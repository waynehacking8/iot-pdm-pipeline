# References

Curated reading list, roughly ordered from "primary references" to
"background reading".

---

## Primary references

### Protocols and standards

1. **MQTT 5.0 Specification** (OASIS, 2019). Sections 3.1–3.3 cover
   the publish/subscribe protocol layer and QoS semantics that the
   ingestion layer depends on.
2. **OPC UA Part 1: Overview and Concepts** (IEC 62541). For the
   long-term plan to add an OPC UA adapter; OPC UA is the
   cross-vendor industrial protocol of record.
3. **IPC-CFX (Connected Factory Exchange)** specification. Industry
   electronics-assembly standard that uses AMQP 1.0 + JSON. Skim for
   how a vertical-specific protocol layers on top of generic
   messaging.

### Vibration analysis and PdM

4. **Randall, *Vibration-Based Condition Monitoring*** (2011). The
   reference textbook for rotating-machine vibration features —
   harmonics, sidebands, envelope spectrum, bearing fault frequencies.
5. **Lessmeier et al. (2016)**, *Condition Monitoring of Bearing
   Damage in Electromechanical Drive Systems by Using Motor Current
   Signals.* — Public PdM dataset and feature methodology.
6. **CWRU Bearing Data Center** website. Standard public dataset for
   benchmarking rolling-element bearing diagnosis.

### Anomaly detection

7. **Liu, Ting, Zhou (2008)**, *Isolation Forest.* ICDM. The baseline
   anomaly detector used in the prototype.
8. **Schölkopf et al. (2001)**, *Estimating the Support of a
   High-Dimensional Distribution.* — One-Class SVM, an alternative.
9. **Sakurada & Yairi (2014)**, *Anomaly Detection Using
   Autoencoders.* — Deep approach for the roadmap stretch goal.

### Infrastructure

10. **TimescaleDB documentation** — hypertables, continuous
    aggregates, compression policies.
11. **EMQX 5 documentation** — bridges, authentication, MQTT 5
    features.
12. **Apache Kafka — The Definitive Guide** (Narkhede et al., 2017).
    Chapters on partitioning and consumer-group semantics.

---

## Industry references

13. **AWS IoT Reference Architecture** — the standard pattern of
    MQTT-at-edge, Kafka-at-backbone, time-series store.
14. **Microsoft Azure IoT Operations** — Microsoft's equivalent;
    useful as a counterpoint for cloud-portable patterns.
15. **Eclipse Sparkplug Specification** — a more opinionated MQTT
    convention for industrial use; uses topic and payload conventions
    that simplify multi-vendor integration.
16. **AWS IoT Greengrass v2 documentation** — edge runtime that
    inverts the cloud-first pattern; useful for understanding what
    "edge-autonomous" actually requires.
17. **KubeEdge** — Kubernetes-based edge orchestration; the "fleet
    of edges as a single control plane" framing.
18. **Siemens Industrial Edge platform** — proprietary but the
    most fully-developed edge-first architecture for OT / IT
    convergence.

---

## Production-pattern references (where the senior decisions live)

These are the patterns that look obvious in retrospect and burn
junior teams in the field.

### Time-series and cardinality

19. **InfluxData (2023)** — *TSI cardinality explained.* Why high-
    cardinality tags (per-request IDs, firmware-version hashes,
    free-form session IDs) cause TSI to blow up RAM and stall
    compaction. The number-one InfluxDB production failure mode.
20. **TimescaleDB hypertable internals** — chunk count, planner
    cost; the analog of cardinality explosion on the relational side.
21. **Apache Iceberg / Delta Lake small-files problem** — analytic
    side; the same problem in a different guise.

### Edge OTA, fleet rollout, and reconciliation

22. **Google Site Reliability Engineering, ch. 27 (Canary
    Deployments)** — generic canary discipline; reapplied here to
    OTA cohorts.
23. **Kubernetes reconciliation pattern** (Borg / Omega → Kubernetes
    lineage). The desired-state-versus-actual-state model that any
    serious IoT control plane converges to.
24. **Mender / Rauc / SWUpdate documentation** — A/B partition + dual-
    bank bootloader patterns for edge-autonomous OTA rollback. The
    minimum viable "rollback works even with no network".
25. **HashiCorp Consul, Nomad, Serf** — gossip-based fleet
    coordination; useful counterpoint to centralized rollouts.

### Alarm-storm suppression as signal processing

26. **Roeser & Bahder (2003)**, *Alarm management for the process
    industries* (ISA). The canonical industrial reference;
    pre-cloud but still the source of fingerprint-dedup, hysteresis,
    flapping-detection vocabulary.
27. **Google SRE workbook — Practical Alerting** — modern version of
    the same problem, expressed in token-bucket and SLO terms.
28. **Prometheus Alertmanager — grouping, inhibition, silencing** —
    the practical implementation most teams will actually deploy.

### Backpressure and queue dynamics

29. **Lattner et al. (2017)**, *Reactive Streams Specification.* The
    formal contract behind WebFlux / RxJava / Akka Streams that
    `@Async` does not provide.
30. **Crawshaw, *Queues don't fix overload* (blog post).** Short and
    correct on why bounded queues + `CallerRunsPolicy` is the only
    sane default in IoT ingestion.

### CDC and change propagation

31. **Debezium documentation — outbox pattern.** Why CDC of the
    business table is fragile and the outbox table is the production
    pattern.
32. **Vitess / LSN / GTID semantics** — monotonic clock guarantees
    that downstream consumers must rely on, not wall-clock time.

---

## Industrial AI / vertical foundation models (2024–2026 frontier)

The forward-looking edge of where this prototype's lineage is going.

33. **Siemens Industrial Copilot (2024–2026)** — LLM-as-interface
    over the existing OT / MES stack. The most concrete current
    deployment of "natural language → InfluxDB / SQL / alarm
    topology query" in industrial settings.
34. **NVIDIA Metropolis** — vision-foundation-model push into
    industrial inspection; not directly applicable to vibration
    PdM but the closest existing "industrial foundation model"
    program.
35. **GE Predix retrospective** (multiple post-mortem articles,
    2018–2023) — required reading for any industrial-cloud
    architect. The reasons Predix failed are exactly the patterns
    a serious IIoT platform now avoids by default.
36. **NVIDIA Omniverse / Cosmos (2024–2026)** — physics-informed
    world models. The longest-shot candidate for a "Sora moment" in
    industrial AI: simulation-driven prediction rather than
    sensor-driven detection.

---

## Background reading

37. **Hennig, *Industry 4.0: The Industrial Internet of Things***
    (2016). Frames the business and operational context of IIoT.
38. **Kim, Park, *Smart Factory Architectures and Technologies***
    (survey, 2020). Useful taxonomy of edge/cloud responsibilities.

---

## Suggested reading order

If approaching the area fresh:

1. MQTT 5.0 spec sections 3.1–3.3 — understand the wire protocol.
2. TimescaleDB hypertable docs — understand time-series storage.
3. Randall chapter on harmonics — understand the features.
4. Isolation Forest paper — understand the detector.
5. CWRU dataset description — understand real PdM data.

That ordering also matches the implementation phases in
`roadmap.md`.
