# Field Evolution: Industrial IoT Backend, 1999–2026

> Why this file exists: an MQTT-Kafka-TimescaleDB-Grafana prototype is
> easy to read as "yet another IIoT demo". This document re-frames the
> same work inside the mental models and production-pattern debates
> that resident senior IIoT architects actually argue over — so a
> reviewer can see what the prototype is *signalling* about, not just
> what it does.

---

## 1. The 25-year arc, in one sentence

> MQTT (1999) and OPC UA (2007) supplied the wire protocols; Kafka
> (2011) and InfluxDB / TimescaleDB (2013) supplied the storage
> backbone; AWS IoT and Azure IoT (2015–2016) productized the
> cloud-first pattern, which GE Predix's 2018 failure forced into
> hybrid edge-cloud architectures (AWS Greengrass, Azure IoT Edge,
> Siemens Industrial Edge, KubeEdge, 2019–2022); since 2024, LLM-as-
> interface (Siemens Industrial Copilot) is the visible surface change,
> but the unsettled questions — high-cardinality time series, edge-
> autonomous OTA, alarm storms, hybrid configuration drift — are still
> the same hard problems they were in 2015.

---

## 2. Five core mental models — the world view behind the architecture

These five frame every architectural decision in `simulator/`,
`ingest/`, `ml/`, and `infra/`. Reading them before the code makes the
choices obvious.

### M1. Time is IIoT's first-class citizen, not a column

A relational engineer sees `timestamp` as one column among many. A
senior IIoT engineer sees time as the **partition axis, the index
axis, the retention axis, and the downsampling axis**. Once time
becomes the schema's center, cardinality, hot shards, out-of-order
ingestion, and watermarks all become permanent background concerns
rather than "we'll fix it later" problems.

This prototype's choice of **TimescaleDB hypertable** is a direct
instance: the chunk dimension is time, not device.

### M2. Edge is not a small cloud — it is a different species

The cloud engineer sees an edge box as "the same software, fewer
resources". The IIoT engineer knows edge means **stay correct when
disconnected, expect upgrades to fail, expect clocks to jump, accept
that hardware ages**. The acceptance test for edge code is "what is
it doing one week after the network was unplugged", not "what is
throughput at idle".

The pipeline's **edge feature extractor** (RMS, kurtosis, harmonics
computed before upload) is an instance: ~50 bytes per second
survives long disconnections; raw 25.6 kHz streams do not.

### M3. Devices are not clients — they are state machines with a
life cycle

A web request is stateless and short-lived. A device is born,
provisioned, deployed, periodically updated, sometimes broken,
eventually decommissioned. **Desired state and actual state are
never exactly equal**, and the backend's job is not to assume they
match — it is to drive them closer together.

MQTT's last-will, Azure IoT Hub's device twin, Kubernetes'
reconciliation loop are all instances of the same pattern, applied to
different layers.

### M4. Data value density decays exponentially with time — compliance
value does not

A vibration sample is:
- a **control signal** in the first 100 ms,
- an **anomaly-detection input** within an hour,
- **PdM training data** within a day,
- a **compliance / audit artifact** a year later.

The same byte serves four readers with four different query patterns
and four different SLOs. Hot / warm / cold tiering, downsampling
policies, CDC to a lakehouse — these are not optimizations; they are
the only honest answer to a value curve that drops over time while
the audit obligation does not.

### M5. Alarms are not events — they are a signal-processing problem

Treating alarms as a log produces alarm storms. Treating alarms as a
**signal** produces fingerprint dedup, hysteresis, correlation
windows, root-cause topology, and suppression hierarchies. When
100,000 devices drop simultaneously, the correct answer is not
"send 100,000 notifications"; it is "identify the one broken fiber
upstream".

This is the design intent behind the alarm-storm-suppression module
in the roadmap: a three-layer architecture (fingerprint dedup,
topology-aware correlation, flapping detection) backed by expiring
LRU + DAG + token bucket data structures.

---

## 3. Three live disagreements

### D1. MQTT broker-centric versus Kafka log-centric backbone

- **MQTT camp** (HiveMQ, EMQX, AWS IoT Core): MQTT was built for
  devices — low bandwidth, QoS semantics, last-will, retained
  messages. Kafka clients do not run on MCUs.
- **Kafka camp** (Confluent, LinkedIn lineage): the log is the source
  of truth — replay, stream processing, exactly-once, schema
  registry are the industrial-grade primitives. MQTT keeps message
  semantics, not history.
- **Where the industry is**: layered — **MQTT at the edge ingress,
  Kafka on the cloud backbone**, with a bridge in between. The bridge
  is now the new single point of failure; QoS / ordering / retention
  semantics at the boundary remain underspecified in practice, and
  end-to-end exactly-once is more aspiration than guarantee.

### D2. Edge-first versus cloud-first responsibility

- **Edge-first** (Siemens Industrial Edge, AWS Greengrass, KubeEdge):
  latency, bandwidth, sovereignty, and disconnection survival require
  the logic to live near the device. PdM inference and control
  loops belong on the edge.
- **Cloud-first** (early Azure IoT Hub, PTC ThingWorx): only the
  cloud can unify model versions, observability, and fleet operations
  at scale.
- **Where the industry is**: hybrid — control loops on the edge,
  training and fleet orchestration in the cloud (a post-Predix
  consensus). The unsolved problem is **configuration drift**: 100k
  edges running slightly different combinations of model, runtime,
  and OS, with no clean way to reproduce a 0.3% failure.

### D3. High-cardinality time-series: wide tag tables versus narrow
relational versus columnar lakehouse

- **InfluxDB camp**: tag-indexed wide tables are fastest for
  device-centric queries.
- **TimescaleDB camp**: PostgreSQL compatibility, JOINs, and the SQL
  ecosystem are what enterprises actually need.
- **Lakehouse camp** (Databricks, Iceberg, Delta): time series is
  ultimately an analytical asset; keep hot data in OLTP, push cold
  to a lakehouse and query with Trino / Spark.
- **Where the industry is**: tiered — hot / warm / cold — but every
  organization assembles their own tier mapping. **Cardinality
  explosion remains unsolved cleanly** across all three: InfluxDB
  TSI blows out RAM; Timescale's hypertable chunk count blows out the
  planner; Iceberg's small-files problem blows out metadata.

---

## 4. Where this prototype sits

This pipeline implements the **canonical industrial backbone** at
laptop scale:

- `simulator/` produces realistic 3-axis vibration with injectable
  fault modes.
- `ingest/` is the MQTT → Kafka → TimescaleDB chain that mirrors
  the production AWS-IoT-style architecture.
- `ml/` does the offline-train / online-score pattern that production
  PdM uses.
- `infra/docker-compose.yml` brings the whole stack up in one command.

This is **not** a Predix / MindSphere / DataHub reproduction. It is
the **unit test** for the patterns those platforms are made of:

- The **MQTT QoS handling** in `ingest/bridge.py` is the same
  protocol-level reasoning that a senior architect uses to refute
  "QoS 2 means exactly-once" (it doesn't; application-level
  idempotency is still required).
- The **partition-key choice** in the Kafka producer is the same
  reasoning that splits hot devices into sub-partitions in
  production.
- The **timestamp-as-partition-key** in TimescaleDB is the same
  schema discipline that prevents cardinality explosion in
  production.

The prototype's purpose is to make those choices visible and
defensible in interview, not to ship to a customer.

---

## 5. Has this field had its "GPT moment"?

> My answer: no, and probably not within the next 3–5 years.

**Why not**:
1. **No scale → emergence axis.** IIoT progress is engineering
   refinement, not capability emergence.
2. **No transformer-equivalent substrate.** MQTT (1999), Kafka
   (2011), InfluxDB (2013), the entire stack is engineering
   evolution.
3. **No public-facing capability shift.** AWS IoT, Azure IoT,
   Siemens MindSphere do not have a ChatGPT equivalent.
4. **The data is private.** Industrial telemetry is each factory's
   crown jewel and bound by compliance rules. There is no Common
   Crawl for industrial data; even when Siemens / Schneider / NVIDIA
   try to assemble industrial foundation models, the scaling-law data
   axis is structurally capped.

**Four candidate paths, ranked by likelihood**:

| Path | Description | Likelihood |
|------|-------------|------------|
| A. Vertical foundation models | One sensor foundation model per device class (motor, CNC, HVAC); few-shot anomaly detection at GPT-3 level **inside** a vertical but no cross-vertical transfer. Tesla on batteries, GE on turbines, etc. | Most likely |
| B. LLM as natural-language interface | "Why was line 3 slow at 8 am?" translated by an LLM into InfluxDB / SQL / alarm-topology queries. Siemens Industrial Copilot is already on this path. **Interface revolution, not backend revolution.** | Already happening |
| C. Federated learning + homomorphic encryption | Cross-vendor learning without sharing raw data. Technically feasible, commercially blocked (whoever shares first loses). May require regulatory pressure (EU Data Act). | Long-term |
| D. Physics-AI / world models | NVIDIA Cosmos / DeepMind world models mature enough to drive *simulation-based prediction* rather than data-driven detection. The "Sora moment" of IIoT. | Highest emergence potential, longest timeline |

**Interview takeaway**: do not claim "LLMs are about to disrupt IIoT".
Senior architects will mark you down. Say instead: "LLMs are a phase
change at the interface layer; the model layer remains vertical-
specific; the backend layer (time series, edge-cloud, alarms) is
unchanged in its fundamental problems for the foreseeable future."

---

## 6. How this maps to interview talking points

If a reviewer asks "what does this prototype demonstrate":

1. **Protocol literacy.** MQTT QoS, Kafka ordering, partition keys —
   the right answer to "QoS 2 = exactly-once?" is "no, only
   broker-to-client".
2. **Pattern literacy.** Edge-autonomous OTA, alarm-storm
   suppression, CDC outbox, desired-versus-actual reconciliation —
   patterns that look obvious in retrospect and that burn teams
   that haven't internalized them.
3. **Cardinality discipline.** Tag versus field, partition strategy,
   tier mapping — the discipline that decides whether the system
   survives its second year.

If a reviewer asks "why not real factory data":

- Real factory data is unavailable for licensing reasons. A
  faithfully simulated signal (with injectable, ground-truth fault
  modes) is the strongest honest demonstration of "I understand the
  features and the model" available in an interview prototype. The
  CWRU bearing dataset in `docs/references.md` is the public
  benchmark for the next phase.

---

## 7. Further reading

- `docs/references.md` — the full paper / spec / production-pattern
  list, now extended with cardinality, OTA, alarm-storm, backpressure,
  and CDC references plus the 2024–2026 industrial-AI frontier
  (Siemens Industrial Copilot, NVIDIA Metropolis, NVIDIA Omniverse /
  Cosmos).
- `docs/architecture.md` — layer-by-layer rationale of the pipeline.
- `docs/design-decisions.md` — why this scope, why these choices.
- `docs/roadmap.md` — what's done, what's planned, what's stretch.
