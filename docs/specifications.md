# Specifications

Function-level technical specifications. Each section corresponds to
one module or interface; agents implementing the corresponding code
should treat the formulas, shapes, and reference numbers here as
contracts.

---

## 1. Vibration signal model (`simulator/vibration.py`)

### Mathematical model

For a rotating shaft at frequency `f_rot` (Hz), the time-domain
acceleration signal on a single axis is:

```
a(t) = A_1 · sin(2π f_rot t)                              (1× component)
     + A_2 · sin(2π · 2 f_rot · t + φ_2)                  (2× harmonic)
     + A_3 · sin(2π · 3 f_rot · t + φ_3)                  (3× harmonic)
     + B(t)                                                (fault term, see below)
     + ε(t),   ε(t) ~ N(0, noise_std²)                     (Gaussian noise)
```

Defaults: `A_1 = base_amplitude`, `A_2 = 0.3 · A_1`,
`A_3 = 0.15 · A_1`, `φ_2 = π/4`, `φ_3 = π/2`.

### Fault terms `B(t)`

| Fault | Formula | Effect |
|---|---|---|
| `imbalance` | `severity · A_1 · sin(2π f_rot t)` | Boosts 1× harmonic |
| `misalignment` | `severity · A_1 · [sin(2π·2f_rot t) + 0.5·sin(2π·4f_rot t)]` | Boosts 2× and 4× harmonics |
| `outer_race` (bearing) | impulse train at `BPFO = 3.585 · f_rot`, scaled by `severity` | Periodic impulses |
| `inner_race` (bearing) | amplitude-modulated impulses at `BPFI = 5.415 · f_rot`, modulation freq `f_rot` | Sidebands around BPFI |
| `healthy` | `B(t) = 0` | No fault |

(BPFO/BPFI defaults are typical for SKF 6205-class bearings; document
the chosen bearing geometry in the function docstring.)

### Function signature

```python
def generate_window(config: SensorConfig, duration_s: float = 1.0) -> np.ndarray:
    """
    Returns: array of shape (3, int(duration_s * sampling_rate_hz)).
             Channel 0 = primary (x), channel 1 = y (50% leakage),
             channel 2 = z (25% leakage).
    Values:  acceleration in g (1 g ≈ 9.81 m/s²); typical range ±5 g.
    """
```

### Acceptance criteria

- Healthy signal: `mean(|a|) ≈ noise_std · sqrt(2/π) + A_1 · 2/π`.
- Imbalance at severity 1.0: 1× FFT peak is ≥ 2× higher than healthy.
- Bearing fault at severity 1.0: envelope spectrum (Hilbert magnitude)
  shows a clear peak at BPFO or BPFI ± 5% tolerance.
- Output is deterministic when `np.random.seed` is fixed.

---

## 2. Edge feature extractor (`ml/features.py`)

### 8-dim feature vector

| Index | Name | Formula |
|---|---|---|
| 0 | `rms` | `sqrt(mean(signal²))` |
| 1 | `peak_to_peak` | `max(signal) − min(signal)` |
| 2 | `crest` | `max(|signal|) / rms` |
| 3 | `kurtosis` | `mean((signal − μ)⁴) / σ⁴` (Fisher's definition; 0 for Gaussian) |
| 4 | `peak_1x` | Magnitude of FFT bin nearest to `f_rot` |
| 5 | `peak_2x` | Magnitude of FFT bin nearest to `2 · f_rot` |
| 6 | `peak_3x` | Magnitude of FFT bin nearest to `3 · f_rot` |
| 7 | `envelope_peak` | Peak of Hilbert-envelope spectrum below 500 Hz, excluding DC and 1× component |

### Function signature

```python
def extract_features(signal: np.ndarray,
                     sampling_rate_hz: float,
                     rotation_freq_hz: float) -> FeatureVector:
    """
    Args:
        signal: 1-D array of length N (use channel 0 of the sensor
                output for this prototype).
        sampling_rate_hz: e.g., 25_600.0
        rotation_freq_hz: e.g., 60.0

    Returns: NamedTuple(rms, peak_to_peak, crest, kurtosis,
                        peak_1x, peak_2x, peak_3x, envelope_peak)
    """
```

### Acceptance criteria

- For a pure sine of amplitude 1.0 at `f_rot`:
  - `rms ≈ 1 / sqrt(2) ≈ 0.707`
  - `peak_to_peak ≈ 2.0`
  - `crest ≈ sqrt(2) ≈ 1.414`
  - `kurtosis ≈ −1.5` (sine wave is platykurtic)
  - `peak_1x` >> `peak_2x` and `peak_3x`
- For pure Gaussian noise: `kurtosis ≈ 0`, harmonic peaks small.

---

## 3. MQTT publisher (`simulator/publisher.py`)

### CLI

```
python -m simulator.publisher \
    --device d001 --plant p001 \
    --rate 1.0 \
    --broker localhost --port 1883 \
    --fault-mode healthy --fault-severity 0.0 \
    [--schedule schedule.json]
```

Schedule JSON (optional) lets the publisher transition fault modes
over time:

```json
[
    {"after_s": 0,   "fault_mode": "healthy",   "severity": 0.0},
    {"after_s": 60,  "fault_mode": "imbalance", "severity": 0.5},
    {"after_s": 120, "fault_mode": "outer_race","severity": 1.0}
]
```

### Topic and payload

- Topic: `pdm/{plant_id}/{device_id}`
- QoS: 1
- Retain: false
- Payload (JSON):
  ```json
  {
      "device_id": "d001",
      "ts": "2026-05-28T08:31:42.123Z",
      "features": {
          "rms": 0.712,
          "peak_to_peak": 1.998,
          "crest": 1.412,
          "kurtosis": -1.502,
          "peak_1x": 0.487,
          "peak_2x": 0.142,
          "peak_3x": 0.071,
          "envelope_peak": 0.003
      },
      "fault_label": "healthy",
      "severity": 0.0
  }
  ```

`fault_label` and `severity` are present **only for synthetic data**;
they would not exist in a real device feed. They are kept here so the
downstream ML training script has ground truth.

### Acceptance criteria

- Publisher reconnects on broker disconnect with exponential backoff
  (1s, 2s, 4s, capped at 30s).
- Publisher does not block on broker outages; messages queued in
  memory up to 1000 then dropped with a warning.
- `mosquitto_sub -t 'pdm/#' -v` shows messages at the configured rate.

---

## 4. MQTT → Kafka bridge (`ingest/bridge.py`)

### Behavior

- Subscribe: `pdm/#` (all plants, all devices), QoS 1.
- For each received MQTT message:
  1. Parse JSON payload.
  2. Extract `device_id`.
  3. Produce to Kafka topic `pdm.features` with `key = device_id` and
     `value = original_json`.
- Kafka producer config:
  - `acks=all`
  - `linger.ms=10`
  - `batch.size=16384`
- Logs every 1000 messages: `bridge: forwarded 1000 messages, lag=...`.

### Acceptance criteria

- Throughput ≥ 1000 messages/sec on a laptop (sustained, single thread).
- Kafka partition key ensures same-device messages always go to the
  same partition.
- Bridge handles backpressure: if Kafka producer queue is full, MQTT
  ack is delayed (do not drop).

---

## 5. Kafka → TimescaleDB consumer (`ingest/consumer.py`)

### Schema

```sql
CREATE TABLE IF NOT EXISTS device_features (
    device_id      TEXT        NOT NULL,
    ts             TIMESTAMPTZ NOT NULL,
    rms            DOUBLE PRECISION NOT NULL,
    peak_to_peak   DOUBLE PRECISION NOT NULL,
    crest          DOUBLE PRECISION NOT NULL,
    kurtosis       DOUBLE PRECISION NOT NULL,
    peak_1x        DOUBLE PRECISION NOT NULL,
    peak_2x        DOUBLE PRECISION NOT NULL,
    peak_3x        DOUBLE PRECISION NOT NULL,
    envelope_peak  DOUBLE PRECISION NOT NULL,
    fault_label    TEXT,
    severity       DOUBLE PRECISION
);

SELECT create_hypertable('device_features', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS idx_device_ts
    ON device_features (device_id, ts DESC);
```

### Batching

- Batch by 100 messages OR 1 second, whichever comes first.
- Use `COPY ... FROM STDIN` (psycopg `cursor.copy()`) for batch insert
  (10× faster than `INSERT VALUES`).

### Idempotency

- Auto-commit disabled on Kafka consumer.
- Commit offset **only after** the DB INSERT transaction commits.

### Acceptance criteria

- After a kill -9 restart, no duplicates in `device_features` and
  no gaps in the timeline.
- Sustained insertion of 1000 rows/sec without growing lag.

---

## 6. PdM training (`ml/train.py`)

### Procedure

1. Use the simulator to generate 7 days of healthy data at 1 Hz =
   604,800 samples per device, across 10 simulated devices.
2. Extract features → matrix of shape (6,048,000, 8).
3. Fit `StandardScaler` on the matrix.
4. Fit `IsolationForest(n_estimators=200, contamination=0.01,
   random_state=42)`.
5. Persist:
   - `ml/artifacts/scaler.joblib`
   - `ml/artifacts/model.joblib`
   - `ml/artifacts/training_summary.json` (sample counts, fit time,
     per-feature mean and std)

### Acceptance criteria

- `training_summary.json` reports `n_samples ≈ 6e6` and `fit_time_s
  < 60` on a laptop.
- The scaler's per-feature means are within 1% of the simulator's
  theoretical means.

---

## 7. PdM inference (`ml/inference.py`)

### Procedure

- Consume `pdm.features`.
- For each message: scale features → `model.decision_function` →
  anomaly score (lower = more anomalous, per sklearn convention).
- Maintain a 300-sample rolling buffer per device.
- Emit an alert to topic `pdm.alerts` when the rolling mean score
  drops below `−0.1` (configurable threshold).
- Debounce: do not re-alert the same device within 10 minutes.

### Acceptance criteria

- On synthetic fault sequences (60s healthy → 60s fault @ severity 1.0):
  - Alert fires within 30 seconds of fault onset.
  - No alerts during the healthy segment (false positive rate < 1%).
- F1 across the four fault modes at severity 1.0 is ≥ 0.85.

---

## 8. Reference benchmarks

Expected performance on the synthetic dataset (laptop, no GPU):

| Metric | Target |
|---|---|
| Simulator throughput (1 feature vector/sec/device) | 100 devices in real time |
| MQTT broker (EMQX 5.x) | 10,000 msg/sec single node |
| Kafka producer | 5,000 msg/sec single broker |
| TimescaleDB write | 2,000 row/sec batched |
| IsolationForest score per sample | < 1 ms |
| End-to-end latency (sensor tick → DB row) | < 200 ms |

If your implementation falls below these by >2×, suspect a bug, not
the design.
