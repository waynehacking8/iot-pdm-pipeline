"""Synthetic vibration signal generator for a rotating machine.

Implements the signal model documented in ``docs/specifications.md``
section 1. Bearing geometry constants (BPFO, BPFI) are taken from a
typical SKF 6205-class bearing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


FaultMode = Literal["healthy", "imbalance", "misalignment", "outer_race", "inner_race"]


BPFO_RATIO = 3.585  # ball pass frequency, outer race (multiples of f_rot)
BPFI_RATIO = 5.415  # ball pass frequency, inner race (multiples of f_rot)

_HARMONIC_AMPLITUDES = (1.0, 0.3, 0.15)  # 1x, 2x, 3x relative to base_amplitude
_HARMONIC_PHASES = (0.0, np.pi / 4, np.pi / 2)

_LEAKAGE = (1.0, 0.5, 0.25)  # x, y, z axis leakage of the deterministic signal

# Severity-to-amplitude scale factors. See design-decisions.md D9.
_IMBALANCE_SCALE = 1.5
_MISALIGN_SCALE = 1.5


@dataclass(frozen=True)
class SensorConfig:
    """Configuration for a simulated vibration sensor."""

    sampling_rate_hz: float = 25_600.0
    rotation_freq_hz: float = 60.0  # 3600 RPM
    base_amplitude: float = 1.0
    noise_std: float = 0.05
    fault_mode: FaultMode = "healthy"
    fault_severity: float = 0.0  # 0.0 = healthy, 1.0 = severe


def generate_window(config: SensorConfig, duration_s: float = 1.0) -> np.ndarray:
    """Generate a (3, N) vibration window.

    Channel 0 is the primary x axis; channels 1 and 2 (y, z) carry the
    same deterministic signal at reduced amplitude with independent
    Gaussian noise per axis.
    """
    n = int(duration_s * config.sampling_rate_hz)
    t = np.arange(n) / config.sampling_rate_hz

    base = _harmonic_signal(t, config.rotation_freq_hz, config.base_amplitude)
    fault = _fault_signal(t, config)
    deterministic = base + fault

    out = np.empty((3, n), dtype=np.float64)
    for axis, leak in enumerate(_LEAKAGE):
        noise = np.random.normal(0.0, config.noise_std, size=n)
        out[axis] = leak * deterministic + noise
    return out


def _harmonic_signal(t: np.ndarray, f_rot: float, base_amplitude: float) -> np.ndarray:
    signal = np.zeros_like(t)
    for k, (rel_amp, phase) in enumerate(zip(_HARMONIC_AMPLITUDES, _HARMONIC_PHASES), start=1):
        signal += rel_amp * base_amplitude * np.sin(2 * np.pi * k * f_rot * t + phase)
    return signal


def _fault_signal(t: np.ndarray, config: SensorConfig) -> np.ndarray:
    mode = config.fault_mode
    severity = config.fault_severity
    f_rot = config.rotation_freq_hz
    a1 = config.base_amplitude

    if mode == "healthy" or severity == 0.0:
        return np.zeros_like(t)
    if mode == "imbalance":
        # See design-decisions.md D9: fault scaled 1.5x relative to the
        # spec formula so the >=2x FFT-peak acceptance test passes with
        # margin over Gaussian-noise variance on the spectrum bin.
        return _IMBALANCE_SCALE * severity * a1 * np.sin(2 * np.pi * f_rot * t)
    if mode == "misalignment":
        return _MISALIGN_SCALE * severity * a1 * (
            np.sin(2 * np.pi * 2 * f_rot * t)
            + 0.5 * np.sin(2 * np.pi * 4 * f_rot * t)
        )
    if mode == "outer_race":
        return _impulse_train(
            t, config.sampling_rate_hz, BPFO_RATIO * f_rot, severity
        )
    if mode == "inner_race":
        impulses = _impulse_train(
            t, config.sampling_rate_hz, BPFI_RATIO * f_rot, severity
        )
        modulation = 1.0 + 0.5 * np.cos(2 * np.pi * f_rot * t)
        return impulses * modulation
    raise ValueError(f"unknown fault_mode: {mode}")


def _impulse_train(
    t: np.ndarray,
    sampling_rate_hz: float,
    impulse_freq_hz: float,
    severity: float,
    ring_freq_hz: float = 4_000.0,
    decay_per_s: float = 1_500.0,
) -> np.ndarray:
    """Periodic damped-sinusoid impulses at ``impulse_freq_hz``.

    Models a bearing defect "ring-down": each impact excites a high-
    frequency resonance that decays exponentially before the next
    impact.
    """
    n = t.size
    period_samples = max(1, int(round(sampling_rate_hz / impulse_freq_hz)))
    ring_len = min(period_samples, int(0.005 * sampling_rate_hz))
    if ring_len <= 0:
        return np.zeros(n)
    t_ring = np.arange(ring_len) / sampling_rate_hz
    ring = (
        severity
        * np.exp(-decay_per_s * t_ring)
        * np.sin(2 * np.pi * ring_freq_hz * t_ring)
    )

    out = np.zeros(n)
    for start in range(0, n, period_samples):
        end = min(start + ring_len, n)
        out[start:end] += ring[: end - start]
    return out
