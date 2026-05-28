"""MQTT -> Kafka bridge.

Subscribes to ``pdm/#`` on the broker and republishes each message to
the Kafka topic ``pdm.features`` with key = device_id parsed from the
MQTT topic. See ``docs/specifications.md`` section 4.
"""

from __future__ import annotations

import json
import logging
import signal as os_signal
import time
from typing import Optional

import paho.mqtt.client as mqtt
import typer
from confluent_kafka import KafkaException, Producer

log = logging.getLogger("bridge")

app = typer.Typer(add_completion=False, no_args_is_help=False)

KAFKA_TOPIC = "pdm.features"


def _make_producer(bootstrap: str) -> Producer:
    return Producer(
        {
            "bootstrap.servers": bootstrap,
            "acks": "all",
            "linger.ms": 10,
            "batch.size": 16384,
            "compression.type": "none",
            "enable.idempotence": True,
        }
    )


def _make_mqtt(client_id: str) -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv5,
    )
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    return client


def _parse_device_id(topic: str, payload_obj: dict) -> Optional[str]:
    parts = topic.split("/")
    if len(parts) >= 3 and parts[0] == "pdm":
        return parts[2]
    val = payload_obj.get("device_id")
    return str(val) if val is not None else None


@app.command()
def main(
    broker: str = typer.Option("localhost", help="MQTT broker host"),
    port: int = typer.Option(1883, help="MQTT broker port"),
    kafka_bootstrap: str = typer.Option(
        "localhost:9094", help="Kafka bootstrap.servers"
    ),
    duration_s: Optional[float] = typer.Option(
        None, help="Stop after this many seconds (default: run forever)"
    ),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    producer = _make_producer(kafka_bootstrap)
    stats = {"forwarded": 0, "errors": 0}

    def _on_delivery(err, msg) -> None:
        if err is not None:
            stats["errors"] += 1
            log.error("kafka delivery failed: %s", err)

    def _on_message(_client, _userdata, msg) -> None:
        try:
            obj = json.loads(msg.payload)
        except json.JSONDecodeError:
            log.warning("skip non-JSON payload on %s", msg.topic)
            return
        device_id = _parse_device_id(msg.topic, obj)
        if not device_id:
            log.warning("no device_id on %s", msg.topic)
            return
        for attempt in range(10):
            try:
                producer.produce(
                    KAFKA_TOPIC,
                    key=device_id.encode("utf-8"),
                    value=msg.payload,
                    on_delivery=_on_delivery,
                )
                break
            except BufferError:
                producer.poll(0.1)
        else:
            log.error("dropping after 10 retries: kafka queue stuck full")
            return
        producer.poll(0)
        stats["forwarded"] += 1
        if stats["forwarded"] % 1000 == 0:
            log.info(
                "bridge: forwarded %d messages, errors=%d",
                stats["forwarded"],
                stats["errors"],
            )

    def _on_connect(client, _userdata, _flags, reason_code, _props) -> None:
        log.info("mqtt connected rc=%s, subscribing pdm/#", reason_code)
        client.subscribe("pdm/#", qos=1)

    mqtt_client = _make_mqtt("bridge-1")
    mqtt_client.on_connect = _on_connect
    mqtt_client.on_message = _on_message
    mqtt_client.connect(broker, port, keepalive=30)
    mqtt_client.loop_start()

    stop = {"flag": False}

    def _handle_sig(*_args) -> None:
        stop["flag"] = True

    os_signal.signal(os_signal.SIGINT, _handle_sig)
    os_signal.signal(os_signal.SIGTERM, _handle_sig)

    start = time.monotonic()
    try:
        while not stop["flag"]:
            if duration_s is not None and (time.monotonic() - start) > duration_s:
                break
            time.sleep(0.5)
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        try:
            producer.flush(timeout=10)
        except KafkaException as e:
            log.error("producer flush failed: %s", e)
        log.info(
            "bridge stop forwarded=%d errors=%d", stats["forwarded"], stats["errors"]
        )


if __name__ == "__main__":
    app()
