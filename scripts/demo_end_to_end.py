"""End-to-end demo entry point.

Sequence:
    1. Assume infrastructure is already running (docker compose up).
    2. Start the simulator publisher with a scripted fault injection
       schedule.
    3. Start the MQTT -> Kafka bridge (in a thread or subprocess).
    4. Start the Kafka -> TimescaleDB consumer.
    5. Start the inference consumer.
    6. Print Grafana URL: http://localhost:3000

This is a developer-facing convenience script; production deployment
would manage each component as a separate service.

TODO:
    - Wire up subprocess management.
    - Wire up a scripted fault timeline (e.g., 60s healthy -> 60s
      imbalance -> 60s misalignment).
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("To be implemented in Phase 4.2")


if __name__ == "__main__":
    main()
