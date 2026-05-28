"""End-to-end demo orchestrator.

Brings up bridge -> consumer -> inference -> publisher (with a scripted
healthy -> imbalance -> outer_race fault timeline) as subprocesses,
then waits ``duration_s`` seconds before tearing down.

Assumes docker compose stack is already running. Run
``infra/docker compose up -d`` first.
"""

from __future__ import annotations

import json
import logging
import signal as os_signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import typer

log = logging.getLogger("demo")

app = typer.Typer(add_completion=False, no_args_is_help=False)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEDULE = [
    {"after_s": 0, "fault_mode": "healthy", "severity": 0.0},
    {"after_s": 60, "fault_mode": "imbalance", "severity": 1.0},
    {"after_s": 120, "fault_mode": "outer_race", "severity": 1.0},
    {"after_s": 180, "fault_mode": "healthy", "severity": 0.0},
]


def _start(name: str, args: list[str], log_dir: Path) -> subprocess.Popen:
    log_path = log_dir / f"{name}.log"
    log.info("start %s -> %s", name, log_path)
    fh = log_path.open("w")
    return subprocess.Popen(
        args,
        cwd=REPO_ROOT,
        stdout=fh,
        stderr=subprocess.STDOUT,
        env={"PYTHONUNBUFFERED": "1", **__import__("os").environ},
    )


@app.command()
def main(
    duration_s: float = typer.Option(240.0, help="Total demo runtime"),
    device: str = typer.Option("d001"),
    plant: str = typer.Option("p001"),
    rate: float = typer.Option(1.0, help="Publisher rate (Hz)"),
    log_dir: Path = typer.Option(REPO_ROOT / "results" / "demo-logs"),
    schedule_path: Optional[Path] = typer.Option(None),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log_dir.mkdir(parents=True, exist_ok=True)

    if schedule_path is None:
        schedule_path = log_dir / "schedule.json"
        schedule_path.write_text(json.dumps(DEFAULT_SCHEDULE, indent=2))
    log.info("schedule -> %s", schedule_path)

    py = sys.executable
    procs: list[tuple[str, subprocess.Popen]] = []

    try:
        procs.append(
            ("bridge", _start("bridge", [py, "-m", "ingest.bridge"], log_dir))
        )
        procs.append(
            ("consumer", _start("consumer", [py, "-m", "ingest.consumer"], log_dir))
        )
        procs.append(
            ("inference", _start("inference", [py, "-m", "ml.inference"], log_dir))
        )
        # let consumers register before producer starts
        time.sleep(3.0)
        procs.append(
            (
                "publisher",
                _start(
                    "publisher",
                    [
                        py,
                        "-m",
                        "simulator.publisher",
                        "--device",
                        device,
                        "--plant",
                        plant,
                        "--rate",
                        str(rate),
                        "--schedule",
                        str(schedule_path),
                        "--duration-s",
                        str(duration_s),
                    ],
                    log_dir,
                ),
            )
        )

        log.info("demo running for %.0fs", duration_s)
        log.info("Grafana: http://localhost:3000 (admin / pdm)")
        log.info("EMQX dashboard: http://localhost:18083 (admin / public)")

        stop = {"flag": False}

        def _handle_sig(*_args) -> None:
            stop["flag"] = True

        os_signal.signal(os_signal.SIGINT, _handle_sig)
        os_signal.signal(os_signal.SIGTERM, _handle_sig)

        end = time.monotonic() + duration_s + 10
        while time.monotonic() < end and not stop["flag"]:
            time.sleep(1.0)
            for name, proc in procs:
                if proc.poll() is not None and name != "publisher":
                    log.error("%s exited prematurely rc=%s — see %s/%s.log",
                              name, proc.returncode, log_dir, name)
                    stop["flag"] = True
                    break
    finally:
        for name, proc in reversed(procs):
            if proc.poll() is None:
                log.info("stopping %s", name)
                proc.send_signal(os_signal.SIGTERM)
        deadline = time.monotonic() + 8
        for name, proc in reversed(procs):
            timeout = max(0.5, deadline - time.monotonic())
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                log.warning("killing %s", name)
                proc.kill()
        log.info("demo done. Logs: %s", log_dir)


if __name__ == "__main__":
    app()
