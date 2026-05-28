"""Time-domain and frequency-domain feature extractors for vibration signals.

The 8-dim feature vector is suitable input to IsolationForest or any
tabular anomaly detector. See ``docs/specifications.md`` section 2 for
the formulas and acceptance criteria.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
from scipy.signal import hilbert


_ENVELOPE_MAX_HZ = 500.0  # upper cutoff for envelope-spectrum search


class FeatureVector(NamedTuple):
    rms: float
    peak_to_peak: float
    crest: float
    kurtosis: float
    peak_1x: float
    peak_2x: float
    peak_3x: float
    envelope_peak: float


def extract_features(
    signal: np.ndarray, sampling_rate_hz: float, rotation_freq_hz: float
) -> FeatureVector:
    """Compute the 8-dim feature vector for one channel of vibration data."""
    signal = np.asarray(signal, dtype=np.float64)
    n = signal.size

    rms = float(np.sqrt(np.mean(signal * signal)))
    peak_to_peak = float(signal.max() - signal.min())
    abs_peak = float(np.max(np.abs(signal)))
    crest = abs_peak / rms if rms > 0 else 0.0
    kurt = _fisher_kurtosis(signal)

    spectrum = np.abs(np.fft.rfft(signal)) * (2.0 / n)
    freqs = np.fft.rfftfreq(n, d=1.0 / sampling_rate_hz)
    peak_1x = _peak_at(spectrum, freqs, rotation_freq_hz)
    peak_2x = _peak_at(spectrum, freqs, 2.0 * rotation_freq_hz)
    peak_3x = _peak_at(spectrum, freqs, 3.0 * rotation_freq_hz)

    envelope_peak = _envelope_peak(
        signal, sampling_rate_hz, rotation_freq_hz, freqs
    )

    return FeatureVector(
        rms=rms,
        peak_to_peak=peak_to_peak,
        crest=crest,
        kurtosis=kurt,
        peak_1x=peak_1x,
        peak_2x=peak_2x,
        peak_3x=peak_3x,
        envelope_peak=envelope_peak,
    )


def _fisher_kurtosis(signal: np.ndarray) -> float:
    centered = signal - signal.mean()
    var = float(np.mean(centered * centered))
    if var == 0.0:
        return 0.0
    return float(np.mean(centered**4) / (var * var) - 3.0)


def _peak_at(spectrum: np.ndarray, freqs: np.ndarray, target_hz: float) -> float:
    bin_index = int(np.argmin(np.abs(freqs - target_hz)))
    return float(spectrum[bin_index])


def _envelope_peak(
    signal: np.ndarray,
    sampling_rate_hz: float,
    rotation_freq_hz: float,
    freqs: np.ndarray,
) -> float:
    """Peak of the Hilbert-envelope spectrum below 500 Hz, excluding DC and 1x."""
    envelope = np.abs(hilbert(signal))
    envelope = envelope - envelope.mean()
    env_spectrum = np.abs(np.fft.rfft(envelope)) * (2.0 / envelope.size)

    f_rot_bin = int(np.argmin(np.abs(freqs - rotation_freq_hz)))
    mask = (freqs > 0.0) & (freqs <= _ENVELOPE_MAX_HZ)
    mask[f_rot_bin] = False
    if not mask.any():
        return 0.0
    return float(env_spectrum[mask].max())
