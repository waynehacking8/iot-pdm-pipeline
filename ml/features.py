"""Time-domain and frequency-domain feature extractors for vibration signals.

The feature set is the minimum needed to discriminate the three fault
modes implemented in the simulator:

    Time-domain:
        rms             — root-mean-square amplitude (overall energy)
        peak_to_peak    — max(signal) - min(signal)
        crest           — max(|signal|) / rms (impulsiveness indicator)
        kurtosis        — 4th standardized moment (sharp-impulse sensitivity)

    Frequency-domain (from FFT magnitude spectrum):
        peak_1x         — magnitude at the rotation frequency
        peak_2x         — magnitude at 2x rotation frequency
        peak_3x         — magnitude at 3x rotation frequency
        envelope_peak   — peak of the Hilbert envelope spectrum below 500 Hz
                          (sensitive to bearing-fault-induced impulses)

The 8-dim feature vector is suitable input to IsolationForest or any
tabular anomaly detector.

TODO:
    - Implement time-domain features.
    - Implement FFT + peak-picking at harmonic frequencies.
    - Implement Hilbert envelope spectrum.
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np


class FeatureVector(NamedTuple):
    rms: float
    peak_to_peak: float
    crest: float
    kurtosis: float
    peak_1x: float
    peak_2x: float
    peak_3x: float
    envelope_peak: float


def extract_features(signal: np.ndarray, sampling_rate_hz: float, rotation_freq_hz: float) -> FeatureVector:
    """Compute the 8-dim feature vector for one channel of vibration data.

    Args:
        signal: 1-D NumPy array of acceleration samples.
        sampling_rate_hz: sampling frequency of ``signal``.
        rotation_freq_hz: shaft rotation frequency, used to locate the 1×
            harmonic in the spectrum.

    Returns:
        ``FeatureVector`` with the 8 named scalars.
    """
    raise NotImplementedError("To be implemented in Phase 1.2")
