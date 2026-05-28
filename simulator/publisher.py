"""MQTT publisher wrapping the synthetic vibration sensor.

Publishes one JSON-encoded feature vector per second to the topic
``pdm/{plant_id}/{device_id}`` with QoS 1.

CLI:
    python -m simulator.publisher --device d001 --plant p001 \\
        --rate 1.0 --broker localhost --port 1883 \\
        --fault-mode healthy --fault-severity 0.0

The feature vector emitted on each tick is the 8-dim summary computed by
``ml.features.extract_features`` from the most recent 1-second window of
raw signal.

TODO:
    - Connect to broker with reconnect-on-failure.
    - Drive the simulator window-by-window.
    - Optionally inject a scheduled fault transition (e.g., at minute 5
      switch fault_mode from healthy to imbalance with severity 0.5).
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("To be implemented in Phase 1.3")


if __name__ == "__main__":
    main()
