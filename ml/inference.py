"""Online inference consumer.

Reads from Kafka topic ``pdm.features``, applies the trained anomaly
detector, and writes anomaly scores back to a separate Kafka topic
``pdm.scores``. Maintains a rolling 5-minute mean of scores per device;
when the mean exceeds a configurable threshold, emit an alert event to
``pdm.alerts``.

TODO:
    - Load scaler + model from ml/artifacts.
    - Kafka consumer (commit only after producing the score).
    - Rolling-window aggregation per device.
    - Alert emission with debouncing (don't re-alert within 10 minutes).
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("To be implemented in Phase 3.2")


if __name__ == "__main__":
    main()
