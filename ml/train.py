"""Offline training of the PdM IsolationForest baseline.

Synthesizes a healthy-state dataset using the simulator, extracts
features, fits ``StandardScaler + IsolationForest`` and persists
artifacts under ``ml/artifacts/``.

Spec defaults call for 7 days x 10 devices x 1 Hz = 6e6 samples. That
takes ~5 hours on a laptop to *generate* (the window-by-window
simulator + FFT cost). For the prototype demo we default to a much
smaller sample count and expose ``--n-samples`` so the spec target
can be reached when desired. IsolationForest accuracy plateaus well
before 6e6 samples for this 8-D feature space.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import typer
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from ml.features import FeatureVector, extract_features
from simulator.vibration import SensorConfig, generate_window

log = logging.getLogger("train")

app = typer.Typer(add_completion=False, no_args_is_help=False)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
ARTIFACTS_DIR.mkdir(exist_ok=True)


def generate_feature_matrix(
    n_samples: int,
    fault_mode: str = "healthy",
    severity: float = 0.0,
    rotation_freq_hz: float = 60.0,
    sampling_rate_hz: float = 25_600.0,
    seed: Optional[int] = None,
    log_every: int = 500,
) -> np.ndarray:
    """Sample ``n_samples`` 1-second windows and extract features."""
    if seed is not None:
        np.random.seed(seed)
    config = SensorConfig(
        sampling_rate_hz=sampling_rate_hz,
        rotation_freq_hz=rotation_freq_hz,
        fault_mode=fault_mode,  # type: ignore[arg-type]
        fault_severity=severity,
    )
    rows = np.empty((n_samples, len(FeatureVector._fields)), dtype=np.float64)
    t0 = time.monotonic()
    for i in range(n_samples):
        window = generate_window(config, duration_s=1.0)
        feats = extract_features(window[0], sampling_rate_hz, rotation_freq_hz)
        rows[i] = feats
        if log_every and (i + 1) % log_every == 0:
            rate = (i + 1) / (time.monotonic() - t0)
            log.info(
                "  sampled %d/%d (%s sev=%.2f) %.0f win/s",
                i + 1,
                n_samples,
                fault_mode,
                severity,
                rate,
            )
    return rows


@app.command()
def main(
    n_samples: int = typer.Option(
        6000, help="Number of healthy 1-second windows to synthesize"
    ),
    output_dir: Path = typer.Option(ARTIFACTS_DIR),
    seed: int = typer.Option(42),
    rotation_freq_hz: float = typer.Option(60.0),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    output_dir.mkdir(parents=True, exist_ok=True)

    log.info("synthesizing healthy training set n_samples=%d", n_samples)
    t0 = time.monotonic()
    X = generate_feature_matrix(
        n_samples=n_samples,
        fault_mode="healthy",
        severity=0.0,
        rotation_freq_hz=rotation_freq_hz,
        seed=seed,
    )
    synth_s = time.monotonic() - t0
    log.info("synth done X shape=%s elapsed=%.1fs", X.shape, synth_s)

    scaler = StandardScaler().fit(X)
    Xs = scaler.transform(X)

    log.info("fitting IsolationForest")
    t_fit = time.monotonic()
    model = IsolationForest(
        n_estimators=200,
        contamination=0.01,
        random_state=seed,
        n_jobs=-1,
    ).fit(Xs)
    fit_s = time.monotonic() - t_fit
    log.info("fit done fit_time=%.2fs", fit_s)

    joblib.dump(scaler, output_dir / "scaler.joblib")
    joblib.dump(model, output_dir / "model.joblib")

    summary = {
        "n_samples": int(n_samples),
        "synth_time_s": round(synth_s, 2),
        "fit_time_s": round(fit_s, 2),
        "feature_names": list(FeatureVector._fields),
        "feature_means": {
            name: float(scaler.mean_[i])
            for i, name in enumerate(FeatureVector._fields)
        },
        "feature_stds": {
            name: float(scaler.scale_[i])
            for i, name in enumerate(FeatureVector._fields)
        },
        "model": {
            "type": "IsolationForest",
            "n_estimators": 200,
            "contamination": 0.01,
            "random_state": seed,
        },
        "rotation_freq_hz": rotation_freq_hz,
    }
    (output_dir / "training_summary.json").write_text(json.dumps(summary, indent=2))
    log.info(
        "wrote artifacts to %s (synth=%.1fs fit=%.2fs)",
        output_dir,
        synth_s,
        fit_s,
    )


if __name__ == "__main__":
    app()
