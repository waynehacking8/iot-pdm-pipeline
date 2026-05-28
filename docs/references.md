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

---

## Background reading

16. **Hennig, *Industry 4.0: The Industrial Internet of Things***
    (2016). Frames the business and operational context of IIoT.
17. **Kim, Park, *Smart Factory Architectures and Technologies***
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
