"""Throughput micro-benchmarks for spec §4 (bridge) and §5 (consumer).

§4 acceptance: bridge ≥ 1000 msg/s single-thread.
§5 acceptance: consumer sustains ≥ 1000 row/s insertion.

§4 path:  burst-publish to MQTT -> bridge -> Kafka, measure Kafka arrival rate.
§5 path:  directly produce to pdm.features Kafka topic -> consumer -> TimescaleDB,
          measure DB insert rate.

Each phase starts its own subprocess for the SUT, drains, then tears down.
Writes results to results/throughput.json and prints a one-line summary.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
import psycopg
import typer
from confluent_kafka import Consumer, Producer

log = logging.getLogger("bench")

app = typer.Typer(add_completion=False, no_args_is_help=False)

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS = REPO_ROOT / "results"
RESULTS.mkdir(exist_ok=True)

_FEATURE_TEMPLATE = {
    "rms": 0.75,
    "peak_to_peak": 2.0,
    "crest": 1.4,
    "kurtosis": -1.5,
    "peak_1x": 1.0,
    "peak_2x": 0.3,
    "peak_3x": 0.15,
    "envelope_peak": 0.02,
}


def _start_proc(name: str, args: list[str], log_path: Path) -> subprocess.Popen:
    log.info("start %s -> %s", name, log_path)
    fh = log_path.open("w")
    env = {"PYTHONUNBUFFERED": "1", **os.environ}
    return subprocess.Popen(args, cwd=REPO_ROOT, stdout=fh, stderr=subprocess.STDOUT, env=env)


def _stop(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        if p.poll() is None:
            p.terminate()
    deadline = time.monotonic() + 6
    for p in procs:
        try:
            p.wait(timeout=max(0.3, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            p.kill()


def _drain_kafka_count(bootstrap: str, topic: str, expected: int, timeout_s: float) -> int:
    c = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"bench-drain-{topic}-{int(time.time())}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
            "fetch.min.bytes": 1,
        }
    )
    c.subscribe([topic])
    n = 0
    start = time.time()
    quiet = 0
    while time.time() - start < timeout_s and n < expected:
        m = c.poll(0.5)
        if m and not m.error():
            n += 1
            quiet = 0
        else:
            quiet += 1
            if quiet > 6 and n > 0:
                break
    c.close()
    return n


def bench_bridge(
    mqtt_broker: str,
    mqtt_port: int,
    kafka_bootstrap: str,
    target_msgs: int,
    log_dir: Path,
) -> dict:
    """Burst-publish target_msgs over MQTT, measure Kafka arrival rate.

    Pre-warms the drain Kafka consumer so partition assignment overhead
    is excluded from the measurement window. The reported throughput
    is the rate at which the bridge forwards messages to Kafka, not
    including drain-consumer startup.
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    bridge_log = log_dir / "bridge_bench.log"
    bridge = _start_proc("bridge", [sys.executable, "-m", "ingest.bridge"], bridge_log)
    time.sleep(2.5)  # MQTT subscribe + Kafka producer init

    # Pre-create + warm-up drain consumer with assignment confirmed.
    drain = Consumer(
        {
            "bootstrap.servers": kafka_bootstrap,
            "group.id": f"bench-bridge-drain-{int(time.time())}",
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
            "fetch.min.bytes": 1,
            "fetch.wait.max.ms": 5,
        }
    )
    drain.subscribe(["pdm.features"])
    # Force assignment by polling until we have partitions assigned.
    warmup_end = time.time() + 5
    while time.time() < warmup_end and not drain.assignment():
        drain.poll(0.1)
    log.info("drain consumer warmed, assignment=%d partitions", len(drain.assignment()))

    pub = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id="bench-pub",
        protocol=mqtt.MQTTv5,
    )
    pub.max_inflight_messages_set(200)
    pub.max_queued_messages_set(target_msgs + 100)
    pub.connect(mqtt_broker, mqtt_port)
    pub.loop_start()

    payload_template = {
        "device_id": "bench001",
        "features": _FEATURE_TEMPLATE,
        "fault_label": "healthy",
        "severity": 0.0,
    }

    t0 = time.monotonic()
    infos = []
    for i in range(target_msgs):
        payload_template["ts"] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
        infos.append(
            pub.publish(
                "pdm/bench/bench001",
                json.dumps(payload_template),
                qos=1,
            )
        )
    # Block until paho has confirmed each PUBACK from EMQX. Without this
    # `loop_stop()` would drop the in-flight queue and the measurement
    # would under-count.
    for info in infos:
        info.wait_for_publish(timeout=30)
    pub_done = time.monotonic()
    log.info("published+acked %d msgs in %.2fs (%.0f msg/s producer-side)",
             target_msgs, pub_done - t0, target_msgs / max(pub_done - t0, 1e-3))

    # Drain from warmed consumer. Stamp first/last arrival to compute
    # actual bridge throughput, separated from drain idle time.
    arrived = 0
    first_arrival = None
    last_arrival = None
    deadline = time.time() + 60
    quiet = 0
    while time.time() < deadline and arrived < target_msgs:
        m = drain.poll(0.5)
        if m and not m.error():
            now = time.monotonic()
            if first_arrival is None:
                first_arrival = now
            last_arrival = now
            arrived += 1
            quiet = 0
        else:
            quiet += 1
            if quiet > 12 and arrived > 0:
                break
    drain.close()
    pub.loop_stop()
    pub.disconnect()
    _stop([bridge])

    e2e_elapsed = (last_arrival or time.monotonic()) - t0
    bridge_span = (last_arrival - first_arrival) if (first_arrival and last_arrival) else 0
    bridge_throughput = round(arrived / max(bridge_span, 1e-3)) if bridge_span > 0 else 0
    return {
        "target_msgs": target_msgs,
        "arrived_kafka": arrived,
        "e2e_elapsed_s": round(e2e_elapsed, 2),
        "bridge_active_span_s": round(bridge_span, 3),
        "bridge_throughput_msg_per_s": bridge_throughput,
        "publisher_rate_msg_per_s": round(target_msgs / max(pub_done - t0, 1e-3)),
        # legacy key kept for the report writer
        "throughput_msg_per_s": bridge_throughput,
    }


def bench_consumer(
    kafka_bootstrap: str,
    db_dsn: str,
    target_rows: int,
    log_dir: Path,
) -> dict:
    """Directly produce target_rows to pdm.features Kafka topic; measure DB inserts."""
    log_dir.mkdir(parents=True, exist_ok=True)
    consumer_log = log_dir / "consumer_bench.log"

    # Pre-clean DB rows for this benchmark device
    with psycopg.connect(db_dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM device_features WHERE device_id LIKE 'bench-cons%'")
        conn.commit()

    consumer_proc = _start_proc(
        "consumer", [sys.executable, "-m", "ingest.consumer"], consumer_log
    )
    time.sleep(2.5)  # subscribe + DDL

    producer = Producer(
        {
            "bootstrap.servers": kafka_bootstrap,
            "linger.ms": 5,
            "batch.size": 65536,
            "acks": "1",
        }
    )

    payload_template = {
        "features": _FEATURE_TEMPLATE,
        "fault_label": "healthy",
        "severity": 0.0,
    }

    t0 = time.monotonic()
    for i in range(target_rows):
        device_id = f"bench-cons{i % 4:02d}"  # 4 devices to spread across partitions
        payload_template["device_id"] = device_id
        # Unique timestamp per (device_id, i) so UNIQUE INDEX doesn't dedupe.
        payload_template["ts"] = datetime(
            2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%S.") + f"{i:06d}Z"
        producer.produce(
            "pdm.features",
            key=device_id.encode("utf-8"),
            value=json.dumps(payload_template).encode("utf-8"),
        )
        if i % 1000 == 0:
            producer.poll(0)
    producer.flush(timeout=30)
    produced_done = time.monotonic()
    log.info(
        "produced %d to Kafka in %.2fs (%.0f msg/s)",
        target_rows,
        produced_done - t0,
        target_rows / max(produced_done - t0, 1e-3),
    )

    # Poll DB and record first / last insert time to compute actual rate
    deadline = time.monotonic() + 60
    rows = 0
    first_seen_t = None
    last_seen_t = None
    while time.monotonic() < deadline:
        with psycopg.connect(db_dsn) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*), min(ts), max(ts) FROM device_features WHERE device_id LIKE 'bench-cons%'"
            )
            rows, min_ts, max_ts = cur.fetchone()
            if rows and first_seen_t is None:
                first_seen_t = time.monotonic()
            if rows:
                last_seen_t = time.monotonic()
        if rows >= target_rows:
            break
        time.sleep(0.1)
    drain_done = time.monotonic()
    elapsed = drain_done - t0

    _stop([consumer_proc])

    with psycopg.connect(db_dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM device_features WHERE device_id LIKE 'bench-cons%'")
        conn.commit()

    consumer_active = (last_seen_t - first_seen_t) if (first_seen_t and last_seen_t) else elapsed
    consumer_throughput = round(rows / max(consumer_active, 1e-3))
    return {
        "target_rows": target_rows,
        "rows_inserted": rows,
        "e2e_elapsed_s": round(elapsed, 2),
        "consumer_active_span_s": round(consumer_active, 3),
        "consumer_throughput_row_per_s": consumer_throughput,
        "producer_rate_msg_per_s": round(target_rows / max(produced_done - t0, 1e-3)),
        # legacy key kept for the report writer
        "throughput_row_per_s": consumer_throughput,
    }


@app.command()
def main(
    mqtt_broker: str = typer.Option("localhost"),
    mqtt_port: int = typer.Option(1883),
    kafka_bootstrap: str = typer.Option("localhost:9094"),
    db_dsn: str = typer.Option("postgresql://pdm:pdm@localhost:5432/pdm"),
    bridge_msgs: int = typer.Option(3000),
    consumer_rows: int = typer.Option(5000),
    log_dir: Path = typer.Option(RESULTS / "bench-logs"),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    log.info("=== §4 bridge throughput ===")
    bridge_result = bench_bridge(
        mqtt_broker, mqtt_port, kafka_bootstrap, bridge_msgs, log_dir
    )
    log.info("bridge: %s", bridge_result)

    log.info("=== §5 consumer throughput ===")
    cons_result = bench_consumer(kafka_bootstrap, db_dsn, consumer_rows, log_dir)
    log.info("consumer: %s", cons_result)

    out = {
        "spec_targets": {"bridge_msg_per_s_min": 1000, "consumer_row_per_s_min": 1000},
        "bridge": bridge_result,
        "consumer": cons_result,
    }
    (RESULTS / "throughput.json").write_text(json.dumps(out, indent=2))
    print("\nSUMMARY")
    print(f"  §4 bridge:   {bridge_result['throughput_msg_per_s']:5d} msg/s  "
          f"(target ≥1000, {'PASS' if bridge_result['throughput_msg_per_s'] >= 1000 else 'FAIL'})")
    print(f"  §5 consumer: {cons_result['throughput_row_per_s']:5d} row/s  "
          f"(target ≥1000, {'PASS' if cons_result['throughput_row_per_s'] >= 1000 else 'FAIL'})")


if __name__ == "__main__":
    app()
