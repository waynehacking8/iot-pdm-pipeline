"""Pull the live demo's TimescaleDB rows + Kafka score / alert events and
plot the end-to-end timeline.

Run after ``scripts/demo_end_to_end.py`` finishes. Produces:
    results/figures/live_features.png
    results/figures/live_scores.png
    results/live_summary.json
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import psycopg
import typer
from confluent_kafka import Consumer

log = logging.getLogger("plot-live")

app = typer.Typer(add_completion=False, no_args_is_help=False)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIG_DIR = REPO_ROOT / "results" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)
RESULTS = REPO_ROOT / "results"

_FAULT_COLORS = {
    "healthy": "#2ca02c",
    "imbalance": "#ff7f0e",
    "misalignment": "#9467bd",
    "outer_race": "#d62728",
    "inner_race": "#8c564b",
}


def _drain_topic(bootstrap: str, topic: str, timeout_s: float = 6.0) -> list[dict]:
    c = Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"live-plot-{topic}-{int(time.time())}",
            "auto.offset.reset": "earliest",
            "enable.auto.commit": False,
        }
    )
    c.subscribe([topic])
    out: list[dict] = []
    start = time.time()
    while time.time() - start < timeout_s:
        m = c.poll(1.0)
        if m and not m.error():
            out.append(json.loads(m.value()))
    c.close()
    return out


@app.command()
def main(
    db_dsn: str = typer.Option("postgresql://pdm:pdm@localhost:5432/pdm"),
    kafka_bootstrap: str = typer.Option("localhost:9094"),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    log.info("querying TimescaleDB")
    with psycopg.connect(db_dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT ts, device_id, rms, peak_1x, peak_2x, peak_3x, kurtosis, fault_label
            FROM device_features ORDER BY ts
            """
        )
        rows = cur.fetchall()
    log.info("rows=%d", len(rows))

    if not rows:
        log.error("no rows in device_features — run demo first")
        raise typer.Exit(1)

    ts = [r[0] for r in rows]
    rms = np.array([r[2] for r in rows])
    peak_1x = np.array([r[3] for r in rows])
    peak_2x = np.array([r[4] for r in rows])
    peak_3x = np.array([r[5] for r in rows])
    kurt = np.array([r[6] for r in rows])
    label = np.array([r[7] or "healthy" for r in rows])

    elapsed = np.array([(t - ts[0]).total_seconds() for t in ts])

    log.info("plotting features timeline")
    fig, axes = plt.subplots(2, 2, figsize=(13, 7), sharex=True)
    ((ax_r, ax_p1), (ax_p23, ax_k)) = axes

    def _color_segments(ax, x, y, labels, title, ylabel):
        for lbl in np.unique(labels):
            mask = labels == lbl
            ax.plot(
                x[mask],
                y[mask],
                ".",
                markersize=4,
                color=_FAULT_COLORS.get(lbl, "#7f7f7f"),
                label=lbl,
            )
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.grid(alpha=0.3)

    _color_segments(ax_r, elapsed, rms, label, "RMS", "rms")
    _color_segments(ax_p1, elapsed, peak_1x, label, "peak_1x", "magnitude")
    _color_segments(ax_p23, elapsed, peak_2x, label, "peak_2x (orange) / peak_3x (gray)", "magnitude")
    for lbl in np.unique(label):
        mask = label == lbl
        ax_p23.plot(elapsed[mask], peak_3x[mask], "x", color="#888", markersize=3)
    _color_segments(ax_k, elapsed, kurt, label, "kurtosis", "kurtosis")

    ax_r.legend(loc="upper left", fontsize=8)
    for ax in (ax_p23, ax_k):
        ax.set_xlabel("seconds since demo start")
    fig.suptitle("Live demo — features ingested through MQTT -> Kafka -> TimescaleDB")
    fig.tight_layout()
    feat_path = FIG_DIR / "live_features.png"
    fig.savefig(feat_path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    log.info("wrote %s", feat_path)

    log.info("draining Kafka score / alert topics")
    scores = _drain_topic(kafka_bootstrap, "pdm.scores")
    alerts = _drain_topic(kafka_bootstrap, "pdm.alerts", timeout_s=8.0)
    log.info("scores=%d alerts=%d", len(scores), len(alerts))

    if scores:
        score_ts = [s["ts"] for s in scores]
        from datetime import datetime

        def _parse(t: str) -> datetime:
            t = t[:-1] + "+00:00" if t.endswith("Z") else t
            return datetime.fromisoformat(t)

        st0 = _parse(score_ts[0])
        elapsed_s = np.array([(_parse(t) - st0).total_seconds() for t in score_ts])
        raw = np.array([s["score"] for s in scores])
        rolling = np.array([s["rolling_mean"] for s in scores])

        fig, ax = plt.subplots(figsize=(11, 4))
        ax.plot(elapsed_s, raw, ".", markersize=3, alpha=0.5, label="per-sample score")
        ax.plot(elapsed_s, rolling, "-", linewidth=1.5, label="rolling mean (window=30)")
        ax.axhline(-0.1, color="red", linestyle="--", linewidth=1, label="alert threshold -0.1")
        for a in alerts:
            t_alert = _parse(a["ts"])
            ax.axvline(
                (t_alert - st0).total_seconds(),
                color="red",
                linewidth=1,
                alpha=0.6,
            )
        ax.set_xlabel("seconds since first score")
        ax.set_ylabel("IsolationForest score (lower = anomalous)")
        ax.set_title("Live demo — IsolationForest scores from pdm.scores topic")
        ax.legend(loc="lower left", fontsize=9)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        scores_path = FIG_DIR / "live_scores.png"
        fig.savefig(scores_path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        log.info("wrote %s", scores_path)

    summary = {
        "row_count": len(rows),
        "rows_by_fault_label": {
            lbl: int((label == lbl).sum()) for lbl in np.unique(label)
        },
        "ts_min": str(ts[0]),
        "ts_max": str(ts[-1]),
        "kafka_scores_count": len(scores),
        "kafka_alerts_count": len(alerts),
        "alerts": alerts,
    }
    (RESULTS / "live_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    log.info("wrote %s", RESULTS / "live_summary.json")


if __name__ == "__main__":
    app()
