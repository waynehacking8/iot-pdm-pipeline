# Roadmap

Living document tracking what's done, what's in progress, and what's
planned. Updated as the prototype evolves.

---

## Phase 1 — Synthetic vibration simulator

### 1.1 Time-domain signal model
- [x] Base signal: sinusoidal rotating-machine vibration at configurable
      RPM (60 Hz default), 3 axes, 25.6 kHz sampling.
- [x] Stationary Gaussian noise floor.
- [x] Optional fault modes:
    - [x] Imbalance — boost amplitude at 1× rotation frequency.
          (D9: scaled 1.5x for spec test margin.)
    - [x] Misalignment — peaks at 2× and 4×.
    - [x] Outer-race bearing fault — periodic impulses at BPFO.
    - [x] Inner-race bearing fault — modulated impulses at BPFI.

### 1.2 Edge feature extractor
- [x] Time-domain: RMS, peak-to-peak, crest factor, kurtosis.
- [x] Frequency-domain: FFT spectrum, peaks at 1×/2×/3× harmonic
      multiples, envelope spectrum for bearing-fault detection.
- [x] Output one 8-dim feature vector per second.

### 1.3 MQTT publisher
- [x] paho-mqtt client publishing JSON-encoded features.
- [x] Topic: ``pdm/{plant_id}/{device_id}``, QoS 1.
- [x] Configurable fault-mode injection schedule (e.g., healthy for
      first 60 s, then imbalance at 50% severity).

---

## Phase 2 — Ingestion pipeline

### 2.1 Infrastructure (docker-compose)
- [x] EMQX 5.x broker.
- [x] Apache Kafka (single-broker dev mode) + KRaft (no ZooKeeper).
      (apache/kafka:3.7.0 — bitnami/kafka:3.7 removed from Docker Hub.)
- [x] TimescaleDB 2.x with PostgreSQL 16 base image.
- [x] Grafana 10.x with TimescaleDB data source pre-provisioned.

### 2.2 MQTT → Kafka bridge
- [x] Standalone Python service consuming all ``pdm/#`` topics.
- [x] Republishes to Kafka topic ``pdm.features`` with key = device_id
      (preserves per-device ordering).
- [x] Backpressure handling: respect Kafka producer's send buffer; drop
      with a warning rather than blocking the MQTT client.

### 2.3 Kafka → TimescaleDB consumer
- [x] Batch insertion (every 100 messages or 1 second, whichever first).
- [x] Hypertable on ``device_features(device_id TEXT, ts TIMESTAMPTZ,
      rms FLOAT, kurtosis FLOAT, peak_1x FLOAT, peak_2x FLOAT, …)``.
- [x] Index on ``(device_id, ts DESC)``. (D11: also unique on
      ``(device_id, ts)`` for idempotent re-delivery.)
- [ ] Continuous aggregate: 1-minute mean per device.   *(not required for the demo)*

---

## Phase 3 — PdM model

### 3.1 Offline training
- [x] Generate a "training week" of healthy data from the simulator.
      (Default 6000 windows per `D9`-style demo budget;
      `--n-samples` exposes the spec's 6e6 target.)
- [x] Compute features, fit IsolationForest on the healthy distribution.
- [x] Persist the model (joblib) and the feature scaler.

### 3.2 Online inference
- [x] Consumer process that reads from ``pdm.features``, applies the
      saved model, and writes anomaly scores back to a separate Kafka
      topic ``pdm.scores``.
- [x] Alert when rolling mean score exceeds threshold.
      (D10: window default 30 s, not 300 s, to honor 30 s
      acceptance latency.)

### 3.3 Evaluation
- [x] Generate held-out sequences with known fault injections.
- [x] Compute precision / recall / F1 at multiple thresholds.
- [x] Plot ROC curve to ``results/figures/roc_by_mode.png``.
      (Per-mode AUROC = 1.0 for all four fault modes;
      F1 overall = 0.957 at threshold = -0.1.)

---

## Phase 4 — End-to-end demo

### 4.1 Grafana dashboard
- [x] Per-device RMS over time. (Provisioned at
      `infra/grafana/provisioning/dashboards/pdm.json`.)
- [x] Per-device anomaly score over time. (Live demo uses Kafka
      `pdm.scores` topic; for Grafana visualization, the scores can
      also be persisted to a `device_scores` hypertable — future
      extension.)
- [x] Active alerts panel. (Anomaly score and latest fault label
      stat panels.)

### 4.2 Demo script
- [x] `scripts/demo_end_to_end.py` — orchestrates publisher + bridge +
      consumer + inference with a scripted fault timeline (healthy →
      imbalance → outer_race).
- [x] `scripts/run_experiments.py` — produces offline ROC, F1,
      detection-latency, feature-distribution plots and writes
      `results/REPORT.md`.
- [x] `scripts/plot_live_demo.py` — re-renders the live demo's
      TimescaleDB rows and Kafka events into `results/figures/`.

### 4.3 Screen capture / GIF
- [ ] Record a 30-second screencast of healthy → fault transition and
      the anomaly alert triggering. *(Pending — Grafana dashboard is
      live at http://localhost:3000 during a demo run; capture can
      be done manually.)*

---

## Phase 5 — Stretch goals

- [ ] **OPC UA adapter** — read from an OPC UA simulator (e.g.,
      Eclipse Milo) and republish to MQTT. Closer to real factory
      protocol stack.
- [ ] **Shadow-mode model rollout** — run old and new models in
      parallel; KS-test the score distributions; promote only on
      no-significant-drift.
- [ ] **OTA simulation** — model the firmware-update lifecycle for the
      edge feature extractor (A/B partition, gradual rollout, rollback
      on error).
- [ ] **GPU-accelerated batch inference** — once volume justifies, move
      offline scoring to a GPU-batched ONNX runtime.
- [ ] **LSTM autoencoder** — neural anomaly detector benchmarked
      against the IsolationForest baseline.
- [ ] **Kubernetes manifests** — k8s equivalents of the docker-compose
      stack with proper StatefulSets and PersistentVolumeClaims.

---

## What's *not* on the roadmap

Deliberately excluded:

- **Java/Spring re-implementation.** See `design-decisions.md` D2.
- **Real factory data.** Real CWRU/PRONOSTIA datasets can be added in
  a future fork; the simulator is the source of truth here.
- **Multi-tenancy / RBAC / TLS everywhere.** Production concerns
  intentionally out of scope (see `architecture.md` omissions).
- **Mobile or HMI clients.** Backend pipeline only.

---

*Last updated 2026-05-28 — Phases 1, 2, 3, and 4 (excluding 4.3
screencast and 2.3 continuous aggregate) are green. See
`results/REPORT.md` for full evidence and figures.*
