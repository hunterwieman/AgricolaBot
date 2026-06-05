"""Pointer-head model — a per-candidate scorer + segment-softmax (POLICY_HEAD.md §11).

`NormalizedPointerModel(net, PointerNormStats)` wraps a `ConfigurableMLP`
(`input_dim = ENCODED_DIM + candidate_dim`, `output_dim=1`) that scores a single
`[state ; candidate_delta]` row to a scalar. Two paths share the net:

- **Training** (`score_flat`): a flat batch `(M, candidate_dim)` of candidates with
  a `segment` map (which snapshot each belongs to). The per-candidate state is
  gathered by `state[segment]`, concatenated, normalized, and scored in one pass.
  `segment_log_softmax` then normalizes per snapshot.
- **Inference** (`candidate_probs`): one state + its `(K, candidate_dim)` candidates
  → a length-K probability vector (a single-segment softmax). This is what
  `pointer_prior` calls.

Persistence mirrors `NormalizedPolicyModel` (`<path>.pt` + `<path>.meta.json`,
`model_kind="policy_pointer"`, with `head` + `candidate_dim`), hard-failing on an
`ENCODING_VERSION` mismatch. Imports torch; not re-exported from
`agricola.agents.nn.__init__`.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.agents.nn.model import NET_REGISTRY, EncodingVersionMismatch
from agricola.agents.nn.policy_pointer_dataset import PointerNormStats


def segment_log_softmax(
    scores: torch.Tensor, segment: torch.Tensor, num_segments: int,
) -> torch.Tensor:
    """Log-softmax of `scores` (M,) computed independently within each segment.

    `segment` (M,) maps each row to a segment id in `[0, num_segments)`. Numerically
    stable: subtract the per-segment max (via `scatter_reduce` amax), then normalize
    by the per-segment sum of exponentials (via `index_add_`). Vectorized — no loop
    over segments, no padding.
    """
    seg_max = scores.new_full((num_segments,), float("-inf"))
    seg_max = seg_max.scatter_reduce(0, segment, scores, reduce="amax",
                                     include_self=True)
    shifted = scores - seg_max[segment]
    exp = shifted.exp()
    seg_sum = scores.new_zeros(num_segments).index_add_(0, segment, exp)
    return shifted - seg_sum.log()[segment]


class NormalizedPointerModel(nn.Module):
    """Input-normalized per-candidate scorer for a `PointerHead`."""

    def __init__(self, net: nn.Module, stats: PointerNormStats):
        super().__init__()
        if stats.encoding_version != ENCODING_VERSION:
            raise EncodingVersionMismatch(
                f"PointerNormStats has encoding_version={stats.encoding_version}, "
                f"current ENCODING_VERSION={ENCODING_VERSION}. Regenerate the "
                f"pointer dataset."
            )
        self.net = net
        self.encoding_version = int(stats.encoding_version)
        self.candidate_dim = int(stats.candidate_dim)
        self.state_dim = int(stats.input_dim - stats.candidate_dim)  # == ENCODED_DIM
        self.head_name: str | None = None
        self.register_buffer(
            "input_mean", torch.from_numpy(stats.input_mean.astype(np.float32)).clone())
        self.register_buffer(
            "input_std", torch.from_numpy(stats.input_std.astype(np.float32)).clone())

    def _score_rows(self, x: torch.Tensor) -> torch.Tensor:
        """Score full `[state ; candidate]` rows `(n, input_dim)` → `(n,)`."""
        out = self.net((x - self.input_mean) / self.input_std)
        return out.reshape(-1)            # ConfigurableMLP(output_dim=1) already squeezes

    def score_flat(
        self, state: torch.Tensor, cand: torch.Tensor, segment: torch.Tensor,
    ) -> torch.Tensor:
        """Per-candidate raw scores for a flattened batch.

        `state` `(B, state_dim)`, `cand` `(M, candidate_dim)`, `segment` `(M,)` →
        scores `(M,)`. Each candidate's state row is gathered via `state[segment]`.
        """
        x = torch.cat([state[segment], cand], dim=1)
        return self._score_rows(x)

    def score_candidates(
        self, state_row: torch.Tensor, cand_rows: torch.Tensor,
    ) -> torch.Tensor:
        """Raw scores `(K,)` for ONE state's `(K, candidate_dim)` candidates."""
        k = cand_rows.shape[0]
        st = state_row.reshape(1, -1).expand(k, -1)
        return self._score_rows(torch.cat([st, cand_rows], dim=1))

    def candidate_probs(
        self, state_row: torch.Tensor, cand_rows: torch.Tensor,
    ) -> torch.Tensor:
        """Softmax over ONE state's candidates `(K,)` — the inference prior."""
        if cand_rows.shape[0] == 0:
            return cand_rows.new_zeros(0)
        return torch.softmax(self.score_candidates(state_row, cand_rows), dim=0)

    # ---- Persistence (mirrors NormalizedPolicyModel) ----

    def save(self, path: str | Path, *, extras: dict | None = None) -> None:
        path = Path(path)
        net_type = type(self.net).__name__
        if net_type not in NET_REGISTRY:
            raise ValueError(f"net type {net_type!r} is not in NET_REGISTRY.")
        if not hasattr(self.net, "config_dict"):
            raise ValueError(f"net {net_type!r} must implement config_dict().")
        torch.save(self.state_dict(), path.with_suffix(".pt"))
        meta = {
            "model_kind": "policy_pointer",
            "head": self.head_name,
            "candidate_dim": self.candidate_dim,
            "net_type": net_type,
            "net_config": self.net.config_dict(),
            "encoding_version": int(self.encoding_version),
            "extras": dict(extras) if extras else {},
        }
        with path.with_suffix(".meta.json").open("w") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "NormalizedPointerModel":
        path = Path(path)
        with path.with_suffix(".meta.json").open("r") as f:
            meta = json.load(f)
        if meta["encoding_version"] != ENCODING_VERSION:
            raise EncodingVersionMismatch(
                f"Checkpoint {path} has encoding_version={meta['encoding_version']}, "
                f"current ENCODING_VERSION={ENCODING_VERSION}."
            )
        net_type = meta["net_type"]
        if net_type not in NET_REGISTRY:
            raise ValueError(f"Checkpoint references unknown net_type {net_type!r}.")
        net = NET_REGISTRY[net_type](**meta["net_config"])
        n = meta["net_config"]["input_dim"]
        cand_dim = int(meta["candidate_dim"])
        placeholder = PointerNormStats(
            input_mean=np.zeros(n, dtype=np.float32),
            input_std=np.ones(n, dtype=np.float32),
            candidate_dim=cand_dim,
            encoding_version=meta["encoding_version"],
        )
        model = cls(net, placeholder)
        model.load_state_dict(torch.load(path.with_suffix(".pt"), weights_only=True))
        model.head_name = meta.get("head")
        return model
