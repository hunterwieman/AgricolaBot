"""PyTorch model + normalization wrapper for the NN value function.

Two classes:

- **`ConfigurableMLP(input_dim, hidden_dims, output_dim=1, activation,
  norm, dropout)`** — a parameterized MLP, architecture-agnostic of any
  specific task. Composable: usable as the full value network
  (`output_dim=1`), as a per-player sub-encoder for a future Siamese
  architecture (`output_dim > 1`), or as a value/policy head on top of
  a trunk. See FIRST_NN.md §7.1.

- **`NormalizedValueModel(net, norm_stats)`** — wraps a base network
  with fixed normalization buffers. `forward(x)` normalizes inputs by
  `(input_mean, input_std)` and returns the normalized scalar output
  (used during training). `predict_margin(x)` additionally multiplies
  the output by `target_std` to return margin units (used at inference
  by `NNAgent`). The buffers travel with the model — `.to(device)`
  moves them, `state_dict` saves them — so inference can never forget
  to apply normalization.

Persistence: `save(path)` writes `<path>.pt` (state_dict — weights AND
normalization buffers) plus `<path>.meta.json` (architecture config +
`encoding_version` + optional `extras`). `load(path)` reads the sidecar,
reconstructs the inner net via the architecture config, then loads the
state_dict. Hard-fails on `encoding_version` mismatch.

This module imports torch — the eager-import is in `dataset.py` + here,
not in `__init__.py`, so data-generation code that imports
`agricola.agents.nn` for the schema/recording stays torch-free.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Type

import numpy as np
import torch
from torch import nn

from agricola.agents.nn.dataset import NormStats
from agricola.agents.nn.encoder import ENCODING_VERSION


# ---------------------------------------------------------------------------
# ConfigurableMLP
# ---------------------------------------------------------------------------

# String dispatch for activations and normalizers — keeps configs JSON-clean
# (sidecar metadata stores strings, not module references).

_ACTIVATIONS: dict[str, Type[nn.Module]] = {
    "gelu": nn.GELU,
    "silu": nn.SiLU,
    "relu": nn.ReLU,
    "tanh": nn.Tanh,
}

_NORMS = {
    "layer": lambda dim: nn.LayerNorm(dim),
    "none": lambda dim: nn.Identity(),
}

# Final-layer activation ("head"). `linear` (default) = raw output for
# unbounded regression (margin target). `tanh` bounds to (-1, 1) for the
# zero-sum outcome target. `sigmoid` bounds to (0, 1) for the win-prob
# target. See FIRST_NN.md Experiment P2.
_HEADS: dict[str, Type[nn.Module]] = {
    "linear": nn.Identity,
    "tanh": nn.Tanh,
    "sigmoid": nn.Sigmoid,
}


class ConfigurableMLP(nn.Module):
    """Parameterized MLP. Architecture:

        Linear → Norm → Activation → Dropout → ... → Linear(output_dim)

    Post-norm (norm AFTER linear, BEFORE activation) — the classical
    placement; works well for shallow networks. Output has no
    activation — for regression targets the head is raw; for
    classification heads, the loss (`CrossEntropyLoss`) applies softmax
    internally for numerical stability.

    `output_dim=1` (the default) squeezes the trailing dimension so the
    output shape is `(batch,)` — matches scalar regression targets
    without MSELoss broadcasting warnings. `output_dim > 1` keeps the
    `(batch, output_dim)` shape — usable as a sub-encoder.

    Init: PyTorch defaults (Kaiming-uniform for `nn.Linear`). For
    shallow networks with modern activations + LayerNorm, this is
    sufficient; we don't override.
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dims: list[int],
        output_dim: int = 1,
        activation: str = "gelu",
        norm: str = "layer",
        dropout: float = 0.0,
        head: str = "linear",
    ):
        super().__init__()
        if activation not in _ACTIVATIONS:
            raise ValueError(
                f"activation must be one of {sorted(_ACTIVATIONS)}; "
                f"got {activation!r}"
            )
        if norm not in _NORMS:
            raise ValueError(
                f"norm must be one of {sorted(_NORMS)}; got {norm!r}"
            )
        if head not in _HEADS:
            raise ValueError(
                f"head must be one of {sorted(_HEADS)}; got {head!r}"
            )
        if not 0.0 <= dropout < 1.0:
            raise ValueError(f"dropout must be in [0, 1); got {dropout}")
        if input_dim < 1 or output_dim < 1:
            raise ValueError(
                f"input_dim and output_dim must be ≥ 1; "
                f"got input={input_dim}, output={output_dim}"
            )

        self.input_dim = int(input_dim)
        self.hidden_dims = list(hidden_dims)
        self.output_dim = int(output_dim)
        self.activation = activation
        self.norm = norm
        self.dropout = float(dropout)
        self.head = head

        act_cls = _ACTIVATIONS[activation]
        norm_factory = _NORMS[norm]
        head_cls = _HEADS[head]

        layers: list[nn.Module] = []
        prev_dim = self.input_dim
        for h in self.hidden_dims:
            layers.append(nn.Linear(prev_dim, h))
            layers.append(norm_factory(h))
            layers.append(act_cls())
            if self.dropout > 0:
                layers.append(nn.Dropout(self.dropout))
            prev_dim = h
        layers.append(nn.Linear(prev_dim, self.output_dim))
        # Final-layer activation. Identity for linear (margin); tanh/sigmoid
        # bound the output for the outcome / win-prob targets (Experiment P2).
        layers.append(head_cls())
        self.net = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.net(x)
        if self.output_dim == 1:
            return out.squeeze(-1)
        return out

    def config_dict(self) -> dict:
        """The constructor arguments — minimum info to recreate this
        module. Persisted in the sidecar by `NormalizedValueModel.save`."""
        return {
            "input_dim": self.input_dim,
            "hidden_dims": list(self.hidden_dims),
            "output_dim": self.output_dim,
            "activation": self.activation,
            "norm": self.norm,
            "dropout": self.dropout,
            "head": self.head,
        }

    def param_count(self) -> int:
        """Total trainable parameter count. Useful for sanity-checking
        architecture size."""
        return sum(p.numel() for p in self.parameters())


# ---------------------------------------------------------------------------
# NormalizedValueModel
# ---------------------------------------------------------------------------

# Registry maps net-class names → classes for save/load reconstruction.
# Add new architectures (e.g., a Siamese class) here when they land.
NET_REGISTRY: dict[str, Type[nn.Module]] = {
    "ConfigurableMLP": ConfigurableMLP,
}


class EncodingVersionMismatch(Exception):
    """Raised when a model's `encoding_version` doesn't match the
    current `ENCODING_VERSION`. Hard-fail to prevent silent
    misinterpretation of input features.

    The same error class lives in `schema.DataVersionMismatch` for
    dataset-schema drift; this one is the encoder-schema sibling.
    """


class NormalizedValueModel(nn.Module):
    """Wraps a base network with fixed normalization buffers.

    `forward(x)`: normalize input by `(input_mean, input_std)`, call
    the inner net, return the **normalized** scalar output. Training
    targets are also normalized (the dataset divides by `target_std`),
    so the loss is in normalized space — keeps loss values on a
    unit-ish scale for the optimizer.

    `predict_margin(x)`: forward + multiply by `target_std` → returns
    values in **margin units**. This is what `NNAgent` calls.

    `value_scale`: a plain float (default 1.0), the std of this model's
    leaf-differential `V(s,0) − V(s,1)` over a representative state
    sample. NOT used by `forward`/`predict_margin` (so standalone NNAgent
    is unaffected) — it's read by MCTS to normalize leaf values to unit
    scale so a single `c_uct` works across value heads of different
    magnitude (margin ~tens of points vs tanh/sigmoid ~order 1). See
    FIRST_NN.md Experiment P2 / §10.x. Measured post-training
    (`measure_leaf_value_scale`) and persisted in the meta sidecar, NOT
    the state_dict — so pre-P2 checkpoints load fine and default to 1.0.

    Buffers (`input_mean`, `input_std`, `target_std`) are stored in the
    `state_dict` (saved with weights, moved with `.to(device)`) but not
    trained. `encoding_version` + `value_scale` are stored in the
    metadata sidecar; `encoding_version` is hard-checked at load time.
    """

    def __init__(self, net: nn.Module, norm_stats: NormStats):
        super().__init__()
        if norm_stats.encoding_version != ENCODING_VERSION:
            raise EncodingVersionMismatch(
                f"NormStats has encoding_version="
                f"{norm_stats.encoding_version}, current ENCODING_VERSION="
                f"{ENCODING_VERSION}. The stats are from a different "
                f"encoder schema — regenerate the dataset."
            )
        self.net = net
        self.encoding_version = int(norm_stats.encoding_version)
        # Leaf-value scale for MCTS normalization (plain attr, set
        # post-training; persisted in meta, not state_dict). Default 1.0
        # = no normalization (correct for unmeasured / pre-P2 models).
        self.value_scale: float = 1.0

        # Fixed (non-trainable) buffers. .clone() detaches from the source
        # numpy array in case the caller mutates it after construction.
        self.register_buffer(
            "input_mean",
            torch.from_numpy(norm_stats.input_mean.astype(np.float32)).clone(),
        )
        self.register_buffer(
            "input_std",
            torch.from_numpy(norm_stats.input_std.astype(np.float32)).clone(),
        )
        self.register_buffer(
            "target_std",
            torch.tensor(float(norm_stats.target_std), dtype=torch.float32),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Normalized output — for training loss. (x − mean) / std → net → raw output."""
        x_normalized = (x - self.input_mean) / self.input_std
        return self.net(x_normalized)

    def predict_margin(self, x: torch.Tensor) -> torch.Tensor:
        """Denormalized output — margin units. For inference / NNAgent."""
        return self.forward(x) * self.target_std

    # ---- Persistence ----

    def save(self, path: str | Path, *, extras: dict | None = None) -> None:
        """Save weights + buffers to `<path>.pt` and architecture +
        version metadata to `<path>.meta.json`.

        `extras`: optional dict of training-run lineage info (git SHA,
        run id, dataset run id, training metrics, etc.). Persisted as-is
        in the sidecar for analytics / debugging.
        """
        path = Path(path)
        net_type = type(self.net).__name__
        if net_type not in NET_REGISTRY:
            raise ValueError(
                f"net type {net_type!r} is not in NET_REGISTRY; "
                f"cannot persist. Register the class before saving."
            )
        if not hasattr(self.net, "config_dict"):
            raise ValueError(
                f"net {net_type!r} must implement `config_dict()` "
                f"returning constructor kwargs to support persistence."
            )

        torch.save(self.state_dict(), path.with_suffix(".pt"))

        meta = {
            "net_type": net_type,
            "net_config": self.net.config_dict(),
            "encoding_version": int(self.encoding_version),
            "value_scale": float(self.value_scale),
            "extras": dict(extras) if extras else {},
        }
        with path.with_suffix(".meta.json").open("w") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "NormalizedValueModel":
        """Reconstruct from `<path>.pt` + `<path>.meta.json`.

        Hard-fails on `encoding_version` mismatch (the saved model
        expects features from a different encoder schema)."""
        path = Path(path)
        meta_path = path.with_suffix(".meta.json")
        weights_path = path.with_suffix(".pt")
        with meta_path.open("r") as f:
            meta = json.load(f)
        if meta["encoding_version"] != ENCODING_VERSION:
            raise EncodingVersionMismatch(
                f"Checkpoint {path} has encoding_version="
                f"{meta['encoding_version']}, current ENCODING_VERSION="
                f"{ENCODING_VERSION}. Model was trained against a "
                f"different encoder schema."
            )

        net_type = meta["net_type"]
        if net_type not in NET_REGISTRY:
            raise ValueError(
                f"Checkpoint references unknown net_type {net_type!r}. "
                f"Available: {sorted(NET_REGISTRY)}."
            )
        net = NET_REGISTRY[net_type](**meta["net_config"])

        # Placeholder NormStats — its buffer values will be overwritten
        # by load_state_dict below. We only need the encoding_version
        # check to pass (we already checked it from the sidecar above).
        n = meta["net_config"]["input_dim"]
        placeholder = NormStats(
            input_mean=np.zeros(n, dtype=np.float32),
            input_std=np.ones(n, dtype=np.float32),
            target_std=1.0,
            encoding_version=meta["encoding_version"],
        )
        model = cls(net, placeholder)
        # weights_only=True is the modern-safe pickle load (no arbitrary
        # code execution from the checkpoint).
        state = torch.load(weights_path, weights_only=True)
        model.load_state_dict(state)
        # Restore the MCTS leaf-value scale (meta-stored, default 1.0 for
        # pre-P2 checkpoints that predate this field).
        model.value_scale = float(meta.get("value_scale", 1.0))
        return model


@torch.no_grad()
def measure_leaf_value_scale(
    model: "NormalizedValueModel", x_paired: torch.Tensor,
) -> float:
    """Std of the leaf differential `V(s,0) − V(s,1)` over a state sample.

    `x_paired` is a feature tensor in the dataset's paired layout — rows
    `2i` and `2i+1` are the two perspective encodings of the same state
    (as produced by `build_datasets`' val/test arrays). The differential
    `predict_margin(x[2i]) − predict_margin(x[2i+1])` is exactly the
    leaf value MCTS feeds to UCB (`nn_evaluator_differential(s, 0)`), so
    its std is the right scale to normalize by. See FIRST_NN.md
    Experiment P2 — a single `c_uct` works across heads once each head's
    leaf is divided by this scale.
    """
    model.eval()
    pred = model.predict_margin(x_paired)
    diff = pred[0::2] - pred[1::2]
    s = float(diff.std().item())
    return s if s > 1e-9 else 1.0  # degenerate guard: never scale by ~0
