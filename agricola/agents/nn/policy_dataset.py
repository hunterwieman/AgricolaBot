"""Dataset for the factored policy heads (behavioral cloning).

Driven by a `DecisionHead` spec (`policy_heads.py`), so the same pipeline builds
the placement head, the ChooseSubAction head, or any future head. Pipeline
(POLICY_HEAD.md §5):

1. Stream `GameRecord` pickles one worker-file at a time (bounds peak memory:
   the extracted rows are tiny vs. the full game collection).
2. For each non-terminal snapshot the head **owns** (`head.owns(state)`) whose
   `chosen_action` maps to one of the head's classes, extract one example —
   **single perspective** (the decider's).
3. Route each example to train/val/test by the game's seed-hash.
4. Fit input normalization (`PolicyNormStats`) on the train split only.
5. For the `awr` variant, compute advantage weights
   `wᵢ = clip(exp((Rᵢ − V_θ(sᵢ)) / β), 0, w_max)` over the train split (`V_θ`
   from a trained value net, reusing the policy input encoding; `β = std(A)`).

Each example is `(x[170], target_class_idx, legal_mask[K], weight, won)` where
`K = head.num_classes`. Imports torch — not re-exported from
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
from agricola.agents.nn.encoder import (
    ENCODED_DIM,
    ENCODED_DIM_CANDIDATE,
    ENCODED_DIM_SPATIAL,
    ENCODING_VERSION,
    encode_state,
)

_VALID_DIMS = frozenset({ENCODED_DIM, ENCODED_DIM_CANDIDATE, ENCODED_DIM_SPATIAL})
from agricola.agents.nn.policy_heads import PLACEMENT_HEAD, DecisionHead
from agricola.agents.nn.schema import GameRecord, load_game_records
from agricola.agents.restricted import restricted_legal_actions
from agricola.constants import SPACE_IDS

# Back-compat alias: the placement head's width. Head-agnostic code uses
# `head.num_classes`.
NUM_SPACES = len(SPACE_IDS)

# Default value checkpoint used as the AWR baseline (the champion pointer).
DEFAULT_VALUE_CKPT = "nn_models/best"


# ---------------------------------------------------------------------------
# Input-normalization stats (input-only — no target normalization)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyNormStats:
    """Per-feature input normalization for a policy head. No `target_std`
    (a classifier's class-index targets aren't normalized). `encoding_version`
    guards against encoder drift, hard-checked when paired with a checkpoint."""

    input_mean: np.ndarray   # (ENCODED_DIM,) float32
    input_std: np.ndarray    # (ENCODED_DIM,) float32, constant-features clamped to 1
    encoding_version: int

    def to_dict(self) -> dict:
        return {
            "input_mean": self.input_mean.tolist(),
            "input_std": self.input_std.tolist(),
            "encoding_version": int(self.encoding_version),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PolicyNormStats":
        return cls(
            input_mean=np.asarray(d["input_mean"], dtype=np.float32),
            input_std=np.asarray(d["input_std"], dtype=np.float32),
            encoding_version=int(d["encoding_version"]),
        )

    def save(self, path: str | Path) -> None:
        with Path(path).open("w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "PolicyNormStats":
        with Path(path).open("r") as f:
            return cls.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# PyTorch dataset
# ---------------------------------------------------------------------------


class AgricolaPolicyDataset(Dataset):
    """Holds extracted policy examples as tensors. `X` may be float16 (upcast
    per item); `mask` bool (width K = head classes); `target` int64 (the
    argmax/played class, kept for top-1/top-3 readouts); `pi` float32 `(N, K)`
    the soft target distribution the loss is computed against (a one-hot on
    `target` for legacy data, normalized MCTS visit counts for self-play data);
    `weight`/`won` float32 (won: 1.0 win / 0.0 loss / −1.0 tie). The DataLoader
    yields `(x, pi, mask, weight)` — the loss is cross-entropy against `pi`."""

    def __init__(self, X, target, mask, weight, won, pi=None):
        assert X.dtype in (np.float16, np.float32, np.int8), X.dtype
        assert X.shape[1] in _VALID_DIMS, X.shape
        assert mask.shape[0] == X.shape[0], (mask.shape, X.shape)
        self._X = torch.from_numpy(X)
        self._target = torch.from_numpy(target.astype(np.int64))
        self._mask = torch.from_numpy(mask)
        self._weight = torch.from_numpy(weight.astype(np.float32))
        self._won = torch.from_numpy(won.astype(np.float32))
        self._x_is_half = X.dtype != np.float32  # compressed (float16/int8) → upcast
        self.num_classes = int(mask.shape[1])
        if pi is None:                       # legacy: one-hot on the played class
            pi = np.zeros((X.shape[0], self.num_classes), dtype=np.float32)
            if X.shape[0]:
                pi[np.arange(X.shape[0]), target.astype(np.int64)] = 1.0
        assert pi.shape == (X.shape[0], self.num_classes), (pi.shape, X.shape)
        self._pi = torch.from_numpy(pi.astype(np.float32))

    def __len__(self) -> int:
        return self._target.shape[0]

    def __getitem__(self, idx):
        x = self._X[idx]
        if self._x_is_half:
            x = x.float()
        return x, self._pi[idx], self._mask[idx], self._weight[idx]


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------


def _pi_vector(head, snap, target, mask, *, soft_targets: bool) -> np.ndarray:
    """The policy target distribution `pi[K]` for a fixed-head example.

    Soft (default, self-play data): normalized MCTS visit counts from
    `snap.visit_distribution`, each action mapped through `head.target_index`
    and summed into its class (so e.g. multiple build-cell actions collapse into
    the `build_stop` `__build__` class). Falls back to a one-hot on the played
    class `target` when the snapshot has no recorded `visit_distribution`
    (legacy/heuristic data) or `soft_targets` is False — making hard behavioral
    cloning the degenerate case of the same cross-entropy loss.

    Raises if any mass lands on a class illegal under `mask`: the masked-softmax
    loss would put −inf there, so π's support must be ⊆ the training legality.
    (MCTS only visits legal actions, so this fires only on a legality MISMATCH —
    e.g. training a head with `restricted` legality on data generated with
    `full`. Train such heads with matching, full legality.)"""
    k = head.num_classes
    vd = snap.visit_distribution
    if not soft_targets or vd is None:
        pi = np.zeros(k, dtype=np.float32)
        pi[target] = 1.0
        return pi
    pi = np.zeros(k, dtype=np.float32)
    total = 0.0
    for action, count in vd.items():
        idx = head.target_index(action)
        if idx is None:                      # action outside this head's vocab
            continue                         # (a pruned class, e.g. bake grain>6)
        pi[idx] += float(count)
        total += float(count)
    if total <= 0.0:                         # nothing mapped in — one-hot fallback
        pi[target] = 1.0
        return pi
    pi /= total
    illegal_mass = float(pi[~mask].sum())
    if illegal_mass > 1e-6:
        raise ValueError(
            f"head '{head.name}': visit distribution puts {illegal_mass:.3f} "
            f"probability on classes illegal under the training legality — the "
            f"data was generated under a wider legality than the head is trained "
            f"with. Train this head with matching (full) legality."
        )
    return pi


def _decision_rows(
    games: Iterable[GameRecord],
    head: DecisionHead,
    legal_actions_fn=restricted_legal_actions,
    *,
    soft_targets: bool = True,
) -> Iterator[tuple]:
    """Yield `(game_seed, x_f32, target_idx, legal_mask, R_decider, won, pi)` for
    every non-terminal snapshot the `head` owns whose chosen action is one of
    the head's classes. `x` is the decider-perspective encoding; `target` the
    played class (for top-k readouts); `pi[K]` the soft target distribution the
    loss uses (see `_pi_vector`); `R_decider` the decider-frame terminal margin;
    `won` the decider's outcome (1/0/−1). Raises if the chosen class isn't in its
    own legal mask (the §5 invariant)."""
    for g in games:
        for snap in g.decisions:
            state = snap.state
            if not head.owns(state):
                continue
            target = head.target_index(snap.chosen_action)
            if target is None:
                continue
            d = snap.decider_idx
            x = encode_state(state, d).astype(np.float32)
            mask = head.legal_mask(state, legal_actions_fn)
            if not mask[target]:
                raise ValueError(
                    f"chosen class {target} ({head.name}) not in its own legal "
                    f"mask for game seed={g.seed} — encoder/legality drift."
                )
            pi = _pi_vector(head, snap, target, mask, soft_targets=soft_targets)
            R = float(g.p0_final_score - g.p1_final_score) if d == 0 \
                else float(g.p1_final_score - g.p0_final_score)
            if g.winner is None:
                won = -1.0
            elif g.winner == d:
                won = 1.0
            else:
                won = 0.0
            yield g.seed, x, target, mask, R, won, pi


class _SplitAccumulator:
    """Collects extracted rows, routing each to its seed-hash split bucket."""

    def __init__(self, head, split_seed, train_frac, val_frac, soft_targets=True):
        self.head = head
        self.split_seed = split_seed
        self.train_frac = train_frac
        self.val_frac = val_frac
        self.soft_targets = soft_targets
        self._split_of_seed: dict[int, int] = {}
        self.x = ([], [], [])
        self.t = ([], [], [])
        self.m = ([], [], [])
        self.R = ([], [], [])
        self.won = ([], [], [])
        self.pi = ([], [], [])

    def add_games(self, games, legal_actions_fn) -> None:
        for seed, x, t, m, R, won, pi in _decision_rows(
            games, self.head, legal_actions_fn, soft_targets=self.soft_targets,
        ):
            sp = self._split_of_seed.get(seed)
            if sp is None:
                sp = _seed_split(seed, self.split_seed, self.train_frac, self.val_frac)
                self._split_of_seed[seed] = sp
            self.x[sp].append(x)
            self.t[sp].append(t)
            self.m[sp].append(m)
            self.R[sp].append(R)
            self.won[sp].append(won)
            self.pi[sp].append(pi)

    def arrays(self, sp: int):
        k = self.head.num_classes
        n = len(self.t[sp])
        if n == 0:
            return (np.zeros((0, ENCODED_DIM), np.float32), np.zeros(0, np.int64),
                    np.zeros((0, k), bool), np.zeros(0, np.float32),
                    np.zeros(0, np.float32), np.zeros((0, k), np.float32))
        return (np.asarray(self.x[sp], dtype=np.float32),
                np.asarray(self.t[sp], dtype=np.int64),
                np.asarray(self.m[sp], dtype=bool),
                np.asarray(self.R[sp], dtype=np.float32),
                np.asarray(self.won[sp], dtype=np.float32),
                np.asarray(self.pi[sp], dtype=np.float32))


# ---------------------------------------------------------------------------
# Norm + AWR weights
# ---------------------------------------------------------------------------


def _fit_policy_norm(X_train: np.ndarray) -> PolicyNormStats:
    eps = np.float32(1e-6)
    mean = X_train.mean(axis=0, dtype=np.float64).astype(np.float32)
    std = X_train.std(axis=0, dtype=np.float64).astype(np.float32)
    std = np.where(std < eps, np.float32(1.0), std)
    return PolicyNormStats(input_mean=mean, input_std=std,
                           encoding_version=ENCODING_VERSION)


def _compute_awr_weights(
    X_train: np.ndarray, R_train: np.ndarray, value_ckpt: str | Path,
    w_max: float, batch: int = 8192,
) -> tuple[np.ndarray, float]:
    """AWR weights `clip(exp((R − V)/β), 0, w_max)`. `V` is the value net's
    single-perspective margin on the policy input encoding; `β = std(A)`."""
    from agricola.agents.nn.model import load_value_evaluator

    # model_kind-aware: a separate-net NormalizedValueModel OR a joint
    # SharedTrunkModel (its value head satisfies the same predict_margin
    # contract). `load_value_evaluator` returns an eval()'d model either way.
    vmodel = load_value_evaluator(Path(value_ckpt))
    # Guard the unit mismatch: AWR's advantage A = R - V is only meaningful if
    # R and V share units. R is the terminal SCORE MARGIN in points (tens); V =
    # vmodel.predict_margin(...) is in the value net's target units. Only a
    # MARGIN-mode (linear-head) net returns points — for an outcome (tanh) or
    # winprob (sigmoid) head predict_margin is bounded (~[-1,1] / [0,1], and
    # target_std is forced to 1.0), so V is negligible against R and the
    # advantage silently degenerates to ~|R| (up-weighting blowout games instead
    # of surprising decisions). The head is the reliable, load-reconstructed
    # signal — for a separate net it's `net.head`; for the joint model it's the
    # value head's `head` (`value_head.head`).
    value_net = getattr(vmodel, "net", None) or getattr(vmodel, "value_head", None)
    head = getattr(value_net, "head", None)
    if head != "linear":
        mode = {"tanh": "outcome", "sigmoid": "winprob"}.get(head, f"head={head!r}")
        raise ValueError(
            f"AWR value baseline {value_ckpt} is not margin-mode (net head "
            f"{head!r} -> target_mode '{mode}'): predict_margin returns "
            f"non-point units there, so the advantage A = R - V mixes scales "
            f"(R is the score margin in points). Pass a margin-mode (linear-head) "
            f"value checkpoint for AWR weighting."
        )
    n = X_train.shape[0]
    V = np.empty(n, dtype=np.float32)
    Xt = torch.from_numpy(X_train.astype(np.float32))
    with torch.no_grad():
        for s in range(0, n, batch):
            V[s:s + batch] = vmodel.predict_margin(Xt[s:s + batch]).cpu().numpy()
    A = R_train - V
    beta = float(A.std())
    if not np.isfinite(beta) or beta < 1e-9:
        beta = 1.0
    w = np.clip(np.exp(A / beta), 0.0, w_max).astype(np.float32)
    return w, beta


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def _finalize(acc, *, loss_weight, value_ckpt, awr_clip, store_dtype, verbose):
    Xtr, ttr, mtr, Rtr, wontr, pitr = acc.arrays(0)
    Xva, tva, mva, _, wonva, piva = acc.arrays(1)
    Xte, tte, mte, _, wonte, pite = acc.arrays(2)
    if Xtr.shape[0] == 0:
        raise ValueError(
            f"policy build produced no training examples for head "
            f"'{acc.head.name}'.")

    stats = _fit_policy_norm(Xtr)

    if loss_weight == "awr":
        wtr, beta = _compute_awr_weights(Xtr, Rtr, value_ckpt, awr_clip)
    elif loss_weight == "unweighted":
        wtr, beta = np.ones(Xtr.shape[0], np.float32), None
    else:
        raise ValueError(f"loss_weight must be 'unweighted' or 'awr'; got {loss_weight!r}")

    dt = np.float16 if store_dtype == "float16" else np.float32
    train_ds = AgricolaPolicyDataset(Xtr.astype(dt), ttr, mtr, wtr, wontr, pitr)
    val_ds = AgricolaPolicyDataset(Xva.astype(dt), tva, mva,
                                   np.ones(Xva.shape[0], np.float32), wonva, piva)
    test_ds = AgricolaPolicyDataset(Xte.astype(dt), tte, mte,
                                    np.ones(Xte.shape[0], np.float32), wonte, pite)

    info = {
        "head": acc.head.name,
        "num_classes": acc.head.num_classes,
        "soft_targets": bool(acc.soft_targets),
        "loss_weight": loss_weight,
        "awr_beta": beta,
        "awr_clip": float(awr_clip) if loss_weight == "awr" else None,
        "value_ckpt": str(value_ckpt) if loss_weight == "awr" else None,
        "n_train": int(Xtr.shape[0]),
        "n_val": int(Xva.shape[0]),
        "n_test": int(Xte.shape[0]),
    }
    if verbose:
        print(f"Policy build [{acc.head.name}]: train={info['n_train']} "
              f"val={info['n_val']} test={info['n_test']} | loss_weight={loss_weight}"
              + (f" | β={beta:.3f} clip={awr_clip}" if loss_weight == "awr" else ""))
    return train_ds, val_ds, test_ds, stats, info


def build_policy_datasets_from_games(
    games: list[GameRecord], *,
    head: DecisionHead = PLACEMENT_HEAD,
    loss_weight: str = "unweighted",
    value_ckpt: str | Path = DEFAULT_VALUE_CKPT,
    awr_clip: float = 6.0,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    store_dtype: str = "float32",
    legal_actions_fn=restricted_legal_actions,
    soft_targets: bool = True,
    verbose: bool = True,
):
    """Build (train, val, test) datasets + `PolicyNormStats` + info dict for a
    `head` from an in-memory game list (used by tests). `soft_targets` (default)
    trains against the MCTS visit distribution π when present, else one-hot."""
    acc = _SplitAccumulator(head, split_seed, train_frac, val_frac, soft_targets)
    acc.add_games(games, legal_actions_fn)
    return _finalize(acc, loss_weight=loss_weight, value_ckpt=value_ckpt,
                     awr_clip=awr_clip, store_dtype=store_dtype, verbose=verbose)


def build_policy_datasets(
    run_dirs: Sequence[Path] | Path | str, *,
    head: DecisionHead = PLACEMENT_HEAD,
    loss_weight: str = "unweighted",
    value_ckpt: str | Path = DEFAULT_VALUE_CKPT,
    awr_clip: float = 6.0,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    store_dtype: str = "float16",
    legal_actions_fn=restricted_legal_actions,
    soft_targets: bool = True,
    verbose: bool = True,
):
    """Build policy datasets for a `head` from on-disk run dirs, **streaming**
    one worker pickle at a time (the full collection is never held in RAM).
    Game count comes from the pickles, not `metadata.json` (POLICY_HEAD.md §5).
    `soft_targets` (default) trains against the MCTS visit distribution π when
    present, else one-hot behavioral cloning."""
    if isinstance(run_dirs, (str, Path)):
        run_dirs = [Path(run_dirs)]
    else:
        run_dirs = [Path(r) for r in run_dirs]

    acc = _SplitAccumulator(head, split_seed, train_frac, val_frac, soft_targets)
    n_games = 0
    for pkl in _iter_worker_pickles(run_dirs):
        games = load_game_records(pkl)
        n_games += len(games)
        acc.add_games(games, legal_actions_fn)
        del games
        if verbose:
            print(f"  extracted {pkl.parent.parent.name}/{pkl.name} "
                  f"(games so far={n_games})", flush=True)
    if verbose:
        print(f"Loaded {n_games} games from {len(run_dirs)} run(s)")
    return _finalize(acc, loss_weight=loss_weight, value_ckpt=value_ckpt,
                     awr_clip=awr_clip, store_dtype=store_dtype, verbose=verbose)
