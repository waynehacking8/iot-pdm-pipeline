"""Kafka -> TimescaleDB consumer.

Consumes ``pdm.features`` and batch-inserts rows into the
``device_features`` hypertable. Batches by 100 messages or 1 second,
whichever comes first. Idempotent across kill -9: a UNIQUE index on
(device_id, ts) + ON CONFLICT DO NOTHING absorbs re-deliveries when
Kafka offset commit didn't make it before the crash.

See ``docs/specifications.md`` section 5.
"""

from __future__ import annotations

import json
import logging
import signal as os_signal
import time
from datetime import datetime
from typing import Optional

import psycopg
import typer
from confluent_kafka import Consumer, KafkaException, TopicPartition

log = logging.getLogger("consumer")

app = typer.Typer(add_completion=False, no_args_is_help=False)

KAFKA_TOPIC = "pdm.features"
BATCH_SIZE = 100
# 0.1s flush interval honours spec §8 (E2E latency < 200ms). The spec
# section 5 mentions "100 messages OR 1 second" — see D12.
BATCH_INTERVAL_S = 0.1
POLL_TIMEOUT_S = 0.05

DDL = """
CREATE TABLE IF NOT EXISTS device_features (
    device_id      TEXT        NOT NULL,
    ts             TIMESTAMPTZ NOT NULL,
    rms            DOUBLE PRECISION NOT NULL,
    peak_to_peak   DOUBLE PRECISION NOT NULL,
    crest          DOUBLE PRECISION NOT NULL,
    kurtosis       DOUBLE PRECISION NOT NULL,
    peak_1x        DOUBLE PRECISION NOT NULL,
    peak_2x        DOUBLE PRECISION NOT NULL,
    peak_3x        DOUBLE PRECISION NOT NULL,
    envelope_peak  DOUBLE PRECISION NOT NULL,
    fault_label    TEXT,
    severity       DOUBLE PRECISION
);
SELECT create_hypertable('device_features', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_device_ts
    ON device_features (device_id, ts DESC);
CREATE UNIQUE INDEX IF NOT EXISTS uq_device_ts
    ON device_features (device_id, ts);
"""

CAGG_DDL = """
CREATE MATERIALIZED VIEW IF NOT EXISTS device_features_1m
WITH (timescaledb.continuous) AS
SELECT
    device_id,
    time_bucket('1 minute', ts) AS bucket,
    avg(rms)           AS rms_avg,
    avg(peak_to_peak)  AS pk_pk_avg,
    avg(crest)         AS crest_avg,
    avg(kurtosis)      AS kurtosis_avg,
    avg(peak_1x)       AS peak_1x_avg,
    avg(peak_2x)       AS peak_2x_avg,
    avg(peak_3x)       AS peak_3x_avg,
    avg(envelope_peak) AS env_peak_avg,
    count(*)           AS samples
FROM device_features
GROUP BY device_id, bucket
WITH NO DATA;
"""

CAGG_POLICY = """
SELECT add_continuous_aggregate_policy('device_features_1m',
    start_offset => INTERVAL '2 hours',
    end_offset   => INTERVAL '1 minute',
    schedule_interval => INTERVAL '30 seconds',
    if_not_exists => TRUE);
"""

INSERT_SQL = """
INSERT INTO device_features (
    device_id, ts, rms, peak_to_peak, crest, kurtosis,
    peak_1x, peak_2x, peak_3x, envelope_peak, fault_label, severity
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (device_id, ts) DO NOTHING
"""


def _parse_ts(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


def _row_from(msg_value: bytes) -> Optional[tuple]:
    try:
        obj = json.loads(msg_value)
        f = obj["features"]
        return (
            obj["device_id"],
            _parse_ts(obj["ts"]),
            f["rms"],
            f["peak_to_peak"],
            f["crest"],
            f["kurtosis"],
            f["peak_1x"],
            f["peak_2x"],
            f["peak_3x"],
            f["envelope_peak"],
            obj.get("fault_label"),
            obj.get("severity"),
        )
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        log.warning("skip malformed message: %s", e)
        return None


@app.command()
def main(
    kafka_bootstrap: str = typer.Option("localhost:9094"),
    kafka_group: str = typer.Option("pdm-timescale-writer"),
    db_dsn: str = typer.Option(
        "postgresql://pdm:pdm@localhost:5432/pdm", help="psycopg connection string"
    ),
    duration_s: Optional[float] = typer.Option(None),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    with psycopg.connect(db_dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(DDL)
            try:
                cur.execute(CAGG_DDL)
                cur.execute(CAGG_POLICY)
            except psycopg.Error as e:
                log.warning("continuous aggregate setup skipped: %s", e)
        log.info("schema ready (incl. device_features_1m continuous aggregate)")

    consumer = Consumer(
        {
            "bootstrap.servers": kafka_bootstrap,
            "group.id": kafka_group,
            "enable.auto.commit": False,
            "auto.offset.reset": "earliest",
            "session.timeout.ms": 10000,
        }
    )
    consumer.subscribe([KAFKA_TOPIC])

    stop = {"flag": False}

    def _handle_sig(*_args) -> None:
        stop["flag"] = True

    os_signal.signal(os_signal.SIGINT, _handle_sig)
    os_signal.signal(os_signal.SIGTERM, _handle_sig)

    inserted = 0
    start_t = time.monotonic()

    with psycopg.connect(db_dsn) as conn:
        try:
            while not stop["flag"]:
                if duration_s is not None and (time.monotonic() - start_t) > duration_s:
                    break
                batch_rows: list[tuple] = []
                batch_msgs = []
                batch_start = time.monotonic()
                while (
                    len(batch_rows) < BATCH_SIZE
                    and (time.monotonic() - batch_start) < BATCH_INTERVAL_S
                    and not stop["flag"]
                ):
                    msg = consumer.poll(POLL_TIMEOUT_S)
                    if msg is None:
                        continue
                    if msg.error():
                        log.warning("kafka error: %s", msg.error())
                        continue
                    row = _row_from(msg.value())
                    if row is None:
                        continue
                    batch_rows.append(row)
                    batch_msgs.append(msg)

                if not batch_rows:
                    continue

                with conn.cursor() as cur:
                    cur.executemany(INSERT_SQL, batch_rows)
                conn.commit()
                offsets = [
                    TopicPartition(m.topic(), m.partition(), m.offset() + 1)
                    for m in batch_msgs
                ]
                consumer.commit(offsets=offsets, asynchronous=False)
                inserted += len(batch_rows)
                if inserted % 1000 < BATCH_SIZE:
                    log.info("inserted=%d", inserted)
        finally:
            try:
                consumer.close()
            except KafkaException as e:
                log.error("consumer close failed: %s", e)
            log.info("consumer stop inserted=%d", inserted)


if __name__ == "__main__":
    app()
