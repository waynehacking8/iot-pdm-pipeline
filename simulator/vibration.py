"""Synthetic vibration signal generator for a rotating machine.

The signal model:

    a(t) = base_amplitude * sin(2π · f_rot · t)
         + sum of harmonic terms (2×, 3× rotation frequency)
         + fault-mode injections (imbalance, misalignment, bearing wear)
         + Gaussian noise

Default settings approximate an industrial-grade accelerometer attached
to a rotating shaft at 60 Hz (3600 RPM), sampled at 25.6 kHz.

This module produces NumPy time-series arrays. It does not publish to
MQTT; see ``simulator.publisher`` for transport.

TODO:
    - Implement the time-domain signal model.
    - Implement fault-mode injectors (imbalance, misalignment, bearing).
    - Add a bearing-fault envelope-spectrum signature (BPFO / BPFI).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np


FaultMode = Literal["healthy", "imbalance", "misalignment", "outer_race", "inner_race"]


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

    The 3 channels correspond to x, y, z axes; in this minimal model the
    fault-mode signal lives on the x-axis with smaller leakage to y and z.

    Args:
        config: sensor parameters and fault state.
        duration_s: window duration in seconds.

    Returns:
        A 2-D NumPy array of shape (3, ``int(duration_s * sampling_rate)``).
    """
    raise NotImplementedError("To be implemented in Phase 1.1")
