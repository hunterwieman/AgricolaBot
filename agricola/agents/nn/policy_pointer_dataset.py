"""Pointer-head dataset — behavioral cloning over variable-cardinality frontiers.

Score-the-legal-set heads (`PointerHead`, POLICY_HEAD.md §11) don't classify into
a fixed vocabulary: the legal set is a different, state-dependent list of frontier
points each call (CommitBreed / CommitAccommodate). So each training example is a
snapshot's *list* of legal candidates + the position of the chosen one. The lists
are ragged (length K varies), so a batch is flattened into one `(ΣK, ·)` tensor
plus `segment_id` (which snapshot each candidate belongs to) and `chosen_flat`
(the flat index of each snapshot's chosen candidate); the model scores all ΣK
candidates in one pass and a segment-softmax normalizes per snapshot — no padding.

Each candidate's feature row is the head's small action-delta (e.g.
`(sheep_kept, boar_kept, cattle_kept, food_gained)`); the decision context
(current supply / animals / capacity / food need) rides in the **shared state
encoding** the model concatenates onto every candidate row. So the model input
per candidate is `[state(170) ; candidate_delta(candidate_dim)]`.

Reuses the value/fixed-policy infra: the by-game `_seed_split`, the worker-pickle
streaming, and `_compute_awr_weights` (AWR is a per-snapshot weight on `V_θ(s)` —
identical to the fixed heads). Imports torch; not re-exported from
`agricola.agents.nn.__init__`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

import numpy as np
import torch
from torch.utils.data import Dataset

from agricola.agents.nn.dataset import _iter_worker_pickles, _seed_split
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION, encode_state
from agricola.agents.nn.policy_dataset import (
    DEFAULT_VALUE_CKPT,
    _compute_awr_weights,
)
from agricola.agents.nn.policy_heads import ANIMAL_FRONTIER_HEAD, PointerHead
from agricola.agents.nn.schema import GameRecord, load_game_records


# ---------------------------------------------------------------------------
# Input-normalization stats (over the concatenated [state ; candidate] row)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PointerNormStats:
    """Per-feature input normalization for a pointer head. The normalized input
    is the full per-candidate row `[state(ENCODED_DIM) ; candidate(candidate_dim)]`,
    so `input_mean`/`input_std` have length `ENCODED_DIM + candidate_dim`."""

    input_mean: np.ndarray   # (ENCODED_DIM + candidate_dim,) float32
    input_std: np.ndarray    # (ENCODED_DIM + candidate_dim,) float32
    candidate_dim: int
    encoding_version: int

    @property
    def input_dim(self) -> int:
        return int(self.input_mean.shape[0])

    def to_dict(self) -> dict:
        return {
            "input_mean": self.input_mean.tolist(),
            "input_std": self.input_std.tolist(),
            "candidate_dim": int(self.candidate_dim),
            "encoding_version": int(self.encoding_version),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PointerNormStats":
        return cls(
            input_mean=np.asarray(d["input_mean"], dtype=np.float32),
            input_std=np.asarray(d["input_std"], dtype=np.float32),
            candidate_dim=int(d["candidate_dim"]),
            encoding_version=int(d["encoding_version"]),
        )

    def save(self, path: str | Path) -> None:
        with Path(path).open("w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "PointerNormStats":
        with Path(path).open("r") as f:
            return cls.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# PyTorch dataset (ragged) + segment collate
# ---------------------------------------------------------------------------


class AgricolaPointerDataset(Dataset):
    """Ragged per-snapshot examples. `state` is stored once per snapshot (NOT
    repeated per candidate); `cand` is a flat `(ΣK, candidate_dim)` array sliced
    by `offsets`. `__getitem__` returns one snapshot; batch with `pointer_collate`."""

    def __init__(self, state, cand_flat, offsets, chosen_pos, weight, won):
        assert state.shape[1] == ENCODED_DIM, state.shape
        self._state = torch.from_numpy(state.astype(np.float32))
        self._cand = torch.from_numpy(cand_flat.astype(np.float32))
        self._off = np.asarray(offsets, dtype=np.int64)        # (N+1,)
        self._pos = np.asarray(chosen_pos, dtype=np.int64)     # (N,)
        self._weight = torch.from_numpy(weight.astype(np.float32))
        self._won = torch.from_numpy(won.astype(np.float32))
        self.candidate_dim = int(cand_flat.shape[1]) if cand_flat.size else 0

    def __len__(self) -> int:
        return self._state.shape[0]

    def __getitem__(self, idx):
        a, b = int(self._off[idx]), int(self._off[idx + 1])
        return (self._state[idx], self._cand[a:b],
                int(self._pos[idx]), self._weight[idx])


def pointer_collate(batch):
    """Flatten a list of snapshots into the segment layout.

    Returns `(state, cand, segment, chosen_flat, weight)`:
      - `state`       `(B, ENCODED_DIM)` — one row per snapshot
      - `cand`        `(M, candidate_dim)` — all candidates, snapshot-contiguous
      - `segment`     `(M,)` long — which snapshot (0..B-1) each candidate is in
      - `chosen_flat` `(B,)` long — flat index of each snapshot's chosen candidate
      - `weight`      `(B,)` float — per-snapshot loss weight
    """
    states, cand_blocks, segs, chosen_flat, weights = [], [], [], [], []
    offset = 0
    for i, (st, cd, pos, w) in enumerate(batch):
        k = cd.shape[0]
        states.append(st)
        cand_blocks.append(cd)
        segs.append(torch.full((k,), i, dtype=torch.long))
        chosen_flat.append(offset + pos)
        weights.append(w)
        offset += k
    return (
        torch.stack(states),
        torch.cat(cand_blocks, dim=0),
        torch.cat(segs, dim=0),
        torch.tensor(chosen_flat, dtype=torch.long),
        torch.stack(weights).float(),
    )


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _pointer_rows(games: Iterable[GameRecord], head: PointerHead) -> Iterator[tuple]:
    """Yield `(game_seed, state_enc[170], cand[K, dim], chosen_pos, R, won)` for
    every non-terminal snapshot the `head` owns with ≥2 candidates. `state_enc`
    is the decider-perspective encoding; `chosen_pos` the chosen candidate's
    index. Raises if the chosen action isn't among the head's candidates (drift)."""
    for g in games:
        for snap in g.decisions:
            state = snap.state
            if not head.owns(state):
                continue
            pairs = head.enumerate_candidates(state)
            if len(pairs) < 2:           # singleton: not a real decision
                continue
            pos = head.target_position(state, snap.chosen_action)
            if pos is None:
                raise ValueError(
                    f"chosen action {snap.chosen_action} not among '{head.name}' "
                    f"candidates for game seed={g.seed} — frontier/engine drift."
                )
            d = snap.decider_idx
            state_enc = encode_state(state, d).astype(np.float32)
            cand = np.stack([f for _, f in pairs]).astype(np.float32)
            R = float(g.p0_final_score - g.p1_final_score) if d == 0 \
                else float(g.p1_final_score - g.p0_final_score)
            if g.winner is None:
                won = -1.0
            elif g.winner == d:
                won = 1.0
            else:
                won = 0.0
            yield g.seed, state_enc, cand, pos, R, won


class _PointerSplitAccumulator:
    """Collects pointer rows, routing each to its seed-hash split bucket."""

    def __init__(self, head, split_seed, train_frac, val_frac):
        self.head = head
        self.split_seed = split_seed
        self.train_frac = train_frac
        self.val_frac = val_frac
        self._split_of_seed: dict[int, int] = {}
        self.state = ([], [], [])
        self.cand = ([], [], [])
        self.pos = ([], [], [])
        self.R = ([], [], [])
        self.won = ([], [], [])

    def add_games(self, games) -> None:
        for seed, st, cd, pos, R, won in _pointer_rows(games, self.head):
            sp = self._split_of_seed.get(seed)
            if sp is None:
                sp = _seed_split(seed, self.split_seed, self.train_frac, self.val_frac)
                self._split_of_seed[seed] = sp
            self.state[sp].append(st)
            self.cand[sp].append(cd)
            self.pos[sp].append(pos)
            self.R[sp].append(R)
            self.won[sp].append(won)

    def arrays(self, sp: int):
        """Return (state[N,170], cand_flat[M,dim], offsets[N+1], pos[N], R[N], won[N])."""
        dim = self.head.candidate_dim
        n = len(self.pos[sp])
        if n == 0:
            return (np.zeros((0, ENCODED_DIM), np.float32),
                    np.zeros((0, dim), np.float32), np.zeros(1, np.int64),
                    np.zeros(0, np.int64), np.zeros(0, np.float32),
                    np.zeros(0, np.float32))
        state = np.asarray(self.state[sp], dtype=np.float32)
        counts = np.array([c.shape[0] for c in self.cand[sp]], dtype=np.int64)
        offsets = np.concatenate([[0], np.cumsum(counts)]).astype(np.int64)
        cand_flat = np.concatenate(self.cand[sp], axis=0).astype(np.float32)
        return (state, cand_flat, offsets,
                np.asarray(self.pos[sp], dtype=np.int64),
                np.asarray(self.R[sp], dtype=np.float32),
                np.asarray(self.won[sp], dtype=np.float32))


# ---------------------------------------------------------------------------
# Norm + build
# ---------------------------------------------------------------------------


def _segments_from_offsets(offsets: np.ndarray) -> np.ndarray:
    """`offsets[N+1]` → `segment[M]` mapping each candidate to its snapshot index."""
    counts = np.diff(offsets)
    return np.repeat(np.arange(len(counts)), counts)


def _fit_pointer_norm(state, cand_flat, offsets, candidate_dim) -> PointerNormStats:
    eps = np.float32(1e-6)
    seg = _segments_from_offsets(offsets)
    X = np.concatenate([state[seg], cand_flat], axis=1)  # (M, ENCODED_DIM+dim)
    mean = X.mean(axis=0, dtype=np.float64).astype(np.float32)
    std = X.std(axis=0, dtype=np.float64).astype(np.float32)
    std = np.where(std < eps, np.float32(1.0), std)
    return PointerNormStats(input_mean=mean, input_std=std,
                            candidate_dim=int(candidate_dim),
                            encoding_version=ENCODING_VERSION)


def _finalize(acc, *, loss_weight, value_ckpt, awr_clip, verbose):
    Str, Ctr, Otr, ptr, Rtr, wontr = acc.arrays(0)
    Sva, Cva, Ova, pva, _, wonva = acc.arrays(1)
    Ste, Cte, Ote, pte, _, wonte = acc.arrays(2)
    if Str.shape[0] == 0:
        raise ValueError(
            f"pointer build produced no training examples for head "
            f"'{acc.head.name}'.")

    stats = _fit_pointer_norm(Str, Ctr, Otr, acc.head.candidate_dim)

    if loss_weight == "awr":
        wtr, beta = _compute_awr_weights(Str, Rtr, value_ckpt, awr_clip)
    elif loss_weight == "unweighted":
        wtr, beta = np.ones(Str.shape[0], np.float32), None
    else:
        raise ValueError(f"loss_weight must be 'unweighted' or 'awr'; got {loss_weight!r}")

    train_ds = AgricolaPointerDataset(Str, Ctr, Otr, ptr, wtr, wontr)
    val_ds = AgricolaPointerDataset(Sva, Cva, Ova, pva,
                                    np.ones(Sva.shape[0], np.float32), wonva)
    test_ds = AgricolaPointerDataset(Ste, Cte, Ote, pte,
                                     np.ones(Ste.shape[0], np.float32), wonte)

    info = {
        "head": acc.head.name,
        "candidate_dim": acc.head.candidate_dim,
        "loss_weight": loss_weight,
        "awr_beta": beta,
        "awr_clip": float(awr_clip) if loss_weight == "awr" else None,
        "value_ckpt": str(value_ckpt) if loss_weight == "awr" else None,
        "n_train": int(Str.shape[0]),
        "n_val": int(Sva.shape[0]),
        "n_test": int(Ste.shape[0]),
        "candidates_train": int(Ctr.shape[0]),
    }
    if verbose:
        print(f"Pointer build [{acc.head.name}]: train={info['n_train']} "
              f"val={info['n_val']} test={info['n_test']} "
              f"(train candidates={info['candidates_train']}) | loss_weight={loss_weight}"
              + (f" | β={beta:.3f} clip={awr_clip}" if loss_weight == "awr" else ""))
    return train_ds, val_ds, test_ds, stats, info


def build_pointer_datasets_from_games(
    games: list[GameRecord], *,
    head: PointerHead = ANIMAL_FRONTIER_HEAD,
    loss_weight: str = "unweighted",
    value_ckpt: str | Path = DEFAULT_VALUE_CKPT,
    awr_clip: float = 6.0,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    verbose: bool = True,
):
    """Build (train, val, test) datasets + `PointerNormStats` + info for a pointer
    `head` from an in-memory game list (used by tests)."""
    acc = _PointerSplitAccumulator(head, split_seed, train_frac, val_frac)
    acc.add_games(games)
    return _finalize(acc, loss_weight=loss_weight, value_ckpt=value_ckpt,
                     awr_clip=awr_clip, verbose=verbose)


def build_pointer_datasets(
    run_dirs: Sequence[Path] | Path | str, *,
    head: PointerHead = ANIMAL_FRONTIER_HEAD,
    loss_weight: str = "unweighted",
    value_ckpt: str | Path = DEFAULT_VALUE_CKPT,
    awr_clip: float = 6.0,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    verbose: bool = True,
):
    """Build pointer datasets for a `head` from on-disk run dirs, **streaming**
    one worker pickle at a time."""
    if isinstance(run_dirs, (str, Path)):
        run_dirs = [Path(run_dirs)]
    else:
        run_dirs = [Path(r) for r in run_dirs]

    acc = _PointerSplitAccumulator(head, split_seed, train_frac, val_frac)
    n_games = 0
    for pkl in _iter_worker_pickles(run_dirs):
        games = load_game_records(pkl)
        n_games += len(games)
        acc.add_games(games)
        del games
        if verbose:
            print(f"  extracted {pkl.parent.parent.name}/{pkl.name} "
                  f"(games so far={n_games})", flush=True)
    if verbose:
        print(f"Loaded {n_games} games from {len(run_dirs)} run(s)")
    return _finalize(acc, loss_weight=loss_weight, value_ckpt=value_ckpt,
                     awr_clip=awr_clip, verbose=verbose)
