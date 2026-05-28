# IoT PdM Pipeline

> An end-to-end **predictive-maintenance pipeline** prototype for
> industrial IoT: synthetic vibration sensor → MQTT broker → Kafka →
> time-series database → ML anomaly detector → Grafana dashboard.

Built as a self-study exercise to understand the architecture
patterns behind industrial IoT platforms (DataHub Gateway, edgeMES,
DIALink-class systems). The repo prioritizes **architectural clarity
and end-to-end runnable demos** over scale or production hardening.

---

## What this is

- A synthetic **vibration sensor simulator** producing realistic
  acceleration time series with injectable fault modes (imbalance,
  misalignment, bearing wear).
- An **edge feature extractor** that converts raw 25.6 kHz waveforms
  into compact PdM features (RMS, kurtosis, 1×/2×/3× harmonics) before
  uploading.
- A **publish/subscribe ingestion pipeline**: MQTT broker → Kafka topic
  → TimescaleDB hypertable.
- A **PdM machine-learning module** for offline training of an anomaly
  detector and online inference.
- A **docker-compose stack** that brings up EMQX, Kafka, TimescaleDB,
  and Grafana on a laptop in one command.

## What this is NOT

- **Not benchmarked on real factory data.** All signals are synthetic.
- **Not a Java/Spring service.** Python end-to-end. The architectural
  patterns are language-agnostic; this repo demonstrates them in the
  language the author writes best.
- **Not production-ready.** No authentication, no TLS, no horizontal
  scaling, no high-availability story. The point is to show the moving
  parts work together, not to ship to a customer.
- **Not connected to real PLCs or OPC UA devices.** Modbus/OPC UA
  adapters are out of scope for this prototype.

---

## Architecture

```
[ Simulated Vibration Sensor (3-axis, 25.6 kHz) ]
                      |
                      v  (FFT + summary features on the "edge")
[ Edge Feature Extractor (~50 bytes / second) ]
                      |
                      v  (MQTT QoS 1, topic: pdm/{plant}/{device})
[ MQTT Broker (EMQX) ]
                      |
                      v  (MQTT → Kafka bridge; same payload, durable storage)
[ Kafka topic: pdm.features ]
                      |
                      v  (Kafka consumer)
[ TimescaleDB Hypertable (device_id, ts) ]
                      |
                      |---------------> [ Grafana Dashboard ]
                      |
                      v  (batch + online inference)
[ PdM Anomaly Detector ] -> alerts -> stdout / file sink
```

See [`docs/architecture.md`](docs/architecture.md) for the rationale
behind each layer's choice.

---

## Project layout

```
iot-pdm-pipeline/
├── simulator/          # Phase 1: synthetic sensor data generator
│   ├── vibration.py    # Time-domain signal with optional fault modes
│   └── publisher.py    # MQTT client wrapping the simulator
├── ingest/             # Phase 2: bridge + storage
│   ├── bridge.py       # MQTT subscriber → Kafka producer
│   └── consumer.py     # Kafka consumer → TimescaleDB writer
├── ml/                 # Phase 3: predictive maintenance model
│   ├── features.py     # Time-domain & frequency-domain feature extractors
│   ├── train.py        # Offline training of anomaly detector
│   └── inference.py    # Online scoring against the live stream
├── infra/              # docker-compose for EMQX, Kafka, TimescaleDB, Grafana
│   └── docker-compose.yml
├── scripts/            # End-to-end demo entry points
└── docs/
    ├── architecture.md
    ├── design-decisions.md     # D1–D11 (D9–D11 added during impl)
    ├── specifications.md       # function-level contracts
    ├── roadmap.md
    └── references.md
```

After running `scripts/run_experiments.py` and
`scripts/demo_end_to_end.py`, additional artifacts appear:

```
results/
├── REPORT.md                   # auto-generated experiment + demo report
├── evaluation.json             # offline ROC / F1 / latency numbers
├── live_summary.json           # row counts, alert log from the live demo
├── demo-logs/                  # per-subprocess logs from the demo
└── figures/                    # waveforms, distributions, ROC, timelines
ml/artifacts/                   # scaler.joblib, model.joblib, training_summary.json
```

---

## Quick start

```bash
# 1. Bring up infrastructure (EMQX 1883, Kafka 9094, TimescaleDB 5432, Grafana 3000)
cd infra && docker compose up -d && cd ..

# 2. Install Python deps + test runner
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt pytest

# 3. Run the offline experiments (trains model, produces figures + report)
python -m scripts.run_experiments --train-samples 6000 --eval-per-mode 400

# 4. Create Kafka topics
python - <<'PY'
from confluent_kafka.admin import AdminClient, NewTopic
a = AdminClient({"bootstrap.servers": "localhost:9094"})
for f in a.create_topics([
    NewTopic("pdm.features", num_partitions=3, replication_factor=1),
    NewTopic("pdm.scores",   num_partitions=3, replication_factor=1),
    NewTopic("pdm.alerts",   num_partitions=1, replication_factor=1),
]).values():
    try: f.result(timeout=10)
    except Exception: pass
PY

# 5. Run the live end-to-end demo (4 minutes: healthy -> imbalance -> outer_race)
python -m scripts.demo_end_to_end --duration-s 240

# 6. Re-render live demo figures
python -m scripts.plot_live_demo

# 7. Open Grafana at http://localhost:3000 (admin / pdm) for the live feature stream
```

All figures land in `results/figures/` and the auto-generated report
in `results/REPORT.md`.

---

## Roadmap

See [`docs/roadmap.md`](docs/roadmap.md) for the full plan. Headline
status:

| Phase | Module | Status |
|---|---|---|
| 1 | Vibration simulator + MQTT publisher | done |
| 2 | MQTT → Kafka → TimescaleDB ingestion | done |
| 3 | PdM features + offline anomaly model | done — AUROC=1.0, F1=0.957, latency 26–28 s |
| 4 | End-to-end demo + Grafana dashboard | done (live demo + plots in `results/`) |
| 5 | Stretch: shadow-mode model rollout, OTA simulation | future |

---

## References

See [`docs/references.md`](docs/references.md). Core background:

- ISA-95 / IPC-CFX / OPC UA — industrial communication standards.
- MQTT 5.0 specification — pub/sub semantics, QoS, LWT.
- TimescaleDB time-series optimizations.
- Rolling-element bearing fault feature literature (RMS, kurtosis,
  envelope spectrum).

---

## Author

Wei Cheng (Wayne) Chiu · [GitHub](https://github.com/waynehacking8) ·
M.S. Computer Science, NTUST (April 2026).
