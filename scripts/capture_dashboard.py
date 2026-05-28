"""Orchestrate a live demo and capture Grafana dashboard PNGs at fault
transitions using the grafana-image-renderer plugin.

Output:
    results/figures/grafana_t{30,90,180,240}.png
    results/figures/grafana_final.png   (whole-demo timeline)
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import requests
import typer

log = logging.getLogger("dashboard")
app = typer.Typer(add_completion=False, no_args_is_help=False)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIGS = REPO_ROOT / "results" / "figures"
FIGS.mkdir(parents=True, exist_ok=True)

DASHBOARD_URL = (
    "http://localhost:3000/render/d/pdm-overview/iot-pdm-e28094-live-pipeline"
)
AUTH = ("admin", "pdm")


def _capture(name: str, params: dict) -> Path:
    out = FIGS / name
    r = requests.get(DASHBOARD_URL, auth=AUTH, params=params, timeout=30)
    r.raise_for_status()
    out.write_bytes(r.content)
    log.info("captured %s (%d bytes, %dx%d viewport)",
             out, len(r.content), params.get("width"), params.get("height"))
    return out


@app.command()
def main(
    duration_s: float = typer.Option(240.0),
    capture_times: str = typer.Option("30,90,180,235",
        help="Comma-separated seconds-from-start at which to snapshot"),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    # Clear stale demo rows so dashboard's "last 10m" panel is clean
    import psycopg
    with psycopg.connect("postgresql://pdm:pdm@localhost:5432/pdm") as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM device_features WHERE device_id IN ('d001', 'd002')")
        conn.commit()

    env = {"PYTHONUNBUFFERED": "1", **os.environ}
    log.info("starting demo (duration=%.0fs)", duration_s)
    demo = subprocess.Popen(
        [sys.executable, "-m", "scripts.demo_end_to_end",
         "--duration-s", str(duration_s)],
        cwd=REPO_ROOT,
        stdout=(REPO_ROOT / "results" / "demo-logs" / "demo_capture.log").open("w"),
        stderr=subprocess.STDOUT,
        env=env,
    )

    start = time.monotonic()
    capture_at = [float(s) for s in capture_times.split(",")]
    for t in sorted(capture_at):
        wait = t - (time.monotonic() - start)
        if wait > 0:
            time.sleep(wait)
        elapsed = int(time.monotonic() - start)
        log.info("t+%ds: capturing dashboard", elapsed)
        try:
            _capture(
                f"grafana_t{int(t):03d}.png",
                {"width": 1600, "height": 900, "from": "now-10m", "to": "now", "kiosk": "tv"},
            )
        except requests.HTTPError as e:
            log.error("capture failed: %s", e)

    # Wait for demo to finish
    rem = duration_s + 10 - (time.monotonic() - start)
    if rem > 0:
        log.info("waiting %.0fs for demo to finish", rem)
        try:
            demo.wait(timeout=rem)
        except subprocess.TimeoutExpired:
            demo.terminate()
            demo.wait()
    else:
        demo.wait()

    # Final whole-timeline shot
    log.info("final whole-timeline capture")
    try:
        _capture(
            "grafana_final.png",
            {"width": 1600, "height": 900, "from": "now-10m", "to": "now", "kiosk": "tv"},
        )
    except requests.HTTPError as e:
        log.error("final capture failed: %s", e)

    print("dashboard captures saved under", FIGS)


if __name__ == "__main__":
    app()
