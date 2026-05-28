"""Tests for the synthetic vibration generator.

These tests encode the acceptance criteria from
``docs/specifications.md`` section 1. They will all fail until
``simulator.vibration.generate_window`` is implemented; that is the
intended starting state.
"""

from __future__ import annotations

import numpy as np
import pytest

from simulator.vibration import SensorConfig, generate_window


def test_output_shape(sampling_rate_hz: float, rotation_freq_hz: float) -> None:
    config = SensorConfig(
        sampling_rate_hz=sampling_rate_hz,
        rotation_freq_hz=rotation_freq_hz,
        fault_mode="healthy",
    )
    signal = generate_window(config, duration_s=1.0)
    assert signal.shape == (3, int(sampling_rate_hz))


def test_determinism(sampling_rate_hz: float, rotation_freq_hz: float) -> None:
    config = SensorConfig(
        sampling_rate_hz=sampling_rate_hz, rotation_freq_hz=rotation_freq_hz
    )
    np.random.seed(42)
    a = generate_window(config, duration_s=0.5)
    np.random.seed(42)
    b = generate_window(config, duration_s=0.5)
    np.testing.assert_array_equal(a, b)


def test_imbalance_amplifies_1x(sampling_rate_hz: float, rotation_freq_hz: float) -> None:
    """Imbalance at severity 1.0 should at least double the 1x FFT peak."""
    config_healthy = SensorConfig(
        sampling_rate_hz=sampling_rate_hz,
        rotation_freq_hz=rotation_freq_hz,
        fault_mode="healthy",
    )
    config_imbalance = SensorConfig(
        sampling_rate_hz=sampling_rate_hz,
        rotation_freq_hz=rotation_freq_hz,
        fault_mode="imbalance",
        fault_severity=1.0,
    )

    def fft_peak_at(signal: np.ndarray, freq: float) -> float:
        n = signal.size
        spectrum = np.abs(np.fft.rfft(signal))
        bin_index = int(round(freq * n / sampling_rate_hz))
        return float(spectrum[bin_index])

    healthy = generate_window(config_healthy, duration_s=2.0)[0]
    faulty = generate_window(config_imbalance, duration_s=2.0)[0]
    assert fft_peak_at(faulty, rotation_freq_hz) >= 2.0 * fft_peak_at(
        healthy, rotation_freq_hz
    )


@pytest.mark.parametrize("fault_mode", ["outer_race", "inner_race"])
def test_bearing_envelope_peak(
    fault_mode: str, sampling_rate_hz: float, rotation_freq_hz: float
) -> None:
    """Bearing faults must produce a visible envelope-spectrum peak."""
    config = SensorConfig(
        sampling_rate_hz=sampling_rate_hz,
        rotation_freq_hz=rotation_freq_hz,
        fault_mode=fault_mode,  # type: ignore[arg-type]
        fault_severity=1.0,
    )
    signal = generate_window(config, duration_s=2.0)[0]
    # Crude envelope: absolute value of analytic signal.
    from scipy.signal import hilbert

    envelope = np.abs(hilbert(signal))
    spectrum = np.abs(np.fft.rfft(envelope - envelope.mean()))
    assert spectrum.max() > 0.1, "envelope spectrum should show a clear peak"
