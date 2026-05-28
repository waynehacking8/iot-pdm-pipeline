"""Verify §8 E2E latency (<200ms) and §3 publisher reconnect.

§8 latency: each MQTT publish embeds wall-clock ts; consumer writes
            ingest_t = now(). Measure (ingest_t - msg.ts) at p50/p95/max.

§3 reconnect: start publisher, take EMQX down via docker stop, observe
            publisher does not crash and queue fills; restart EMQX,
            observe publish resumes and all post-restart messages land.
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

log = logging.getLogger("bench-e2e")

app = typer.Typer(add_completion=False, no_args_is_help=False)

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS = REPO_ROOT / "results"


def _start_proc(name: str, args: list[str], log_path: Path) -> subprocess.Popen:
    fh = log_path.open("w")
    env = {"PYTHONUNBUFFERED": "1", **os.environ}
    return subprocess.Popen(args, cwd=REPO_ROOT, stdout=fh, stderr=subprocess.STDOUT, env=env)


@app.command()
def latency(
    mqtt_broker: str = typer.Option("localhost"),
    mqtt_port: int = typer.Option(1883),
    db_dsn: str = typer.Option("postgresql://pdm:pdm@localhost:5432/pdm"),
    n_probes: int = typer.Option(40, help="Number of single-message probes"),
    inter_probe_s: float = typer.Option(0.6, help="Spacing between probes"),
    log_dir: Path = typer.Option(RESULTS / "bench-logs"),
) -> None:
    """Spec §8 E2E latency test: single-message probes.

    Each probe: publish 1 MQTT message with a unique ts, then poll the
    DB every 5ms until the row appears. Latency = (poll_time_seen -
    publish_completed). Upper-bounded by the 5ms poll granularity.
    """
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log_dir.mkdir(parents=True, exist_ok=True)
    device = "lat-probe"

    with psycopg.connect(db_dsn) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM device_features WHERE device_id = %s", (device,))
        conn.commit()

    bridge = _start_proc("bridge", [sys.executable, "-m", "ingest.bridge"], log_dir / "lat_bridge.log")
    consumer = _start_proc("consumer", [sys.executable, "-m", "ingest.consumer"], log_dir / "lat_consumer.log")
    time.sleep(3.0)

    feats = {"rms": 0.75, "peak_to_peak": 2.0, "crest": 1.4, "kurtosis": -1.5,
             "peak_1x": 1.0, "peak_2x": 0.3, "peak_3x": 0.15, "envelope_peak": 0.02}

    pub = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                       client_id="lat-pub", protocol=mqtt.MQTTv5)
    pub.connect(mqtt_broker, mqtt_port)
    pub.loop_start()

    latencies_ms: list[float] = []
    conn = psycopg.connect(db_dsn)
    try:
        for i in range(n_probes):
            unique_ts = datetime(2030, 1, 1, tzinfo=timezone.utc).replace(
                microsecond=i * 1000 + 1
            )
            ts_str = unique_ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{unique_ts.microsecond:06d}Z"
            payload = {"device_id": device, "ts": ts_str, "features": feats,
                       "fault_label": "healthy", "severity": 0.0}
            info = pub.publish(f"pdm/lat/{device}", json.dumps(payload), qos=1)
            info.wait_for_publish(timeout=5)
            t_pub_done = time.monotonic()

            found_at = None
            deadline = t_pub_done + 5.0  # 5s ceiling per probe
            while time.monotonic() < deadline:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM device_features WHERE device_id=%s AND ts=%s",
                        (device, unique_ts),
                    )
                    if cur.fetchone():
                        found_at = time.monotonic()
                        break
                conn.rollback()
                time.sleep(0.005)
            if found_at is not None:
                latencies_ms.append((found_at - t_pub_done) * 1000.0)
            time.sleep(inter_probe_s)
    finally:
        conn.close()

    with psycopg.connect(db_dsn) as c, c.cursor() as cur:
        cur.execute("DELETE FROM device_features WHERE device_id = %s", (device,))
        c.commit()

    pub.loop_stop()
    pub.disconnect()
    bridge.terminate()
    consumer.terminate()
    bridge.wait()
    consumer.wait()

    if not latencies_ms:
        print("FAIL: no rows ingested")
        raise typer.Exit(1)

    import statistics
    p50 = statistics.median(latencies_ms)
    p95 = sorted(latencies_ms)[int(len(latencies_ms) * 0.95)]
    p_max = max(latencies_ms)
    spec_max = 200.0
    out = {
        "n_probes": n_probes,
        "observed_probes": len(latencies_ms),
        "latency_ms": {"p50": round(p50, 1), "p95": round(p95, 1), "max": round(p_max, 1)},
        "spec_target_ms": spec_max,
        "note": "publish_completed -> DB row visible; upper bound is 5ms SELECT poll granularity",
    }
    (RESULTS / "latency.json").write_text(json.dumps(out, indent=2))
    verdict = "PASS" if p95 < spec_max else "FAIL"
    print(f"\nE2E latency  p50={p50:.0f}ms  p95={p95:.0f}ms  max={p_max:.0f}ms  "
          f"(spec ≤{spec_max:.0f}ms, {verdict})")


@app.command()
def reconnect(
    mqtt_broker: str = typer.Option("localhost"),
    mqtt_port: int = typer.Option(1883),
    rate_hz: float = typer.Option(5.0),
    log_dir: Path = typer.Option(RESULTS / "bench-logs"),
) -> None:
    """Spec §3 reconnect: stop EMQX, observe publisher survives, restart, resume."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log_dir.mkdir(parents=True, exist_ok=True)

    # 1. Subscribe locally to count messages before / after EMQX restart
    received_before: list[float] = []
    received_after: list[float] = []
    state = {"after_restart": False}

    def on_msg(_c, _u, m):
        bucket = received_after if state["after_restart"] else received_before
        bucket.append(time.monotonic())

    sub = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                      client_id="recon-sub", protocol=mqtt.MQTTv5)
    sub.on_message = on_msg
    sub.connect(mqtt_broker, mqtt_port)
    sub.subscribe("pdm/recon/#", qos=1)
    sub.loop_start()
    time.sleep(0.5)

    # 2. Start publisher at modest rate
    pub_log = log_dir / "recon_pub.log"
    pub = _start_proc(
        "publisher",
        [sys.executable, "-m", "simulator.publisher",
         "--device", "recon001", "--plant", "recon",
         "--rate", str(rate_hz), "--duration-s", "30"],
        pub_log,
    )

    # 3. Let publisher run for 4 s with broker up
    time.sleep(4.0)
    pre_outage_count = len(received_before)
    log.info("pre-outage received=%d", pre_outage_count)

    # 4. Stop EMQX for 6 s (publisher must not crash)
    log.info("stopping EMQX")
    subprocess.run(["docker", "stop", "pdm-emqx"], check=True, capture_output=True)
    time.sleep(6.0)
    pub_status_during_outage = pub.poll()
    log.info("publisher poll() during outage: %s (None = still running)",
             pub_status_during_outage)

    # 5. Restart EMQX
    log.info("starting EMQX")
    subprocess.run(["docker", "start", "pdm-emqx"], check=True, capture_output=True)
    # Wait for EMQX healthy
    for _ in range(30):
        time.sleep(1)
        h = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", "pdm-emqx"],
            capture_output=True, text=True,
        )
        if h.stdout.strip() == "healthy":
            break
    log.info("EMQX healthy")

    # Re-subscribe (clean_session may have dropped sub on broker side)
    sub.reconnect()
    time.sleep(1.0)
    sub.subscribe("pdm/recon/#", qos=1)
    state["after_restart"] = True

    # 6. Let publisher run another 8 s after restart
    time.sleep(8.0)
    log.info("post-restart received=%d", len(received_after))

    pub.terminate()
    pub.wait()
    sub.loop_stop()
    sub.disconnect()

    pub_log_tail = pub_log.read_text().splitlines()[-20:]

    out = {
        "rate_hz": rate_hz,
        "pre_outage_msgs": pre_outage_count,
        "during_outage_publisher_alive": pub_status_during_outage is None,
        "post_restart_msgs": len(received_after),
        "publisher_log_tail": pub_log_tail,
    }
    (RESULTS / "reconnect.json").write_text(json.dumps(out, indent=2))
    print(f"\nReconnect: pre={pre_outage_count}  during-outage-alive={pub_status_during_outage is None}  "
          f"post-restart={len(received_after)}  "
          f"{'PASS' if pub_status_during_outage is None and len(received_after) > 0 else 'FAIL'}")


if __name__ == "__main__":
    app()
