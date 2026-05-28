"""Online PdM inference consumer.

Reads ``pdm.features``, scales each feature vector, scores it through
the trained IsolationForest, and writes:
  * the raw score to ``pdm.scores``
  * an alert event to ``pdm.alerts`` when the per-device rolling mean
    of scores falls below the threshold

See ``docs/specifications.md`` section 7.
"""

from __future__ import annotations

import json
import logging
import signal as os_signal
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import typer
from confluent_kafka import Consumer, Producer, TopicPartition

from ml.features import FeatureVector

log = logging.getLogger("inference")

app = typer.Typer(add_completion=False, no_args_is_help=False)

INPUT_TOPIC = "pdm.features"
SCORE_TOPIC = "pdm.scores"
ALERT_TOPIC = "pdm.alerts"

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"


def _features_to_vec(features: dict) -> np.ndarray:
    return np.asarray(
        [features[name] for name in FeatureVector._fields], dtype=np.float64
    )


@app.command()
def main(
    kafka_bootstrap: str = typer.Option("localhost:9094"),
    kafka_group: str = typer.Option("pdm-inference"),
    artifacts_dir: Path = typer.Option(ARTIFACTS_DIR),
    window: int = typer.Option(30, help="Rolling buffer length per device (see D10)"),
    threshold: float = typer.Option(-0.1, help="Alert if rolling-mean score < this"),
    debounce_s: float = typer.Option(600.0, help="Min seconds between alerts per device"),
    duration_s: Optional[float] = typer.Option(None),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    scaler = joblib.load(artifacts_dir / "scaler.joblib")
    model = joblib.load(artifacts_dir / "model.joblib")
    log.info("loaded artifacts from %s", artifacts_dir)

    consumer = Consumer(
        {
            "bootstrap.servers": kafka_bootstrap,
            "group.id": kafka_group,
            "enable.auto.commit": False,
            "auto.offset.reset": "latest",
        }
    )
    consumer.subscribe([INPUT_TOPIC])
    producer = Producer({"bootstrap.servers": kafka_bootstrap, "linger.ms": 10})

    rolling: dict[str, deque] = defaultdict(lambda: deque(maxlen=window))
    last_alert: dict[str, float] = {}
    stats = defaultdict(int)

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
            msg = consumer.poll(0.5)
            if msg is None:
                continue
            if msg.error():
                log.warning("kafka error: %s", msg.error())
                continue
            try:
                obj = json.loads(msg.value())
                device_id = obj["device_id"]
                vec = _features_to_vec(obj["features"]).reshape(1, -1)
            except (KeyError, ValueError, json.JSONDecodeError) as e:
                log.warning("skip malformed: %s", e)
                continue

            scaled = scaler.transform(vec)
            score = float(model.decision_function(scaled)[0])
            rolling[device_id].append(score)
            rolling_mean = float(np.mean(rolling[device_id]))

            score_event = {
                "device_id": device_id,
                "ts": obj.get("ts"),
                "score": score,
                "rolling_mean": rolling_mean,
            }
            producer.produce(
                SCORE_TOPIC,
                key=device_id.encode("utf-8"),
                value=json.dumps(score_event).encode("utf-8"),
            )
            stats["scored"] += 1

            if (
                len(rolling[device_id]) >= max(10, window // 30)
                and rolling_mean < threshold
            ):
                now = time.monotonic()
                if now - last_alert.get(device_id, 0.0) >= debounce_s:
                    alert = {
                        "device_id": device_id,
                        "ts": obj.get("ts"),
                        "rolling_mean": rolling_mean,
                        "threshold": threshold,
                        "buffer_size": len(rolling[device_id]),
                    }
                    producer.produce(
                        ALERT_TOPIC,
                        key=device_id.encode("utf-8"),
                        value=json.dumps(alert).encode("utf-8"),
                    )
                    last_alert[device_id] = now
                    stats["alerts"] += 1
                    log.warning(
                        "ALERT device=%s rolling_mean=%.3f", device_id, rolling_mean
                    )
            producer.poll(0)

            tp = TopicPartition(msg.topic(), msg.partition(), msg.offset() + 1)
            consumer.commit(offsets=[tp], asynchronous=True)

            if stats["scored"] % 500 == 0:
                log.info(
                    "scored=%d alerts=%d devices=%d",
                    stats["scored"],
                    stats["alerts"],
                    len(rolling),
                )
    finally:
        producer.flush(timeout=10)
        consumer.close()
        log.info("inference stop scored=%d alerts=%d", stats["scored"], stats["alerts"])


if __name__ == "__main__":
    app()
