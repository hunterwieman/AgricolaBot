"""Shared-trunk value + policy network (Stage B).

One trunk feeds every head, so a single forward computes the shared
representation once and each head reads it (POLICY_HEAD.md / the shared-trunk
plan). This is the joint successor to the separate `NormalizedValueModel` +
nine independent policy/pointer models: instead of each head relearning its own
`170→…` trunk, they share it and train together.

**Architecture-agnostic by construction.** Every width/depth is a constructor
argument — trunk hidden dims, embedding width `E`, and the per-head hidden dims
(value / fixed / pointer). Nothing is baked in, so the same class serves any
point in the capacity sweep; you pass the shape, not edit the code.

Heads (all read the shared embedding `E`):

- **value head** — `MLP(E → 1)`; `predict_margin` preserves the exact contract
  of `NormalizedValueModel` (denormalized margin units, `value_scale` for MCTS),
  so the shared model is a drop-in value evaluator.
- **fixed heads** — one `MLP(E → K)` per fixed `DecisionHead` (placement, sow, …),
  masked-softmax at inference, cross-entropy-against-π at train.
- **pointer heads** — one `MLP([E ; candidate] → 1)` per `PointerHead`. The trunk
  runs **once** on the state; the (normalized) per-candidate features are
  concatenated onto that embedding and scored. This both unifies the pointer
  heads onto the shared trunk AND is cheaper than the standalone pointer model,
  which re-encoded the full `[state(170) ; cand]` row for every candidate.

The head *specs* (names → num_classes / candidate_dim) are passed in rather than
imported from `policy_heads`, keeping this module decoupled and pure-architecture;
`build_shared_trunk_model` (in the trainer) wires the registry to these specs.

Persistence mirrors `NormalizedValueModel`: `<path>.pt` (state_dict — weights +
all normalization buffers) and `<path>.meta.json` (architecture config +
`encoding_version` + `value_scale`). Hard-fails on encoder-version drift.

Imports torch; not re-exported from `agricola.agents.nn.__init__`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from agricola.agents.nn.dataset import NormStats
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.agents.nn.model import (
    NET_REGISTRY,
    ConfigurableMLP,
    EncodingVersionMismatch,
)


def _sanitize(name: str) -> str:
    """ModuleDict / buffer keys can't contain '.'; head names don't, but guard."""
    return name.replace(".", "_")


class SharedTrunkModel(nn.Module):
    """Trunk + value head + fixed-vocab heads + pointer heads, all sharing one
    `170 → … → E` trunk. See module docstring. Submodules are all
    `ConfigurableMLP`s so the architecture is uniform and JSON-reconstructable.

    Normalization buffers (in `state_dict`, moved by `.to`, saved by `save`):
    - `input_mean` / `input_std` `(ENCODED_DIM,)` — the shared state-input norm.
    - `target_std` scalar — the value target norm (margin units on denorm).
    - `cand_mean__<h>` / `cand_std__<h>` `(candidate_dim,)` per pointer head —
      the per-candidate feature norm (the embedding is already ~unit from
      `embed_norm`, so only the raw candidate features need scaling).
    """

    def __init__(
        self,
        *,
        fixed_head_specs: dict[str, int],
        pointer_head_specs: dict[str, int],
        norm_stats: NormStats,
        input_dim: int = ENCODED_DIM,
        trunk_hidden_dims: list[int] = (256, 256),
        embedding_dim: int = 256,
        value_head_dims: list[int] = (),
        outcome_head_dims: list[int] = (),
        fixed_head_dims: list[int] = (),
        pointer_head_dims: list[int] = (64,),
        activation: str = "gelu",
        norm: str = "layer",
        dropout: float = 0.0,
        embed_norm: bool = True,
    ):
        super().__init__()
        # Canonical (v2) stats are guarded by the int ENCODING_VERSION; a
        # candidate schema (encoding_tag set) is identified by its tag instead —
        # the int stays 2 but the feature set differs, and input_dim + the tag
        # are the guard. The dim consistency is enforced by input_mean.shape below.
        if not norm_stats.encoding_tag and norm_stats.encoding_version != ENCODING_VERSION:
            raise EncodingVersionMismatch(
                f"NormStats has encoding_version={norm_stats.encoding_version}, "
                f"current ENCODING_VERSION={ENCODING_VERSION}. Regenerate the dataset."
            )

        self.input_dim = int(input_dim)
        self.trunk_hidden_dims = list(trunk_hidden_dims)
        self.embedding_dim = int(embedding_dim)
        self.value_head_dims = list(value_head_dims)
        self.outcome_head_dims = list(outcome_head_dims)
        self.fixed_head_dims = list(fixed_head_dims)
        self.pointer_head_dims = list(pointer_head_dims)
        self.fixed_head_specs = {str(k): int(v) for k, v in fixed_head_specs.items()}
        self.pointer_head_specs = {str(k): int(v) for k, v in pointer_head_specs.items()}
        self.activation = activation
        self.norm = norm
        self.dropout = float(dropout)
        self.embed_norm_on = bool(embed_norm)
        self.encoding_version = int(norm_stats.encoding_version)
        self.encoding_tag = str(norm_stats.encoding_tag)
        self.value_scale: float = 1.0
        # What the value head's target was trained on: "margin" (terminal score
        # diff, the inference contract `predict_margin` denotes — units are
        # POINTS) or "outcome" (sign(margin) ∈ {-1,0,+1}). Consumers that read the
        # value as points (e.g. the web "Show analysis" badge, which scales Q by
        # value_scale) MUST guard on this being "margin". Set by the trainer;
        # persisted in / restored from meta. Default "margin" for backward compat
        # with checkpoints saved before this field existed (all of which were
        # margin-trained — the value head predates the outcome option).
        self.value_target_mode: str = "margin"

        E = self.embedding_dim
        common = dict(activation=activation, norm=norm, dropout=dropout, head="linear")

        # Trunk: 170 → trunk_hidden_dims → E (linear projection to the embedding).
        self.trunk = ConfigurableMLP(
            input_dim=self.input_dim, hidden_dims=self.trunk_hidden_dims,
            output_dim=E, **common,
        )
        # Optional LayerNorm on the embedding so every head reads a well-scaled
        # representation (matters most for the pointer heads' concat input).
        self.embed_norm = nn.LayerNorm(E) if (embed_norm and norm == "layer") \
            else nn.Identity()

        # Value head: E → 1 (squeezed to (B,) by ConfigurableMLP).
        self.value_head = ConfigurableMLP(
            input_dim=E, hidden_dims=self.value_head_dims, output_dim=1, **common,
        )
        # Outcome head: E → 1 — win/draw/loss = sign(margin) ∈ {-1,0,+1}, linear,
        # NOT scaled by target_std (outcome is already ~unit). Co-trained with the
        # value head off the SAME embedding (one trunk forward; see
        # shared_training._value_loss), so it adds no trunk cost. Pre-outcome
        # checkpoints lack its weights — `load` leaves it freshly initialized.
        self.outcome_head = ConfigurableMLP(
            input_dim=E, hidden_dims=self.outcome_head_dims, output_dim=1, **common,
        )
        # Fixed heads: E → K each.
        self.fixed_heads = nn.ModuleDict({
            _sanitize(name): ConfigurableMLP(
                input_dim=E, hidden_dims=self.fixed_head_dims, output_dim=K, **common,
            )
            for name, K in self.fixed_head_specs.items()
        })
        # Pointer heads: [E ; candidate(dim)] → 1 (scored per candidate).
        self.pointer_heads = nn.ModuleDict({
            _sanitize(name): ConfigurableMLP(
                input_dim=E + dim, hidden_dims=self.pointer_head_dims,
                output_dim=1, **common,
            )
            for name, dim in self.pointer_head_specs.items()
        })

        # ---- Normalization buffers ----
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
        # Per-pointer-head candidate-feature norm (default identity; the trainer
        # fits and sets these from the training candidates).
        for name, dim in self.pointer_head_specs.items():
            s = _sanitize(name)
            self.register_buffer(f"cand_mean__{s}", torch.zeros(dim, dtype=torch.float32))
            self.register_buffer(f"cand_std__{s}", torch.ones(dim, dtype=torch.float32))

    # ---- Forward primitives ----

    def embed(self, x: torch.Tensor) -> torch.Tensor:
        """State features `(B, input_dim)` → shared embedding `(B, E)`."""
        x = (x - self.input_mean) / self.input_std
        return self.embed_norm(self.trunk(x))

    def value_from_embedding(self, emb: torch.Tensor) -> torch.Tensor:
        """Normalized value `(B,)` — for the training loss (normalized space)."""
        return self.value_head(emb)

    def predict_margin(self, x: torch.Tensor) -> torch.Tensor:
        """Denormalized value in margin units `(B,)` — the inference contract
        `NNAgent` / MCTS expect (mirrors `NormalizedValueModel.predict_margin`)."""
        return self.value_from_embedding(self.embed(x)) * self.target_std

    def outcome_from_embedding(self, emb: torch.Tensor) -> torch.Tensor:
        """Outcome prediction `(B,)` in win/draw/loss space (target {-1,0,+1})
        from a precomputed embedding. No target_std scaling — outcome is already
        ~unit. The outcome counterpart to `value_from_embedding`."""
        return self.outcome_head(emb)

    def predict_outcome(self, x: torch.Tensor) -> torch.Tensor:
        """Outcome prediction `(B,)` from raw state features — one trunk forward,
        the outcome counterpart to `predict_margin`. Meaningful only for models
        whose outcome head was trained (see shared_training `train_outcome`)."""
        return self.outcome_from_embedding(self.embed(x))

    def fixed_logits_from_embedding(
        self, emb: torch.Tensor, head_name: str,
    ) -> torch.Tensor:
        """Raw logits `(B, K)` for a fixed head from a precomputed embedding."""
        return self.fixed_heads[_sanitize(head_name)](emb)

    def pointer_scores_from_embedding(
        self, head_name: str, emb_rows: torch.Tensor, cand_rows: torch.Tensor,
    ) -> torch.Tensor:
        """Per-candidate scores `(M,)`. `emb_rows` `(M, E)` is the candidate's
        state embedding (gather the per-state embedding by segment before
        calling); `cand_rows` `(M, candidate_dim)` the raw candidate features
        (normalized here by this head's `cand_mean/std`)."""
        s = _sanitize(head_name)
        cm = getattr(self, f"cand_mean__{s}")
        cs = getattr(self, f"cand_std__{s}")
        cand = (cand_rows - cm) / cs
        return self.pointer_heads[s](torch.cat([emb_rows, cand], dim=1))

    def set_pointer_cand_norm(
        self, head_name: str, mean: np.ndarray, std: np.ndarray,
    ) -> None:
        """Set a pointer head's candidate-feature normalization (trainer-fit)."""
        s = _sanitize(head_name)
        eps = np.float32(1e-6)
        std = np.where(np.asarray(std) < eps, np.float32(1.0), std)
        dev = getattr(self, f"cand_mean__{s}").device
        setattr(self, f"cand_mean__{s}",
                torch.tensor(np.asarray(mean, np.float32), device=dev))
        setattr(self, f"cand_std__{s}",
                torch.tensor(np.asarray(std, np.float32), device=dev))

    # ---- Persistence ----

    def config_dict(self) -> dict:
        """Constructor kwargs (sans `norm_stats`) — enough to rebuild the
        architecture. The norm buffers ride in the state_dict."""
        return {
            "input_dim": self.input_dim,
            "trunk_hidden_dims": list(self.trunk_hidden_dims),
            "embedding_dim": self.embedding_dim,
            "value_head_dims": list(self.value_head_dims),
            "outcome_head_dims": list(self.outcome_head_dims),
            "fixed_head_dims": list(self.fixed_head_dims),
            "pointer_head_dims": list(self.pointer_head_dims),
            "fixed_head_specs": dict(self.fixed_head_specs),
            "pointer_head_specs": dict(self.pointer_head_specs),
            "activation": self.activation,
            "norm": self.norm,
            "dropout": self.dropout,
            "embed_norm": self.embed_norm_on,
        }

    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())

    def save(self, path: str | Path, *, extras: dict | None = None) -> None:
        path = Path(path)
        torch.save(self.state_dict(), path.with_suffix(".pt"))
        meta = {
            "model_kind": "shared_trunk",
            "net_type": "SharedTrunkModel",
            "net_config": self.config_dict(),
            "encoding_version": int(self.encoding_version),
            "encoding_tag": str(self.encoding_tag),
            "value_scale": float(self.value_scale),
            "value_target_mode": str(self.value_target_mode),
            "extras": dict(extras) if extras else {},
        }
        with path.with_suffix(".meta.json").open("w") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "SharedTrunkModel":
        path = Path(path)
        with path.with_suffix(".meta.json").open("r") as f:
            meta = json.load(f)
        enc_tag = str(meta.get("encoding_tag", ""))
        if not enc_tag and meta["encoding_version"] != ENCODING_VERSION:
            raise EncodingVersionMismatch(
                f"Checkpoint {path} has encoding_version={meta['encoding_version']}, "
                f"current ENCODING_VERSION={ENCODING_VERSION}."
            )
        cfg = meta["net_config"]
        placeholder = NormStats(
            input_mean=np.zeros(cfg["input_dim"], dtype=np.float32),
            input_std=np.ones(cfg["input_dim"], dtype=np.float32),
            target_std=1.0,
            encoding_version=meta["encoding_version"],
            encoding_tag=enc_tag,
        )
        model = cls(norm_stats=placeholder, **cfg)
        state = torch.load(path.with_suffix(".pt"), weights_only=True)
        # Tolerant load for backward compat: checkpoints trained before the
        # outcome head lack its weights — the ONLY mismatch allowed (the head
        # stays freshly initialized; it's only meaningful once trained). Any
        # other missing/unexpected key is a real error.
        missing, unexpected = model.load_state_dict(state, strict=False)
        missing = [k for k in missing if not k.startswith("outcome_head")]
        if missing or list(unexpected):
            raise RuntimeError(
                f"SharedTrunkModel.load: unexpected state_dict mismatch for {path} "
                f"(missing={missing}, unexpected={list(unexpected)})")
        model.value_scale = float(meta.get("value_scale", 1.0))
        model.value_target_mode = str(meta.get("value_target_mode", "margin"))
        return model


# Register so a generic NET_REGISTRY consumer can resolve the name. (Loading is
# via SharedTrunkModel.load, which is self-contained — the model owns its norm
# buffers rather than being wrapped, since it has many heads, not one output.)
NET_REGISTRY.setdefault("SharedTrunkModel", SharedTrunkModel)
