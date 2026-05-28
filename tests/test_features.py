"""Tests for the edge feature extractor (specifications.md section 2)."""

from __future__ import annotations

import numpy as np

from ml.features import extract_features


def test_pure_sine_features(sampling_rate_hz: float, rotation_freq_hz: float) -> None:
    """Compare against analytical values for a unit-amplitude sine wave."""
    n = int(sampling_rate_hz)  # 1 second
    t = np.arange(n) / sampling_rate_hz
    signal = np.sin(2 * np.pi * rotation_freq_hz * t)
    f = extract_features(signal, sampling_rate_hz, rotation_freq_hz)

    assert f.rms == _pytest_approx(1 / np.sqrt(2), abs=0.01)
    assert f.peak_to_peak == _pytest_approx(2.0, abs=0.02)
    assert f.crest == _pytest_approx(np.sqrt(2), abs=0.02)
    # Sine wave kurtosis (Fisher's def, excess) = -1.5
    assert f.kurtosis == _pytest_approx(-1.5, abs=0.05)
    assert f.peak_1x > f.peak_2x
    assert f.peak_1x > f.peak_3x


def test_gaussian_noise_kurtosis(sampling_rate_hz: float, rotation_freq_hz: float) -> None:
    """For Gaussian noise, excess kurtosis should be near zero."""
    rng = np.random.default_rng(0)
    signal = rng.standard_normal(int(sampling_rate_hz))
    f = extract_features(signal, sampling_rate_hz, rotation_freq_hz)
    assert abs(f.kurtosis) < 0.3


def _pytest_approx(expected: float, **kwargs):
    """Lazy import to avoid hard pytest dependency in this scaffold."""
    import pytest

    return pytest.approx(expected, **kwargs)
