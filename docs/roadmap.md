# Roadmap

Living document tracking what's done, what's in progress, and what's
planned. Updated as the prototype evolves.

---

## Phase 1 — Synthetic vibration simulator

### 1.1 Time-domain signal model
- [ ] Base signal: sinusoidal rotating-machine vibration at configurable
      RPM (60 Hz default), 3 axes, 25.6 kHz sampling.
- [ ] Stationary Gaussian noise floor.
- [ ] Optional fault modes:
    - [ ] Imbalance — boost amplitude at 1× rotation frequency.
    - [ ] Misalignment — peaks at 2× and 4×.
    - [ ] Outer-race bearing fault — periodic impulses at BPFO.
    - [ ] Inner-race bearing fault — modulated impulses at BPFI.

### 1.2 Edge feature extractor
- [ ] Time-domain: RMS, peak-to-peak, crest factor, kurtosis.
- [ ] Frequency-domain: FFT spectrum, peaks at 1×/2×/3× harmonic
      multiples, envelope spectrum for bearing-fault detection.
- [ ] Output one 8-dim feature vector per second.

### 1.3 MQTT publisher
- [ ] paho-mqtt client publishing JSON-encoded features.
- [ ] Topic: ``pdm/{plant_id}/{device_id}``, QoS 1.
- [ ] Configurable fault-mode injection schedule (e.g., healthy for
      first 60 s, then imbalance at 50% severity).

---

## Phase 2 — Ingestion pipeline

### 2.1 Infrastructure (docker-compose)
- [ ] EMQX 5.x broker.
- [ ] Apache Kafka (single-broker dev mode) + KRaft (no ZooKeeper).
- [ ] TimescaleDB 2.x with PostgreSQL 16 base image.
- [ ] Grafana 10.x with TimescaleDB data source pre-provisioned.

### 2.2 MQTT → Kafka bridge
- [ ] Standalone Python service consuming all ``pdm/#`` topics.
- [ ] Republishes to Kafka topic ``pdm.features`` with key = device_id
      (preserves per-device ordering).
- [ ] Backpressure handling: respect Kafka producer's send buffer; drop
      with a warning rather than blocking the MQTT client.

### 2.3 Kafka → TimescaleDB consumer
- [ ] Batch insertion (every 100 messages or 1 second, whichever first).
- [ ] Hypertable on ``device_features(device_id TEXT, ts TIMESTAMPTZ,
      rms FLOAT, kurtosis FLOAT, peak_1x FLOAT, peak_2x FLOAT, …)``.
- [ ] Index on ``(device_id, ts DESC)``.
- [ ] Continuous aggregate: 1-minute mean per device.

---

## Phase 3 — PdM model

### 3.1 Offline training
- [ ] Generate a "training week" of healthy data from the simulator.
- [ ] Compute features, fit IsolationForest on the healthy distribution.
- [ ] Persist the model (joblib) and the feature scaler.

### 3.2 Online inference
- [ ] Consumer process that reads from ``pdm.features``, applies the
      saved model, and writes anomaly scores back to a separate Kafka
      topic ``pdm.scores``.
- [ ] Alert when rolling 5-min mean score exceeds threshold.

### 3.3 Evaluation
- [ ] Generate held-out sequences with known fault injections.
- [ ] Compute precision / recall / F1 at multiple thresholds.
- [ ] Plot ROC curve to ``results/anomaly_roc.png``.

---

## Phase 4 — End-to-end demo

### 4.1 Grafana dashboard
- [ ] Per-device RMS over time.
- [ ] Per-device anomaly score over time.
- [ ] Active alerts panel.

### 4.2 Demo script
- [ ] `scripts/demo.sh` — bring up infra, start simulator with scripted
      fault injection, open Grafana to the dashboard.

### 4.3 Screen capture / GIF
- [ ] Record a 30-second screencast of healthy → fault transition and
      the anomaly alert triggering.

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

*Last updated on initialization. To be revised as phases complete.*
