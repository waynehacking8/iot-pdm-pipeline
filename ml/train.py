"""Offline training of the PdM anomaly detector.

Pipeline:
    1. Use the simulator to generate a 7-day window of healthy vibration data.
    2. Extract feature vectors at 1 Hz → ~600k samples.
    3. Fit StandardScaler on the feature distribution.
    4. Fit IsolationForest with contamination = 0.01.
    5. Persist scaler and model to ``ml/artifacts/``.

CLI:
    python -m ml.train --output-dir ml/artifacts

TODO:
    - Implement the synthetic-data sampling loop.
    - Implement scaler + IsolationForest fitting.
    - Persist artifacts with joblib.
    - Emit a training-summary JSON (number of samples, fit time, feature
      statistics) for the README to reference.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("To be implemented in Phase 3.1")


if __name__ == "__main__":
    main()
