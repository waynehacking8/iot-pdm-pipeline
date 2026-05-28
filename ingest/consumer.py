"""Kafka → TimescaleDB writer.

Consumes the ``pdm.features`` topic and batch-inserts into a TimescaleDB
hypertable ``device_features``. Batches by 100 messages or 1 second,
whichever comes first, to balance throughput and end-to-end latency.

Schema (created on first run if absent):
    CREATE TABLE device_features (
        device_id TEXT NOT NULL,
        ts TIMESTAMPTZ NOT NULL,
        rms FLOAT NOT NULL,
        peak_to_peak FLOAT NOT NULL,
        crest FLOAT NOT NULL,
        kurtosis FLOAT NOT NULL,
        peak_1x FLOAT NOT NULL,
        peak_2x FLOAT NOT NULL,
        peak_3x FLOAT NOT NULL,
        envelope_peak FLOAT NOT NULL
    );
    SELECT create_hypertable('device_features', 'ts');
    CREATE INDEX ON device_features (device_id, ts DESC);

TODO:
    - Implement Kafka consumer with auto-commit disabled.
    - Implement batch insert with psycopg.
    - Idempotency on restart (commit offset only after DB write succeeds).
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("To be implemented in Phase 2.3")


if __name__ == "__main__":
    main()
