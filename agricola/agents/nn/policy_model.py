"""Placement-policy model + normalization wrapper (POLICY_HEAD.md §6).

`NormalizedPolicyModel(net, PolicyNormStats)` wraps a `ConfigurableMLP`
(output_dim=25, head="linear") with fixed input-normalization buffers:

- `forward(x)` → raw logits `(B, 25)` in normalized-input space.
- `predict_logits(x, legal_mask)` → logits with illegal spaces masked to
  `−inf` (so they receive neither gradient nor probability). A row whose mask
  is entirely False (never a real placement state — there's always an open
  space) is treated as all-legal to avoid a NaN softmax.
- `policy_probs(x, legal_mask)` → softmax over the masked logits; illegal
  columns are exactly 0.

There is **no** target normalization (classification) and no `value_scale`
(an MCTS-leaf concept for the value net). Persistence mirrors
`NormalizedValueModel.save/load` — `<path>.pt` (state_dict incl. the norm
buffers) + `<path>.meta.json` (net config + `encoding_version`), hard-failing
on an `ENCODING_VERSION` mismatch via the shared `EncodingVersionMismatch`.

Imports torch; not re-exported from `agricola.agents.nn.__init__`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from agricola.agents.nn.encoder import ENCODING_VERSION
from agricola.agents.nn.model import NET_REGISTRY, EncodingVersionMismatch
from agricola.agents.nn.policy_dataset import PolicyNormStats


class NormalizedPolicyModel(nn.Module):
    """Input-normalized placement classifier (25-way over `SPACE_IDS`)."""

    def __init__(self, net: nn.Module, stats: PolicyNormStats):
        super().__init__()
        if stats.encoding_version != ENCODING_VERSION:
            raise EncodingVersionMismatch(
                f"PolicyNormStats has encoding_version={stats.encoding_version}, "
                f"current ENCODING_VERSION={ENCODING_VERSION}. Regenerate the "
                f"policy dataset."
            )
        self.net = net
        self.encoding_version = int(stats.encoding_version)
        # Which DecisionHead this model serves (set post-construction by the
        # trainer; persisted in the meta sidecar). None for an unlabelled model.
        self.head_name: str | None = None
        self.register_buffer(
            "input_mean",
            torch.from_numpy(stats.input_mean.astype(np.float32)).clone(),
        )
        self.register_buffer(
            "input_std",
            torch.from_numpy(stats.input_std.astype(np.float32)).clone(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """Raw logits `(B, 25)` from normalized input."""
        x_normalized = (x - self.input_mean) / self.input_std
        return self.net(x_normalized)

    def predict_logits(
        self, x: torch.Tensor, legal_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Logits with illegal spaces set to `−inf`. `legal_mask` is a bool
        tensor `(B, 25)`. An all-False row is treated as all-legal (guards the
        impossible-in-practice no-legal-placement case against a NaN softmax)."""
        logits = self.forward(x)
        if legal_mask.dtype != torch.bool:
            legal_mask = legal_mask.bool()
        all_illegal = ~legal_mask.any(dim=-1, keepdim=True)
        effective = legal_mask | all_illegal
        return logits.masked_fill(~effective, float("-inf"))

    def policy_probs(
        self, x: torch.Tensor, legal_mask: torch.Tensor,
    ) -> torch.Tensor:
        """Softmax over the legal spaces; illegal columns are exactly 0."""
        return torch.softmax(self.predict_logits(x, legal_mask), dim=-1)

    # ---- Persistence (mirrors NormalizedValueModel) ----

    def save(self, path: str | Path, *, extras: dict | None = None) -> None:
        path = Path(path)
        net_type = type(self.net).__name__
        if net_type not in NET_REGISTRY:
            raise ValueError(
                f"net type {net_type!r} is not in NET_REGISTRY; cannot persist."
            )
        if not hasattr(self.net, "config_dict"):
            raise ValueError(
                f"net {net_type!r} must implement config_dict() to persist."
            )
        torch.save(self.state_dict(), path.with_suffix(".pt"))
        meta = {
            "model_kind": "policy",
            "head": self.head_name,
            "net_type": net_type,
            "net_config": self.net.config_dict(),
            "num_classes": int(self.net.config_dict().get("output_dim", 0)),
            "encoding_version": int(self.encoding_version),
            "extras": dict(extras) if extras else {},
        }
        with path.with_suffix(".meta.json").open("w") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "NormalizedPolicyModel":
        path = Path(path)
        with path.with_suffix(".meta.json").open("r") as f:
            meta = json.load(f)
        if meta["encoding_version"] != ENCODING_VERSION:
            raise EncodingVersionMismatch(
                f"Checkpoint {path} has encoding_version={meta['encoding_version']}, "
                f"current ENCODING_VERSION={ENCODING_VERSION}. Trained against a "
                f"different encoder schema."
            )
        net_type = meta["net_type"]
        if net_type not in NET_REGISTRY:
            raise ValueError(
                f"Checkpoint references unknown net_type {net_type!r}. "
                f"Available: {sorted(NET_REGISTRY)}."
            )
        net = NET_REGISTRY[net_type](**meta["net_config"])
        n = meta["net_config"]["input_dim"]
        placeholder = PolicyNormStats(
            input_mean=np.zeros(n, dtype=np.float32),
            input_std=np.ones(n, dtype=np.float32),
            encoding_version=meta["encoding_version"],
        )
        model = cls(net, placeholder)
        state = torch.load(path.with_suffix(".pt"), weights_only=True)
        model.load_state_dict(state)
        model.head_name = meta.get("head")
        return model
