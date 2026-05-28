# Agent Execution Guide

This document tells an AI agent (e.g., Claude, Cursor, Codex) how to
work this repository productively. Read this **before** opening any
source file.

---

## Repository contract

- Every Python module under `simulator/`, `ingest/`, `ml/`, `scripts/`
  currently raises `NotImplementedError` with a TODO block in its
  docstring. The TODO is the **work order**.
- The TODO points to a phase in `docs/roadmap.md`. Each phase has an
  **acceptance criterion** at the bottom of that phase's section.
- Concrete formulas, I/O shapes, schema, and reference benchmarks
  live in `docs/specifications.md`. The roadmap says *what* to do;
  the specifications doc says *how*.

If a TODO is ambiguous, the order of resolution is:

1. Check `docs/specifications.md` for the function-level spec.
2. Check `docs/architecture.md` for the layer-level intent.
3. Check `docs/design-decisions.md` for the "why this and not that".
4. Default to a minimal, defensible choice and record it as a new
   `## D{n}` entry in `docs/design-decisions.md`.

Never silently invent a choice that contradicts an existing doc.

---

## Working order

Implement phases in roadmap order. Each phase should be a separate
commit so the history reads as the actual development sequence.

| Phase | Branch (recommended) | Acceptance gate |
|---|---|---|
| 1.1 Signal model | `feat/vibration-signal` | `pytest tests/test_vibration.py` green |
| 1.2 Feature extractor | `feat/edge-features` | `pytest tests/test_features.py` green |
| 1.3 MQTT publisher | `feat/mqtt-publisher` | manual: `mosquitto_sub -t 'pdm/#' -v` shows messages |
| 2.x Ingestion | `feat/ingestion` | end-to-end: simulator → MQTT → Kafka → TimescaleDB row |
| 3.x ML | `feat/ml-pipeline` | offline F1 ≥ 0.85 on synthetic fault sequences |
| 4.x Demo | `feat/demo` | Grafana dashboard shows live RMS and anomaly score |

Do not work on Phase N+1 before Phase N's tests pass.

---

## Conventions

- **Python style**: PEP 8, `black` formatting, `ruff` linting,
  type-hinted public functions.
- **Tests**: pytest. New code without a test is incomplete.
- **No emoji in code or docs.**
- **Commit messages**: `<type>: <short description>` (feat / fix /
  refactor / docs / test / chore). Phase number in body.
- **Doc updates**: when you finish a phase, flip its checkboxes in
  `docs/roadmap.md` to `[x]` and add a one-line note about what
  changed since the spec.

---

## What you do NOT need to ask

The following are pre-decided and documented. Do not re-litigate:

- Python (not Java/Spring). See `design-decisions.md` D2.
- Synthetic data (not CWRU dataset). See D3.
- EMQX (not Mosquitto). See D4.
- TimescaleDB (not InfluxDB). See D5.
- IsolationForest baseline (not deep model). See D6.
- docker-compose (not k8s). See D7.

If you have a strong reason to change any of these, write a new `D{n}`
entry first; do not commit code that contradicts a current decision.

---

## Author background (for grounding tone in docs)

Wei Cheng (Wayne) Chiu — NTUST CS Master's (April 2026 graduate),
LLM / multi-agent systems background. **No production experience in
industrial IoT, Java/Spring, Kafka, or MQTT.** This is a self-study
prototype, not a re-implementation of a product.

When you write docs or comments, do not claim experience the author
does not have.
