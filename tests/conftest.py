"""Shared pytest fixtures for the iot-pdm-pipeline test suite."""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def deterministic_numpy():
    """Seed NumPy's global RNG for reproducibility across tests."""
    np.random.seed(0)


@pytest.fixture
def sampling_rate_hz() -> float:
    return 25_600.0


@pytest.fixture
def rotation_freq_hz() -> float:
    return 60.0
