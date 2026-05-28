"""LSTM autoencoder anomaly detector — HANDOFF.md stretch goal.

Trained on healthy 30-step feature sequences. Anomaly score = mean
reconstruction MSE across (seq_len, feature_dim). Higher = more
anomalous.

Compared head-to-head with the IsolationForest baseline in
``scripts/bench_lstm_vs_iforest.py``; ROC and F1 reported in
``results/REPORT.md`` section 7.

Requires CUDA (RTX PRO 6000 Blackwell; capability 12.0; needs torch
built for cu128 — see HANDOFF). Falls back to CPU if CUDA absent
(slower, identical math).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, TensorDataset

log = logging.getLogger("lstm")

ARTIFACTS = Path(__file__).resolve().parent / "artifacts"


@dataclass(frozen=True)
class LSTMConfig:
    input_dim: int = 8
    hidden_dim: int = 16
    num_layers: int = 2
    seq_len: int = 30
    dropout: float = 0.0


class LSTMAutoencoder(nn.Module):
    def __init__(self, cfg: LSTMConfig = LSTMConfig()):
        super().__init__()
        self.cfg = cfg
        self.encoder = nn.LSTM(
            cfg.input_dim,
            cfg.hidden_dim,
            num_layers=cfg.num_layers,
            batch_first=True,
            dropout=cfg.dropout if cfg.num_layers > 1 else 0.0,
        )
        self.decoder = nn.LSTM(
            cfg.hidden_dim,
            cfg.hidden_dim,
            num_layers=cfg.num_layers,
            batch_first=True,
            dropout=cfg.dropout if cfg.num_layers > 1 else 0.0,
        )
        self.output = nn.Linear(cfg.hidden_dim, cfg.input_dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, input_dim)
        _, (h, _) = self.encoder(x)            # h: (num_layers, batch, hidden_dim)
        latent = h[-1]                          # (batch, hidden_dim)
        repeated = latent.unsqueeze(1).expand(-1, self.cfg.seq_len, -1)
        decoded, _ = self.decoder(repeated)
        return self.output(decoded)             # (batch, seq_len, input_dim)

    def score(self, x: torch.Tensor) -> torch.Tensor:
        """Per-sequence reconstruction MSE."""
        self.eval()
        with torch.no_grad():
            recon = self.forward(x)
            mse = ((recon - x) ** 2).mean(dim=(1, 2))
        return mse


def features_to_sequences(features: np.ndarray, seq_len: int) -> np.ndarray:
    """Reshape (N, D) -> (N // seq_len, seq_len, D), dropping the tail."""
    n_full = (features.shape[0] // seq_len) * seq_len
    return features[:n_full].reshape(-1, seq_len, features.shape[1])


def train_autoencoder(
    feature_matrix: np.ndarray,
    cfg: LSTMConfig = LSTMConfig(),
    epochs: int = 30,
    batch_size: int = 64,
    lr: float = 1e-3,
    device: str | None = None,
    log_every: int = 5,
) -> tuple[LSTMAutoencoder, list[float]]:
    """Fit autoencoder on healthy features. Returns (model, loss_history)."""
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("training LSTM autoencoder on device=%s", device)

    seqs = features_to_sequences(feature_matrix, cfg.seq_len)
    log.info("input shape %s -> %d sequences of length %d",
             feature_matrix.shape, seqs.shape[0], cfg.seq_len)
    X = torch.from_numpy(seqs.astype(np.float32))
    dataset = TensorDataset(X)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, drop_last=False)

    model = LSTMAutoencoder(cfg).to(device)
    optim = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    history: list[float] = []
    for epoch in range(1, epochs + 1):
        model.train()
        epoch_loss = 0.0
        n = 0
        for (batch,) in loader:
            batch = batch.to(device, non_blocking=True)
            recon = model(batch)
            loss = loss_fn(recon, batch)
            optim.zero_grad()
            loss.backward()
            optim.step()
            epoch_loss += loss.item() * batch.size(0)
            n += batch.size(0)
        avg = epoch_loss / n
        history.append(avg)
        if log_every and (epoch == 1 or epoch % log_every == 0 or epoch == epochs):
            log.info("  epoch %3d / %3d  loss=%.6f", epoch, epochs, avg)
    return model, history


def save_artifacts(
    model: LSTMAutoencoder,
    history: list[float],
    out_dir: Path = ARTIFACTS,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    torch.save(
        {
            "state_dict": model.state_dict(),
            "config": model.cfg.__dict__,
            "loss_history": history,
        },
        out_dir / "lstm_autoencoder.pt",
    )


def load_model(path: Path = ARTIFACTS / "lstm_autoencoder.pt", device: str | None = None) -> LSTMAutoencoder:
    if device is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    blob = torch.load(path, map_location=device, weights_only=False)
    cfg = LSTMConfig(**blob["config"])
    model = LSTMAutoencoder(cfg).to(device)
    model.load_state_dict(blob["state_dict"])
    model.eval()
    return model


def score_features(
    model: LSTMAutoencoder,
    feature_matrix: np.ndarray,
    device: str | None = None,
) -> np.ndarray:
    """Per-sequence anomaly score (mean MSE)."""
    if device is None:
        device = next(model.parameters()).device.type
    seqs = features_to_sequences(feature_matrix, model.cfg.seq_len)
    X = torch.from_numpy(seqs.astype(np.float32)).to(device)
    with torch.no_grad():
        return model.score(X).cpu().numpy()
