"""MQTT publisher wrapping the synthetic vibration sensor.

Publishes one JSON-encoded feature vector per tick to
``pdm/{plant_id}/{device_id}`` with QoS 1. See ``docs/specifications.md``
section 3.
"""

from __future__ import annotations

import json
import logging
import signal as os_signal
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import paho.mqtt.client as mqtt
import typer

from ml.features import extract_features
from simulator.vibration import FaultMode, SensorConfig, generate_window

log = logging.getLogger("publisher")

app = typer.Typer(add_completion=False, no_args_is_help=False)


@dataclass(frozen=True)
class ScheduleStep:
    after_s: float
    fault_mode: FaultMode
    severity: float


def _load_schedule(path: Optional[Path]) -> list[ScheduleStep]:
    if path is None:
        return []
    raw = json.loads(path.read_text())
    return sorted(
        (
            ScheduleStep(
                after_s=float(step["after_s"]),
                fault_mode=step["fault_mode"],
                severity=float(step["severity"]),
            )
            for step in raw
        ),
        key=lambda s: s.after_s,
    )


def _make_client(client_id: str) -> mqtt.Client:
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv5,
    )
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.max_inflight_messages_set(20)
    client.max_queued_messages_set(1000)
    return client


def _build_payload(
    device_id: str,
    config: SensorConfig,
    window: "np.ndarray",  # noqa: F821 (forward ref to numpy)
) -> bytes:
    feats = extract_features(
        window[0], config.sampling_rate_hz, config.rotation_freq_hz
    )
    payload = {
        "device_id": device_id,
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z",
        "features": feats._asdict(),
        "fault_label": config.fault_mode,
        "severity": config.fault_severity,
    }
    return json.dumps(payload).encode("utf-8")


def _active_config(
    base: SensorConfig, schedule: list[ScheduleStep], elapsed_s: float
) -> SensorConfig:
    active = base
    for step in schedule:
        if elapsed_s >= step.after_s:
            active = replace(
                base, fault_mode=step.fault_mode, fault_severity=step.severity
            )
    return active


@app.command()
def main(
    device: str = typer.Option(..., help="Device id, e.g., d001"),
    plant: str = typer.Option("p001", help="Plant id"),
    rate: float = typer.Option(1.0, help="Publish rate in Hz"),
    broker: str = typer.Option("localhost", help="MQTT broker host"),
    port: int = typer.Option(1883, help="MQTT broker port"),
    fault_mode: str = typer.Option("healthy", help="Initial fault mode"),
    fault_severity: float = typer.Option(0.0, help="Initial fault severity"),
    schedule: Optional[Path] = typer.Option(
        None, help="JSON schedule of fault transitions"
    ),
    duration_s: Optional[float] = typer.Option(
        None, help="Stop after this many seconds (default: run forever)"
    ),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    schedule_steps = _load_schedule(schedule)
    base_config = SensorConfig(
        fault_mode=fault_mode,  # type: ignore[arg-type]
        fault_severity=fault_severity,
    )

    topic = f"pdm/{plant}/{device}"
    client = _make_client(f"sim-{plant}-{device}")
    client.connect_async(broker, port, keepalive=30)
    client.loop_start()

    stop = {"flag": False}

    def _handle_sig(*_args) -> None:
        stop["flag"] = True

    os_signal.signal(os_signal.SIGINT, _handle_sig)
    os_signal.signal(os_signal.SIGTERM, _handle_sig)

    log.info("publisher start device=%s topic=%s rate=%.2fHz", device, topic, rate)
    period = 1.0 / rate
    start = time.monotonic()
    next_tick = start
    published = 0
    dropped = 0

    try:
        while not stop["flag"]:
            now = time.monotonic()
            if now < next_tick:
                time.sleep(min(0.05, next_tick - now))
                continue
            elapsed = now - start
            if duration_s is not None and elapsed > duration_s:
                break
            config = _active_config(base_config, schedule_steps, elapsed)
            window = generate_window(config, duration_s=period)
            payload = _build_payload(device, config, window)
            info = client.publish(topic, payload, qos=1)
            if info.rc == mqtt.MQTT_ERR_QUEUE_SIZE:
                dropped += 1
                if dropped % 100 == 1:
                    log.warning("publish queue full, dropped=%d", dropped)
            else:
                published += 1
                if published % 60 == 0:
                    log.info(
                        "published=%d fault=%s severity=%.2f",
                        published,
                        config.fault_mode,
                        config.fault_severity,
                    )
            next_tick += period
    finally:
        log.info("publisher stop published=%d dropped=%d", published, dropped)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    app()
