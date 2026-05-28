"""Plotting utilities for experiment reports.

All figures are written under ``results/figures/``. Matplotlib uses
the non-interactive ``Agg`` backend so this can run headless under
docker / CI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

FIG_DIR = Path(__file__).resolve().parent.parent / "results" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def save(fig: plt.Figure, name: str) -> Path:
    out = FIG_DIR / name
    fig.tight_layout()
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return out


def plot_waveform_and_spectrum(
    signal: np.ndarray,
    sampling_rate_hz: float,
    title: str,
    name: str,
    max_freq_hz: float = 1500.0,
    waveform_window_s: float = 0.05,
) -> Path:
    """Two-panel figure: time-domain snippet + magnitude spectrum."""
    fig, (ax_time, ax_freq) = plt.subplots(1, 2, figsize=(11, 3.5))

    n_snip = int(waveform_window_s * sampling_rate_hz)
    t = np.arange(n_snip) / sampling_rate_hz
    ax_time.plot(t * 1000, signal[:n_snip], linewidth=0.7)
    ax_time.set_xlabel("time (ms)")
    ax_time.set_ylabel("acceleration (g)")
    ax_time.set_title(f"{title} — first {int(waveform_window_s * 1000)} ms")
    ax_time.grid(alpha=0.3)

    n = signal.size
    spectrum = np.abs(np.fft.rfft(signal)) * (2.0 / n)
    freqs = np.fft.rfftfreq(n, d=1.0 / sampling_rate_hz)
    mask = freqs <= max_freq_hz
    ax_freq.plot(freqs[mask], spectrum[mask], linewidth=0.7)
    ax_freq.set_xlabel("frequency (Hz)")
    ax_freq.set_ylabel("magnitude")
    ax_freq.set_title(f"{title} — magnitude spectrum")
    ax_freq.grid(alpha=0.3)

    return save(fig, name)


def plot_feature_distributions(
    feature_matrix: np.ndarray,
    labels: Sequence[str],
    feature_names: Sequence[str],
    name: str,
) -> Path:
    """Box-plot of each feature, grouped by fault label."""
    unique_labels = sorted(set(labels))
    n_features = feature_matrix.shape[1]
    rows = (n_features + 3) // 4
    fig, axes = plt.subplots(rows, 4, figsize=(14, 3 * rows))
    axes = np.atleast_2d(axes).ravel()

    for i, fname in enumerate(feature_names):
        ax = axes[i]
        data = [
            feature_matrix[np.array(labels) == lbl, i] for lbl in unique_labels
        ]
        ax.boxplot(data, labels=unique_labels, showfliers=False)
        ax.set_title(fname)
        ax.tick_params(axis="x", labelrotation=30)
        ax.grid(alpha=0.3)
    for j in range(n_features, axes.size):
        axes[j].axis("off")

    fig.suptitle("Feature distributions by fault mode")
    return save(fig, name)


def plot_roc(fpr_by_mode: dict[str, np.ndarray], tpr_by_mode: dict[str, np.ndarray], name: str) -> Path:
    fig, ax = plt.subplots(figsize=(6, 5))
    for mode, fpr in fpr_by_mode.items():
        tpr = tpr_by_mode[mode]
        ax.plot(fpr, tpr, label=mode, linewidth=1.5)
    ax.plot([0, 1], [0, 1], "k--", alpha=0.4, linewidth=0.8)
    ax.set_xlabel("False positive rate")
    ax.set_ylabel("True positive rate")
    ax.set_title("Anomaly-score ROC by fault mode")
    ax.legend(loc="lower right")
    ax.grid(alpha=0.3)
    return save(fig, name)


def plot_score_timeline(
    timestamps_s: np.ndarray,
    scores: np.ndarray,
    fault_onsets_s: Sequence[float],
    threshold: float,
    name: str,
    title: str = "Anomaly score timeline",
) -> Path:
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(timestamps_s, scores, linewidth=0.8, label="score")
    ax.axhline(threshold, color="red", linestyle="--", linewidth=1, label=f"threshold={threshold:.2f}")
    for onset in fault_onsets_s:
        ax.axvline(onset, color="orange", linestyle=":", linewidth=1)
    ax.set_xlabel("time (s)")
    ax.set_ylabel("IsolationForest score (lower = anomalous)")
    ax.set_title(title)
    ax.legend(loc="lower left")
    ax.grid(alpha=0.3)
    return save(fig, name)
