"""Offline experiments + figure / report generator.

Runs CPU-only — does *not* require the docker stack. Steps:

    1. Train (or load) the IsolationForest baseline.
    2. Plot the 5 vibration regimes (time + spectrum).
    3. Plot the 8-feature distributions across regimes.
    4. Evaluate ROC / F1 / detection latency per fault mode.
    5. Aggregate everything into ``results/REPORT.md``.

Output:
    results/figures/*.png
    results/evaluation.json
    results/REPORT.md
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import joblib
import numpy as np
import typer
from sklearn.metrics import f1_score, roc_auc_score, roc_curve

from ml.features import FeatureVector
from ml.train import generate_feature_matrix
from scripts import plots
from simulator.vibration import SensorConfig, generate_window

log = logging.getLogger("experiments")

app = typer.Typer(add_completion=False, no_args_is_help=False)

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = REPO_ROOT / "ml" / "artifacts"
RESULTS = REPO_ROOT / "results"
FIGS = RESULTS / "figures"

FAULT_MODES = ("healthy", "imbalance", "misalignment", "outer_race", "inner_race")
NON_HEALTHY = tuple(m for m in FAULT_MODES if m != "healthy")

SAMPLING_RATE = 25_600.0
ROTATION_FREQ = 60.0


def _train_or_load(n_samples: int):
    scaler_path = ARTIFACTS / "scaler.joblib"
    model_path = ARTIFACTS / "model.joblib"
    summary_path = ARTIFACTS / "training_summary.json"
    if scaler_path.exists() and model_path.exists():
        log.info("loading cached artifacts from %s", ARTIFACTS)
        scaler = joblib.load(scaler_path)
        model = joblib.load(model_path)
        summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
        return scaler, model, summary

    log.info("training fresh model n_samples=%d", n_samples)
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    X = generate_feature_matrix(
        n_samples=n_samples,
        fault_mode="healthy",
        severity=0.0,
        sampling_rate_hz=SAMPLING_RATE,
        rotation_freq_hz=ROTATION_FREQ,
        seed=42,
    )
    synth_s = time.monotonic() - t0

    scaler = StandardScaler().fit(X)
    t_fit = time.monotonic()
    model = IsolationForest(
        n_estimators=200, contamination=0.01, random_state=42, n_jobs=-1
    ).fit(scaler.transform(X))
    fit_s = time.monotonic() - t_fit

    joblib.dump(scaler, scaler_path)
    joblib.dump(model, model_path)
    summary = {
        "n_samples": n_samples,
        "synth_time_s": round(synth_s, 2),
        "fit_time_s": round(fit_s, 2),
        "feature_names": list(FeatureVector._fields),
        "feature_means": {
            n: float(scaler.mean_[i]) for i, n in enumerate(FeatureVector._fields)
        },
        "feature_stds": {
            n: float(scaler.scale_[i]) for i, n in enumerate(FeatureVector._fields)
        },
        "model": {
            "type": "IsolationForest",
            "n_estimators": 200,
            "contamination": 0.01,
            "random_state": 42,
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2))
    return scaler, model, summary


def _plot_waveforms() -> dict[str, str]:
    out: dict[str, str] = {}
    for mode in FAULT_MODES:
        cfg = SensorConfig(
            sampling_rate_hz=SAMPLING_RATE,
            rotation_freq_hz=ROTATION_FREQ,
            fault_mode=mode,  # type: ignore[arg-type]
            fault_severity=0.0 if mode == "healthy" else 1.0,
        )
        np.random.seed(7)
        sig = generate_window(cfg, duration_s=1.0)[0]
        title = f"{mode} (severity={'0' if mode == 'healthy' else '1.0'})"
        path = plots.plot_waveform_and_spectrum(
            sig, SAMPLING_RATE, title, name=f"wave_{mode}.png"
        )
        out[mode] = path.name
        log.info("wrote %s", path)
    return out


def _build_eval_matrix(per_mode: int):
    """Per fault mode generate ``per_mode`` samples; collect features + labels."""
    rows: list[np.ndarray] = []
    labels: list[str] = []
    for mode in FAULT_MODES:
        log.info("synthesizing eval %s n=%d", mode, per_mode)
        m = generate_feature_matrix(
            n_samples=per_mode,
            fault_mode=mode,
            severity=0.0 if mode == "healthy" else 1.0,
            sampling_rate_hz=SAMPLING_RATE,
            rotation_freq_hz=ROTATION_FREQ,
            seed=hash(mode) & 0xFFFF,
            log_every=0,
        )
        rows.append(m)
        labels.extend([mode] * per_mode)
    X = np.vstack(rows)
    return X, np.array(labels)


def _evaluate(scaler, model, X, labels, threshold: float):
    scaled = scaler.transform(X)
    # Lower score = more anomalous. Convert so higher = more anomalous (for ROC).
    raw = model.decision_function(scaled)
    anomaly = -raw

    is_anom_true = (labels != "healthy").astype(int)
    is_anom_pred = (raw < threshold).astype(int)

    overall = {
        "auroc": float(roc_auc_score(is_anom_true, anomaly)),
        "f1_overall": float(f1_score(is_anom_true, is_anom_pred)),
        "false_positive_rate_on_healthy": float(
            (is_anom_pred[labels == "healthy"] == 1).mean()
        ),
        "true_positive_rate_on_faulty": float(
            (is_anom_pred[labels != "healthy"] == 1).mean()
        ),
    }

    per_mode: dict[str, dict] = {}
    fprs: dict[str, np.ndarray] = {}
    tprs: dict[str, np.ndarray] = {}
    healthy_scores = anomaly[labels == "healthy"]
    for mode in NON_HEALTHY:
        mode_scores = anomaly[labels == mode]
        y = np.concatenate(
            [np.zeros(healthy_scores.size), np.ones(mode_scores.size)]
        )
        s = np.concatenate([healthy_scores, mode_scores])
        fpr, tpr, _ = roc_curve(y, s)
        fprs[mode] = fpr
        tprs[mode] = tpr
        # Predictions on this mode using shared threshold:
        y_pred_mode = (s > -threshold).astype(int)
        per_mode[mode] = {
            "auroc": float(roc_auc_score(y, s)),
            "f1": float(f1_score(y, y_pred_mode)),
            "recall": float(((raw[labels == mode]) < threshold).mean()),
        }

    return overall, per_mode, fprs, tprs, raw


def _detection_latency(scaler, model, threshold: float, fault_mode: str, window: int = 30):
    """Generate 60s healthy + 60s fault sequence, return seconds-from-onset to first alert."""
    seq_n = 60
    healthy_feats = generate_feature_matrix(
        n_samples=seq_n,
        fault_mode="healthy",
        severity=0.0,
        sampling_rate_hz=SAMPLING_RATE,
        rotation_freq_hz=ROTATION_FREQ,
        seed=11,
        log_every=0,
    )
    fault_feats = generate_feature_matrix(
        n_samples=seq_n,
        fault_mode=fault_mode,
        severity=1.0,
        sampling_rate_hz=SAMPLING_RATE,
        rotation_freq_hz=ROTATION_FREQ,
        seed=12,
        log_every=0,
    )
    X = np.vstack([healthy_feats, fault_feats])
    raw = model.decision_function(scaler.transform(X))
    rolling = np.array(
        [raw[max(0, i - window + 1) : i + 1].mean() for i in range(raw.size)]
    )
    alert_idxs = np.where(rolling < threshold)[0]
    onset = seq_n
    post_onset = alert_idxs[alert_idxs >= onset]
    latency = int(post_onset[0] - onset) if post_onset.size else None
    return {
        "scores": raw.tolist(),
        "rolling": rolling.tolist(),
        "onset_s": onset,
        "first_alert_s_from_onset": latency,
    }, raw, rolling


@app.command()
def main(
    train_samples: int = typer.Option(6000),
    eval_per_mode: int = typer.Option(400),
    threshold: float = typer.Option(-0.1),
    rolling_window: int = typer.Option(30, help="Rolling buffer (samples)"),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    RESULTS.mkdir(exist_ok=True)
    FIGS.mkdir(parents=True, exist_ok=True)

    scaler, model, training_summary = _train_or_load(train_samples)

    log.info("plotting vibration regimes")
    wave_paths = _plot_waveforms()

    log.info("building evaluation matrix per_mode=%d", eval_per_mode)
    X_eval, y_eval = _build_eval_matrix(eval_per_mode)

    feat_path = plots.plot_feature_distributions(
        X_eval,
        labels=list(y_eval),
        feature_names=list(FeatureVector._fields),
        name="feature_distributions.png",
    )
    log.info("wrote %s", feat_path)

    overall, per_mode, fprs, tprs, _raw = _evaluate(scaler, model, X_eval, y_eval, threshold)
    roc_path = plots.plot_roc(fprs, tprs, name="roc_by_mode.png")
    log.info("wrote %s overall=%s", roc_path, overall)

    log.info("computing detection latency per fault mode")
    latencies = {}
    for mode in NON_HEALTHY:
        result, raw, rolling = _detection_latency(scaler, model, threshold, mode, window=rolling_window)
        latencies[mode] = result["first_alert_s_from_onset"]
        ts = np.arange(raw.size).astype(float)
        plots.plot_score_timeline(
            ts,
            rolling,
            fault_onsets_s=[result["onset_s"]],
            threshold=threshold,
            name=f"timeline_{mode}.png",
            title=f"{mode} — score timeline (rolling window={rolling_window}s)",
        )
        log.info("latency %s: %s s", mode, result["first_alert_s_from_onset"])

    summary = {
        "training": training_summary,
        "evaluation": {
            "threshold": threshold,
            "samples_per_mode": eval_per_mode,
            "rolling_window_s": rolling_window,
            "overall": overall,
            "per_fault_mode": per_mode,
            "detection_latency_s_from_onset": latencies,
        },
        "figures": {
            "waveforms": wave_paths,
            "feature_distributions": feat_path.name,
            "roc_by_mode": roc_path.name,
            "timelines": {m: f"timeline_{m}.png" for m in NON_HEALTHY},
        },
    }
    (RESULTS / "evaluation.json").write_text(json.dumps(summary, indent=2))
    log.info("wrote results/evaluation.json")
    _write_report(summary)


def _write_report(summary: dict) -> None:
    training = summary["training"]
    ev = summary["evaluation"]
    overall = ev["overall"]
    figs = summary["figures"]

    lines: list[str] = []
    lines.append("# IoT PdM Pipeline — Experiment Report\n")
    lines.append(
        "Auto-generated by `scripts/run_experiments.py`. All numbers and "
        "figures come from synthetic data per `docs/specifications.md`.\n"
    )

    lines.append("## 1. Training\n")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Model | {training.get('model', {}).get('type', 'IsolationForest')} |")
    lines.append(f"| n_estimators | {training.get('model', {}).get('n_estimators')} |")
    lines.append(f"| contamination | {training.get('model', {}).get('contamination')} |")
    lines.append(f"| Healthy samples | {training.get('n_samples')} |")
    lines.append(f"| Synthesis time (s) | {training.get('synth_time_s')} |")
    lines.append(f"| Fit time (s) | {training.get('fit_time_s')} |")
    lines.append("")
    lines.append("### Feature statistics on healthy training data\n")
    lines.append("| Feature | Mean | Std |")
    lines.append("|---|---|---|")
    for name in training.get("feature_names", []):
        m = training["feature_means"].get(name)
        s = training["feature_stds"].get(name)
        lines.append(f"| {name} | {m:.4f} | {s:.4f} |")
    lines.append("")

    lines.append("## 2. Phase 1 — Vibration regimes\n")
    for mode, name in figs["waveforms"].items():
        lines.append(f"### {mode}\n\n![{mode}](figures/{name})\n")

    lines.append("## 3. Phase 1.2 — Feature distributions across fault modes\n")
    lines.append(f"![feature distributions](figures/{figs['feature_distributions']})\n")

    lines.append("## 4. Phase 3 — Anomaly detection metrics\n")
    lines.append(f"Threshold = `{ev['threshold']}`, "
                 f"rolling window = `{ev['rolling_window_s']} samples`, "
                 f"samples per mode = `{ev['samples_per_mode']}`.\n")
    lines.append("### Overall (healthy vs all-faulty)\n")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| AUROC | {overall['auroc']:.3f} |")
    lines.append(f"| F1 (threshold = {ev['threshold']}) | {overall['f1_overall']:.3f} |")
    lines.append(
        f"| False-positive rate on healthy | {overall['false_positive_rate_on_healthy']:.3f} |"
    )
    lines.append(
        f"| True-positive rate on faulty | {overall['true_positive_rate_on_faulty']:.3f} |"
    )
    lines.append("")

    lines.append("### Per fault mode\n")
    lines.append("| Fault mode | AUROC | F1 | Recall @ threshold | Detection latency (s from onset) |")
    lines.append("|---|---|---|---|---|")
    for mode, row in ev["per_fault_mode"].items():
        lat = ev["detection_latency_s_from_onset"].get(mode)
        lat_str = "—" if lat is None else str(lat)
        lines.append(
            f"| {mode} | {row['auroc']:.3f} | {row['f1']:.3f} | {row['recall']:.3f} | {lat_str} |"
        )
    lines.append("")
    lines.append(f"![ROC by mode](figures/{figs['roc_by_mode']})\n")

    lines.append("### Score timelines (60s healthy -> 60s fault @ severity 1.0)\n")
    for mode, name in figs["timelines"].items():
        lines.append(f"#### {mode}\n\n![{mode} timeline](figures/{name})\n")

    lines.append("## 5. Reproducibility\n")
    lines.append("```")
    lines.append("python -m scripts.run_experiments \\\n"
                 "    --train-samples 6000 --eval-per-mode 400 --threshold -0.1")
    lines.append("```")
    lines.append("")
    lines.append("Run with the docker stack for the live end-to-end demo:\n")
    lines.append("```")
    lines.append("cd infra && docker compose up -d && cd ..")
    lines.append("python -m ml.train --n-samples 6000   # one-time")
    lines.append("python -m scripts.demo_end_to_end --duration-s 240")
    lines.append("```")

    (RESULTS / "REPORT.md").write_text("\n".join(lines))
    log.info("wrote %s", RESULTS / "REPORT.md")


if __name__ == "__main__":
    app()
