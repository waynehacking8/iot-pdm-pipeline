# Design Decisions

Non-obvious choices made while scoping this prototype, with the
reasoning behind each. Each entry is intended to be defensible under
"why this and not that" scrutiny.

---

## D1. Why predictive maintenance, not a generic IoT platform?

**Decision:** Build a vertical PdM pipeline (sensor → broker → store →
ML → dashboard) rather than a generic multi-tenant IoT control plane.

**Why:** A vertical demonstrates the full data lifecycle in one
artifact. A generic platform would be a half-built device-registry +
auth service, which is mostly plumbing and shows nothing about
domain reasoning. PdM hits all the interesting layers — edge
processing, pub/sub semantics, time-series storage, ML inference,
operator visualization — in one coherent story.

**What's lost:** the prototype doesn't demonstrate device-onboarding,
multi-tenancy, or remote configuration. These are mentioned in
`architecture.md` as deliberate omissions.

---

## D2. Why Python end-to-end, not Java/Spring?

**Decision:** Every component is Python (paho-mqtt, confluent-kafka,
psycopg, scikit-learn).

**Why:** I write Python and TypeScript fluently and have no production
Java/Spring experience. A Java/Spring port of the pipeline would
demonstrate framework familiarity, not architectural reasoning, and
would take longer than the prototype's scope warrants. The
architecture itself (MQTT topology, Kafka partitioning, hypertable
chunking) is language-agnostic.

**What's lost:** signals about JVM-stack proficiency are not in this
artifact. A reviewer who needs that signal would need to look at
other work.

---

## D3. Why synthetic data, not a public PdM dataset?

**Decision:** A simulator generates vibration signals with injectable
fault modes (imbalance, misalignment, bearing wear) rather than
loading the CWRU bearing dataset or PRONOSTIA.

**Why:** The simulator is **part of the artifact** — it forces explicit
modeling of what "healthy" vs "faulty" looks like, which is the
domain-knowledge signal a reviewer cares about. A dataset loader is
forgettable; a fault-mode injector is a discussion piece.

Additionally: synthetic data has perfect ground truth, which makes
the anomaly-detection evaluation unambiguous (precision/recall at
every fault threshold).

**What's lost:** the model isn't benchmarked on real data, so its
real-world performance is unknown. This is explicitly stated in the
README.

---

## D4. Why EMQX, not Mosquitto?

**Decision:** EMQX as the MQTT broker.

**Why:** EMQX ships an MQTT-to-Kafka bridge as a configuration option,
saving an integration step. It also handles higher fan-in if the
demo is ever extended to many simulated devices.

**Why not Mosquitto:** Mosquitto is the lightest, most-deployed
broker, but lacks built-in Kafka bridging. The bridge would have to
be a separate Python service, which is fine but adds a moving part.

---

## D5. Why TimescaleDB, not InfluxDB?

**Decision:** TimescaleDB as the time-series store.

**Why:**
- **SQL compatibility** — joins, window functions, and ecosystem
  drivers all work without learning a new query language.
- **Grafana integration** — the PostgreSQL data source is
  zero-friction; Grafana already speaks SQL.
- **Operational familiarity** — PostgreSQL is the database I know
  best. Lower cognitive load while building means more time spent on
  the actual pipeline logic.

**Why not InfluxDB:** higher raw write throughput, smaller ecosystem.
For this prototype's scale (~1 message/device/sec, < 100 devices),
write throughput is not the bottleneck. At hyperscale it would
matter.

---

## D6. Why Isolation Forest for anomaly detection?

**Decision:** scikit-learn's `IsolationForest` as the baseline anomaly
detector. Optional upgrades (LSTM autoencoder, one-class SVM, GMM
likelihood) are listed in the roadmap.

**Why:**
- **No labels required** — Isolation Forest is unsupervised, trained
  on healthy-state features alone.
- **Interpretable** — `decision_function` gives a calibrated anomaly
  score per sample, and feature importances are derivable via
  permutation tests.
- **Trivial to train** — ~5 seconds on the synthetic dataset; fast
  iteration loop during prototype development.

**Why not deep learning:** The data dimensionality is low (~8
features), the volume is modest, and interpretability matters. Boring
ML wins here. Deep models go on the roadmap as a stretch goal once
the baseline is solid.

---

## D7. Why a docker-compose stack, not Kubernetes?

**Decision:** All infrastructure components (EMQX, Kafka, TimescaleDB,
Grafana) run as a single `docker compose up`.

**Why:** A reviewer running this on a laptop should not have to
provision a cluster. docker-compose is the right level of abstraction
for "demo this locally". Kubernetes manifests would communicate more
sophistication but at the cost of a 30-minute setup detour.

**What's planned:** k8s manifests as a stretch goal in
`docs/roadmap.md`. Demonstrating "I could deploy this if I needed to"
is reasonable; making it the default barrier-to-entry is not.

---

## D8. Why bridge MQTT to Kafka instead of writing to Kafka directly?

**Decision:** Devices publish to MQTT. A bridge process forwards to
Kafka.

**Why:** Devices are constrained. Kafka clients are heavy (JVM-style
heaps for the Java client, considerable memory for librdkafka). MQTT
clients are minimal (paho-mqtt is ~200KB compiled). The bridge
centralizes the heavy lifting on the server side where memory is
cheap.

**Industry validation:** Every industrial IoT reference architecture
(AWS IoT, Azure IoT, EMQX docs, NVIDIA's IoT examples) shows this
exact pattern. The bridge step is not an artifact of this prototype;
it's the standard.
