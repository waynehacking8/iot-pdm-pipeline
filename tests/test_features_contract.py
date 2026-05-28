"""Smoke tests guarding the FeatureVector contract.

If you change the named-tuple, downstream serialization (MQTT payload,
TimescaleDB schema) will break. These tests pin the contract.
"""

from __future__ import annotations

from ml.features import FeatureVector


def test_feature_vector_fields() -> None:
    assert FeatureVector._fields == (
        "rms",
        "peak_to_peak",
        "crest",
        "kurtosis",
        "peak_1x",
        "peak_2x",
        "peak_3x",
        "envelope_peak",
    )
