"""Dataset for NN value-function training.

Pipeline (FIRST_NN.md §6/§8):

1. Load `GameRecord` pickles from one or more generation runs.
2. By-game train/val/test split (avoid leakage — same game never appears
   in two splits).
3. Expand each game into training-example *descriptors*:
   - per non-singleton decision snapshot: 2 descriptors (both
     perspectives — the "A" dual-perspective augmentation from §8)
   - per game terminal state: 2 descriptors (§5.1)
4. For TRAIN: optionally sub-sample to bound dataset size. Sampling
   happens at the STATE level (uniform random over `(game, snap-or-
   terminal)` keys) and then each chosen state expands to BOTH
   perspectives — i.e., dual-perspective pairs stay together, matching
   §8's "for each snapshot, train on both" intent. `train_sample_size`
   is interpreted as a target *example* count (rounded down to the
   nearest even). VAL/TEST use all descriptors for low-variance metrics.
5. Pre-encode the chosen descriptors *once* into a dense float32 array
   so DataLoader access is array indexing — the per-call cost of
   `encode_state` (microseconds) doesn't pay every epoch.
6. Compute `NormStats` from the training arrays: per-feature input
   mean/std + target stdev. Targets are normalized here (divided by
   target_std); features stay RAW (the model normalizes inputs
   internally via a fixed buffer-based first layer, per FIRST_NN.md §4
   — keeps inference correct without consumers remembering to apply it).
7. Return `(train_ds, val_ds, test_ds, norm_stats)`.

`NormStats` is persisted alongside the trained model so inference can
reconstruct the same normalization. The `encoding_version` field guards
against encoder drift (FIRST_NN.md §11.4).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
import torch
from torch.utils.data import Dataset

from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION, encode_state
from agricola.agents.nn.schema import GameRecord, load_game_records


# ---------------------------------------------------------------------------
# NormStats — persisted alongside the model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NormStats:
    """Per-feature input normalization + target normalization, computed
    once from the training split. Persist with the model so inference
    reconstructs the same transform.

    `input_std` and `target_std` are clamped to `>= eps` for the
    division-safe case where a feature is constant in the training
    split (e.g., a major never built across all training games). The
    corresponding feature value after `(x - mean) / std` is then 0,
    which is correct (the feature carries no info in this dataset).

    `encoding_version` is checked when the stats are paired with a
    model checkpoint — bumping `ENCODING_VERSION` invalidates older
    stats since the feature ordering / count may have shifted.
    """

    input_mean: np.ndarray   # shape (ENCODED_DIM,), float32
    input_std: np.ndarray    # shape (ENCODED_DIM,), float32
    target_std: float
    encoding_version: int

    def to_dict(self) -> dict:
        return {
            "input_mean": self.input_mean.tolist(),
            "input_std": self.input_std.tolist(),
            "target_std": float(self.target_std),
            "encoding_version": int(self.encoding_version),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NormStats":
        return cls(
            input_mean=np.asarray(d["input_mean"], dtype=np.float32),
            input_std=np.asarray(d["input_std"], dtype=np.float32),
            target_std=float(d["target_std"]),
            encoding_version=int(d["encoding_version"]),
        )

    def save(self, path: str | Path) -> None:
        with Path(path).open("w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "NormStats":
        with Path(path).open("r") as f:
            return cls.from_dict(json.load(f))


# ---------------------------------------------------------------------------
# Example descriptors (lightweight — encoded in bulk later)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ExampleDescriptor:
    """One training example, identified by `(game, which-state, perspective)`.

    Held as a lightweight descriptor (16 bytes) so we can sample and
    permute millions cheaply, then encode the chosen subset into a
    dense array in one bulk pass.
    """

    game_idx_in_list: int    # index into the games list passed to encoding
    is_terminal: bool        # True → encode game.terminal_state
    snap_idx: int            # only meaningful if not is_terminal; -1 otherwise
    perspective: int         # 0 or 1


def _enumerate_state_keys(games: list[GameRecord]) -> list[tuple[int, bool, int]]:
    """One `(game_idx, is_terminal, snap_idx)` per training STATE
    (i.e., before the perspective expansion). `snap_idx == -1` for
    terminal states. Used by the train sampling path to sample at the
    state level so dual-perspective pairs stay together.
    """
    out: list[tuple[int, bool, int]] = []
    for gi, game in enumerate(games):
        for si in range(len(game.decisions)):
            out.append((gi, False, si))
        out.append((gi, True, -1))
    return out


def _expand_keys_to_descriptors(
    keys: list[tuple[int, bool, int]],
) -> list[_ExampleDescriptor]:
    """Each state-key → 2 descriptors (both perspectives). Pairs are
    adjacent in the output (perspective 0 immediately followed by
    perspective 1 for the same state)."""
    out: list[_ExampleDescriptor] = []
    for gi, is_terminal, si in keys:
        out.append(_ExampleDescriptor(gi, is_terminal, si, 0))
        out.append(_ExampleDescriptor(gi, is_terminal, si, 1))
    return out


def _expand_to_descriptors(games: list[GameRecord]) -> list[_ExampleDescriptor]:
    """All descriptors for `games` (both perspectives of every state +
    every terminal). Used by val/test (no sampling) and by tests."""
    return _expand_keys_to_descriptors(_enumerate_state_keys(games))


def _encode_one(desc: _ExampleDescriptor, games: list[GameRecord]) -> tuple[np.ndarray, float]:
    """Encode one descriptor → (features, raw_target_margin).

    Target is the perspective-frame margin: `score(perspective) − score(other)`.
    Raw (not yet normalized by target_std).
    """
    game = games[desc.game_idx_in_list]
    state = game.terminal_state if desc.is_terminal else game.decisions[desc.snap_idx].state
    features = encode_state(state, desc.perspective)
    if desc.perspective == 0:
        target = float(game.p0_final_score - game.p1_final_score)
    else:
        target = float(game.p1_final_score - game.p0_final_score)
    return features, target


def _encode_descriptors(
    descriptors: list[_ExampleDescriptor], games: list[GameRecord],
) -> tuple[np.ndarray, np.ndarray]:
    """Bulk-encode all descriptors into `(X, y_raw)` numpy arrays.

    `X.shape == (n, ENCODED_DIM)`, `y_raw.shape == (n,)`, both float32.
    `y_raw` is unnormalized margins (in original score-point units).
    """
    n = len(descriptors)
    X = np.zeros((n, ENCODED_DIM), dtype=np.float32)
    y = np.zeros(n, dtype=np.float32)
    for i, desc in enumerate(descriptors):
        feats, target = _encode_one(desc, games)
        X[i] = feats
        y[i] = target
    return X, y


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------


def _compute_norm_stats(X_train: np.ndarray, y_train_raw: np.ndarray) -> NormStats:
    """Compute per-feature input mean/std + target std on the TRAIN
    split only (never peek at val/test). Constant features get
    `std = 1` (so `(x - mean) / 1 == 0` for them — division-safe and
    the feature carries no signal in this dataset)."""
    eps = np.float32(1e-6)
    input_mean = X_train.mean(axis=0).astype(np.float32)
    input_std = X_train.std(axis=0).astype(np.float32)
    input_std = np.where(input_std < eps, np.float32(1.0), input_std)
    target_std = float(y_train_raw.std())
    if target_std < eps:
        # Pathological: all training games tied. Use 1 to avoid div-by-zero.
        target_std = 1.0
    return NormStats(
        input_mean=input_mean,
        input_std=input_std,
        target_std=target_std,
        encoding_version=ENCODING_VERSION,
    )


# ---------------------------------------------------------------------------
# PyTorch Dataset
# ---------------------------------------------------------------------------


class AgricolaValueDataset(Dataset):
    """Holds the pre-encoded `(X, y_normalized)` arrays and exposes them
    as a PyTorch Dataset.

    - Features (`X`) are **raw** — the model normalizes inputs internally
      via a fixed buffer-based first layer constructed from `NormStats`.
    - Targets (`y`) are **normalized** (divided by training-set
      `target_std`). The model outputs in normalized space during
      training; multiply by `target_std` at inference to get margin
      units back.
    """

    def __init__(self, X: np.ndarray, y_normalized: np.ndarray):
        assert X.dtype == np.float32, f"X dtype is {X.dtype}, expected float32"
        assert y_normalized.dtype == np.float32, (
            f"y dtype is {y_normalized.dtype}, expected float32"
        )
        assert X.shape[0] == y_normalized.shape[0], (
            f"X has {X.shape[0]} rows but y has {y_normalized.shape[0]}"
        )
        assert X.shape[1] == ENCODED_DIM, (
            f"X has {X.shape[1]} feature columns, expected {ENCODED_DIM}"
        )
        # Convert to torch tensors once at construction. `from_numpy`
        # shares the underlying buffer (zero-copy); cheap.
        self._X = torch.from_numpy(X)
        self._y = torch.from_numpy(y_normalized)

    def __len__(self) -> int:
        return self._y.shape[0]

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        return self._X[idx], self._y[idx]


# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def load_all_games_from_runs(run_dirs: Sequence[Path]) -> list[GameRecord]:
    """Load all GameRecords from each run dir's `games/worker_*.pkl`
    files. Order is stable across reruns (sorted by run dir, then by
    pickle path), so the by-game split is deterministic per seed.

    `load_game_records` enforces `DATA_VERSION` at load — a stale
    pickle raises immediately rather than silently mismatching.
    """
    games: list[GameRecord] = []
    for run_dir in run_dirs:
        games_dir = Path(run_dir) / "games"
        if not games_dir.is_dir():
            raise FileNotFoundError(
                f"{run_dir} has no 'games/' subdirectory — not a run directory?"
            )
        for pkl in sorted(games_dir.glob("worker_*.pkl")):
            games.extend(load_game_records(pkl))
    return games


def _split_games_by_index(
    n_games: int, train_frac: float, val_frac: float, seed: int,
) -> tuple[list[int], list[int], list[int]]:
    """Deterministic random by-game split. Returns sorted index lists
    for (train, val, test)."""
    assert 0.0 < train_frac < 1.0
    assert 0.0 <= val_frac < 1.0
    assert train_frac + val_frac < 1.0, (
        f"train_frac + val_frac must be < 1 (got {train_frac + val_frac}); "
        f"test is the remainder."
    )
    rng = np.random.default_rng(seed)
    perm = rng.permutation(n_games)
    n_train = int(round(n_games * train_frac))
    n_val = int(round(n_games * val_frac))
    train = sorted(perm[:n_train].tolist())
    val = sorted(perm[n_train:n_train + n_val].tolist())
    test = sorted(perm[n_train + n_val:].tolist())
    return train, val, test


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------


def build_datasets_from_games(
    games: list[GameRecord],
    *,
    train_sample_size: int | None = None,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    sample_seed: int = 1,
    verbose: bool = True,
) -> tuple[AgricolaValueDataset, AgricolaValueDataset, AgricolaValueDataset, NormStats]:
    """Build (train, val, test) datasets + `NormStats` from an in-memory
    list of `GameRecord`s. Useful for tests; `build_datasets` wraps
    this with on-disk loading.

    `train_sample_size`: if set, random-sample that many TRAIN
    descriptors from the full pool (decorrelates batches when records
    are correlated within a game). `None` uses all descriptors.

    `split_seed` and `sample_seed` are independent so the split can be
    held fixed while exploring sample-size effects.
    """
    n_games = len(games)
    if n_games < 3:
        raise ValueError(
            f"Need at least 3 games for train/val/test split; got {n_games}"
        )

    train_idxs, val_idxs, test_idxs = _split_games_by_index(
        n_games, train_frac, val_frac, split_seed,
    )
    train_games = [games[i] for i in train_idxs]
    val_games = [games[i] for i in val_idxs]
    test_games = [games[i] for i in test_idxs]
    if verbose:
        print(f"By-game split: train={len(train_games)} "
              f"val={len(val_games)} test={len(test_games)}")

    # Sub-sampling for the train split is done at the STATE level so
    # dual-perspective pairs stay together (matches the FIRST_NN.md §8
    # spec: "for each snapshot, train on BOTH perspectives"). Val/test
    # use all descriptors for low-variance metrics.
    train_keys = _enumerate_state_keys(train_games)
    if train_sample_size is not None:
        # train_sample_size is the target number of EXAMPLES; we sample
        # pairs, so divide by 2 and round down to an even total.
        n_pairs = train_sample_size // 2
        if n_pairs < len(train_keys):
            rng = np.random.default_rng(sample_seed)
            chosen = rng.choice(len(train_keys), size=n_pairs, replace=False)
            train_keys = [train_keys[i] for i in sorted(chosen.tolist())]
            if verbose:
                print(f"Sub-sampled train to {len(train_keys)} states "
                       f"({2 * len(train_keys)} examples, paired)")

    train_descs = _expand_keys_to_descriptors(train_keys)
    val_descs = _expand_to_descriptors(val_games)
    test_descs = _expand_to_descriptors(test_games)

    if verbose:
        print(f"Descriptors: train={len(train_descs)} "
              f"val={len(val_descs)} test={len(test_descs)}")
        print("Pre-encoding train...")
    X_tr, y_tr_raw = _encode_descriptors(train_descs, train_games)
    if verbose:
        print("Pre-encoding val...")
    X_va, y_va_raw = _encode_descriptors(val_descs, val_games)
    if verbose:
        print("Pre-encoding test...")
    X_te, y_te_raw = _encode_descriptors(test_descs, test_games)

    stats = _compute_norm_stats(X_tr, y_tr_raw)

    # Targets normalized; features stay raw (model normalizes inputs).
    y_tr = (y_tr_raw / stats.target_std).astype(np.float32)
    y_va = (y_va_raw / stats.target_std).astype(np.float32)
    y_te = (y_te_raw / stats.target_std).astype(np.float32)

    train_ds = AgricolaValueDataset(X_tr, y_tr)
    val_ds = AgricolaValueDataset(X_va, y_va)
    test_ds = AgricolaValueDataset(X_te, y_te)

    if verbose:
        print(f"NormStats: target_std={stats.target_std:.3f}, "
              f"encoding_version={stats.encoding_version}")
        print(f"Examples: train={len(train_ds)} val={len(val_ds)} "
              f"test={len(test_ds)}")

    return train_ds, val_ds, test_ds, stats


def build_datasets(
    run_dirs: Sequence[Path] | Path | str,
    *,
    train_sample_size: int | None = None,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    sample_seed: int = 1,
    verbose: bool = True,
) -> tuple[AgricolaValueDataset, AgricolaValueDataset, AgricolaValueDataset, NormStats]:
    """Build datasets + NormStats from one or more on-disk generation
    runs. Single path or sequence accepted.

    See `build_datasets_from_games` for the parameter semantics.
    """
    if isinstance(run_dirs, (str, Path)):
        run_dirs = [Path(run_dirs)]
    else:
        run_dirs = [Path(r) for r in run_dirs]

    if verbose:
        print(f"Loading games from {len(run_dirs)} run(s)...")
    games = load_all_games_from_runs(run_dirs)
    if verbose:
        print(f"Loaded {len(games)} games")

    return build_datasets_from_games(
        games,
        train_sample_size=train_sample_size,
        train_frac=train_frac,
        val_frac=val_frac,
        split_seed=split_seed,
        sample_seed=sample_seed,
        verbose=verbose,
    )
