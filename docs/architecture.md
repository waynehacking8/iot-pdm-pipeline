# Architecture

A walkthrough of the layered pipeline, with the design rationale behind
each layer's component choice.

---

## Layer 1 — Sensor and Edge Processing

### What it does

A simulated rotating-machine vibration sensor produces a 3-axis
acceleration signal at 25.6 kHz. An on-device feature extractor
computes a compact summary (RMS, kurtosis, harmonic peaks) at 1 Hz
output rate. Only the summary is transmitted upstream.

### Why edge processing

| Concern | Raw 25.6 kHz | Edge-aggregated 1 Hz |
|---|---|---|
| Bandwidth per device | ~1.5 Mbps | ~50 bytes/s |
| 10,000 devices | 15 Gbps backbone | 500 KB/s |
| Cloud compute | Decode and FFT cloud-side | Pre-computed, indexable |
| Latency to alert | ~seconds (transport-bound) | ~milliseconds |

Industrial PdM systems universally do FFT and statistical aggregation
at the edge because the raw waveform is ~99% redundant — frequency-
domain peaks and time-domain moments carry essentially all the
diagnostic signal.

---

## Layer 2 — MQTT Broker

### What it does

EMQX (or any MQTT 5.0 broker) accepts publish messages from devices
and routes them to subscribers. Topic convention:
``pdm/{plant_id}/{device_id}``.

### Why MQTT

- **Lightweight pub/sub** — designed for constrained devices and
  intermittent links; the protocol overhead is ~10 bytes per message.
- **Quality-of-Service levels** — QoS 1 (at-least-once) gives durable
  delivery without the cost of QoS 2's full handshake.
- **Last Will and Testament (LWT)** — disconnected devices broadcast a
  pre-configured "offline" message automatically, enabling supervisory
  systems to react.
- **Retained messages** — newcomer subscribers get the latest message
  on a topic immediately, useful for state snapshots.

### Why EMQX specifically

EMQX runs on a laptop in a single container, scales to 1M+ connections
on a single node when needed, has a built-in MQTT-to-Kafka bridge, and
is open-source. Mosquitto would work as an alternative if simpler is
preferred; EMQX's built-in bridges remove an integration step.

---

## Layer 3 — Kafka

### What it does

Bridges MQTT messages into a Kafka topic (``pdm.features``) for durable
storage, replay, and fan-out to multiple downstream consumers.

### Why Kafka

- **Durable retention** — messages can be replayed for offline analysis
  or new-consumer onboarding without losing data.
- **Multiple independent consumers** — the TimescaleDB writer, the ML
  inference service, and any future analytics consumer can read the
  same topic without coordination.
- **Partitioning by device_id** — preserves per-device ordering while
  allowing horizontal scaling. Throughput scales linearly with partition
  count.

### Why both MQTT and Kafka

A common misconception is that MQTT and Kafka are alternatives. They
serve different roles:

| Role | MQTT | Kafka |
|---|---|---|
| Device-side fan-in | yes | no (heavy client) |
| Durable storage | no | yes |
| Backpressure handling | per-client buffer | broker buffer |
| Long-term retention | minutes | days–weeks |
| Topic discovery | wildcard subscribe | predefined topics |

The standard industrial IoT pattern is **MQTT at the edge, Kafka at the
backbone**, with a bridge translating between them.

---

## Layer 4 — TimescaleDB

### What it does

A Kafka consumer writes features into a TimescaleDB hypertable
partitioned by ``(device_id, ts)``. Hypertables provide automatic
time-based chunking, dramatically improving query performance for
time-range scans.

### Why TimescaleDB

- **PostgreSQL compatibility** — full SQL, joins, window functions; the
  ecosystem (drivers, dashboards, BI tools) works out of the box.
- **Automatic time-based partitioning** — Hypertables handle chunking
  transparently; queries that touch only recent data skip historical
  chunks.
- **Continuous aggregates** — pre-computed rollups (e.g., 1-minute
  mean RMS) materialize automatically and refresh on insert.

### Alternative considered: InfluxDB

InfluxDB has higher raw write throughput, but its query language (Flux)
and ecosystem are smaller. For this prototype's scale and the
preference for SQL portability, TimescaleDB wins. InfluxDB would be the
right choice at hyperscale write rates (>>100k writes/s/node).

---

## Layer 5 — PdM ML Model

### What it does

An anomaly-detection model (Isolation Forest as the baseline) is
trained on healthy-state features and scores incoming feature vectors
in near-real-time. Scores above threshold trigger an alert.

### Why anomaly detection rather than supervised classification

Real predictive-maintenance data is heavily imbalanced — the vast
majority of operating time is healthy. Supervised classification needs
labeled fault examples, which are expensive to collect. Anomaly
detection works with unlabeled "mostly healthy" history, which is
abundant.

### Stretch: shadow-mode rollout

Before promoting a new model to production, the old and new models run
in parallel on the same stream for a week. KS-test on the score
distributions tells us whether the new model is producing meaningfully
different outputs. This is standard practice in production PdM systems
and is on the roadmap.

---

## Layer 6 — Grafana Dashboard

A pre-configured Grafana dashboard displays per-device RMS trends,
recent anomaly scores, and active alerts. Grafana queries TimescaleDB
directly via its PostgreSQL data source.

---

## What this architecture deliberately omits

- **Authentication and TLS** — production needs both at every layer.
  Omitted to keep the demo runnable on a laptop without certificate
  hassle.
- **OPC UA / Modbus protocol adapters** — real factories speak these,
  not MQTT directly. The simulator stands in for the device-side
  adapter; in production an edge gateway (DIALink-class box) would
  translate.
- **Multi-tenancy and authorization** — every customer would have
  separate topic prefixes, RBAC at Kafka and TimescaleDB, and a control
  plane for device provisioning. Out of prototype scope.
- **High availability** — single-node deployments throughout. Real
  systems run EMQX clusters, Kafka with replication factor 3, and
  TimescaleDB with streaming replicas.
