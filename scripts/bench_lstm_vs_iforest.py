"""Train LSTM autoencoder on GPU, benchmark against IsolationForest baseline.

Outputs:
    ml/artifacts/lstm_autoencoder.pt
    results/figures/lstm_training_loss.png
    results/figures/lstm_vs_iforest_roc.png
    results/lstm_vs_iforest.json
    (Appends a section to results/REPORT.md via run_experiments overwrite is NOT done here;
     numbers are folded into the report manually in run_experiments.)
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import joblib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import torch
import typer
from sklearn.metrics import roc_auc_score, roc_curve

from ml import lstm_autoencoder as la
from ml.train import generate_feature_matrix

log = logging.getLogger("bench-lstm")
app = typer.Typer(add_completion=False, no_args_is_help=False)

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS = REPO_ROOT / "results"
FIGS = RESULTS / "figures"
ARTIFACTS = REPO_ROOT / "ml" / "artifacts"

FAULT_MODES = ("healthy", "imbalance", "misalignment", "outer_race", "inner_race")
NON_HEALTHY = tuple(m for m in FAULT_MODES if m != "healthy")


@app.command()
def main(
    train_samples: int = typer.Option(9000, help="Healthy samples for LSTM training"),
    eval_per_mode: int = typer.Option(900, help="Samples per mode for evaluation"),
    epochs: int = typer.Option(30),
    seq_len: int = typer.Option(30),
    batch_size: int = typer.Option(64),
    lr: float = typer.Option(1e-3),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    FIGS.mkdir(parents=True, exist_ok=True)

    log.info("device: %s (cuda=%s)",
             "cuda" if torch.cuda.is_available() else "cpu",
             torch.cuda.is_available())
    if torch.cuda.is_available():
        log.info("gpu: %s capability=%s",
                 torch.cuda.get_device_name(0),
                 torch.cuda.get_device_capability(0))

    log.info("loading IsolationForest baseline artifacts")
    scaler = joblib.load(ARTIFACTS / "scaler.joblib")
    iforest = joblib.load(ARTIFACTS / "model.joblib")

    # ---- LSTM training ----
    log.info("synthesizing %d healthy windows for LSTM training", train_samples)
    X_train = generate_feature_matrix(
        n_samples=train_samples,
        fault_mode="healthy",
        severity=0.0,
        seed=23,
        log_every=0,
    )
    X_train_scaled = scaler.transform(X_train)

    cfg = la.LSTMConfig(input_dim=8, hidden_dim=16, num_layers=2, seq_len=seq_len)
    t0 = time.monotonic()
    model, history = la.train_autoencoder(
        X_train_scaled, cfg=cfg, epochs=epochs, batch_size=batch_size, lr=lr
    )
    train_time_s = time.monotonic() - t0
    la.save_artifacts(model, history)
    log.info("LSTM training done in %.1fs (final loss = %.6f)",
             train_time_s, history[-1])

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(range(1, len(history) + 1), history, marker="o", markersize=3)
    ax.set_xlabel("epoch")
    ax.set_ylabel("reconstruction MSE")
    ax.set_title(f"LSTM autoencoder training (final={history[-1]:.5f})")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIGS / "lstm_training_loss.png", dpi=120)
    plt.close(fig)
    log.info("wrote %s", FIGS / "lstm_training_loss.png")

    # ---- Evaluation ----
    log.info("building evaluation matrix per_mode=%d", eval_per_mode)
    X_eval_blocks = []
    labels = []
    for mode in FAULT_MODES:
        m = generate_feature_matrix(
            n_samples=eval_per_mode,
            fault_mode=mode,
            severity=0.0 if mode == "healthy" else 1.0,
            seed=hash(mode) & 0xFFFF,
            log_every=0,
        )
        X_eval_blocks.append(m)
        labels.extend([mode] * eval_per_mode)
    X_eval = np.vstack(X_eval_blocks)
    y_eval = np.array(labels)
    X_eval_scaled = scaler.transform(X_eval)

    # IsolationForest: anomaly = -decision_function (higher = more anomalous)
    iforest_score = -iforest.decision_function(X_eval_scaled)

    # LSTM: reconstruction MSE per *sequence*. Group samples into sequences
    # of length seq_len within each mode. Drop tail per mode for clean
    # alignment.
    n_seq_per_mode = eval_per_mode // seq_len
    if n_seq_per_mode < 2:
        raise typer.BadParameter(
            f"eval_per_mode={eval_per_mode} too small for seq_len={seq_len}"
        )
    lstm_score_seq: list[float] = []
    lstm_label_seq: list[str] = []
    for mi, mode in enumerate(FAULT_MODES):
        block = X_eval_scaled[mi * eval_per_mode : (mi + 1) * eval_per_mode]
        scores = la.score_features(model, block)
        lstm_score_seq.extend(scores.tolist())
        lstm_label_seq.extend([mode] * len(scores))

    lstm_score_arr = np.array(lstm_score_seq)
    lstm_label_arr = np.array(lstm_label_seq)
    lstm_y_true = (lstm_label_arr != "healthy").astype(int)

    # Also compute per-sample IF metrics for comparable single number
    if_y_true = (y_eval != "healthy").astype(int)

    overall = {
        "iforest": {
            "auroc": float(roc_auc_score(if_y_true, iforest_score)),
        },
        "lstm": {
            "auroc": float(roc_auc_score(lstm_y_true, lstm_score_arr)),
            "training_time_s": round(train_time_s, 2),
            "epochs": epochs,
            "final_loss": float(history[-1]),
            "n_train_samples": train_samples,
            "n_eval_sequences": int(lstm_score_arr.size),
        },
    }

    per_mode = {}
    fprs = {"iforest": {}, "lstm": {}}
    tprs = {"iforest": {}, "lstm": {}}
    healthy_lstm = lstm_score_arr[lstm_label_arr == "healthy"]
    healthy_if = iforest_score[y_eval == "healthy"]
    for mode in NON_HEALTHY:
        # IsolationForest per-sample
        if_mode = iforest_score[y_eval == mode]
        y = np.concatenate([np.zeros(healthy_if.size), np.ones(if_mode.size)])
        s = np.concatenate([healthy_if, if_mode])
        fpr, tpr, _ = roc_curve(y, s)
        fprs["iforest"][mode] = fpr
        tprs["iforest"][mode] = tpr
        # LSTM per-sequence
        lstm_mode = lstm_score_arr[lstm_label_arr == mode]
        y_l = np.concatenate([np.zeros(healthy_lstm.size), np.ones(lstm_mode.size)])
        s_l = np.concatenate([healthy_lstm, lstm_mode])
        fpr_l, tpr_l, _ = roc_curve(y_l, s_l)
        fprs["lstm"][mode] = fpr_l
        tprs["lstm"][mode] = tpr_l
        per_mode[mode] = {
            "iforest_auroc": float(roc_auc_score(y, s)),
            "lstm_auroc": float(roc_auc_score(y_l, s_l)),
        }

    # ---- ROC comparison plot ----
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for detector, ax in zip(("iforest", "lstm"), axes):
        for mode in NON_HEALTHY:
            ax.plot(fprs[detector][mode], tprs[detector][mode], label=mode)
        ax.plot([0, 1], [0, 1], "k--", alpha=0.4)
        ax.set_xlabel("False positive rate")
        ax.set_title(
            f"{'IsolationForest (per sample)' if detector == 'iforest' else 'LSTM (per 30-step sequence)'}"
            f" — AUROC overall = {overall[detector]['auroc']:.3f}"
        )
        ax.legend(loc="lower right", fontsize=9)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("True positive rate")
    fig.suptitle(
        f"LSTM autoencoder vs IsolationForest — synthetic eval ({eval_per_mode} samples/mode)"
    )
    fig.tight_layout()
    fig.savefig(FIGS / "lstm_vs_iforest_roc.png", dpi=120, bbox_inches="tight")
    plt.close(fig)
    log.info("wrote %s", FIGS / "lstm_vs_iforest_roc.png")

    summary = {
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "gpu": (
            {
                "name": torch.cuda.get_device_name(0),
                "capability": list(torch.cuda.get_device_capability(0)),
                "total_memory_GB": round(
                    torch.cuda.get_device_properties(0).total_memory / 1e9, 1
                ),
            }
            if torch.cuda.is_available()
            else None
        ),
        "model_config": cfg.__dict__,
        "training": {
            "n_train_samples": train_samples,
            "epochs": epochs,
            "batch_size": batch_size,
            "lr": lr,
            "train_time_s": round(train_time_s, 2),
            "final_loss": float(history[-1]),
        },
        "evaluation": {
            "eval_per_mode": eval_per_mode,
            "seq_len": seq_len,
            "overall": overall,
            "per_fault_mode": per_mode,
        },
        "figures": {
            "training_loss": "figures/lstm_training_loss.png",
            "roc_vs_iforest": "figures/lstm_vs_iforest_roc.png",
        },
    }
    (RESULTS / "lstm_vs_iforest.json").write_text(json.dumps(summary, indent=2))
    log.info("wrote %s", RESULTS / "lstm_vs_iforest.json")

    print("\nLSTM autoencoder vs IsolationForest")
    print(f"  IsolationForest overall AUROC: {overall['iforest']['auroc']:.4f}")
    print(f"  LSTM autoencoder overall AUROC: {overall['lstm']['auroc']:.4f}")
    print(f"  Training time: {train_time_s:.1f}s on {summary['device']}")
    print("  Per-mode AUROC:")
    for mode, row in per_mode.items():
        print(f"    {mode:14s}  IF={row['iforest_auroc']:.3f}  LSTM={row['lstm_auroc']:.3f}")


if __name__ == "__main__":
    app()
