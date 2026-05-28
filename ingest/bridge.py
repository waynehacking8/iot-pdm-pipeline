"""MQTT → Kafka bridge.

Subscribes to ``pdm/#`` on the MQTT broker and republishes each message
to the Kafka topic ``pdm.features``. The Kafka key is set to the
device_id parsed from the MQTT topic, preserving per-device ordering
when the Kafka consumer group fans out.

Why standalone (not the EMQX built-in bridge): an explicit Python
process makes the data flow visible and debuggable. EMQX's built-in
Kafka bridge is the production-grade alternative once the architecture
is settled.

TODO:
    - Connect to MQTT broker and Kafka.
    - Map MQTT topic suffix to Kafka key.
    - Respect Kafka producer's send buffer (do not block MQTT loop).
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("To be implemented in Phase 2.2")


if __name__ == "__main__":
    main()
