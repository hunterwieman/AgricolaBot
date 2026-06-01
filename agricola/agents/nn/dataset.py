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
    target_mode: str = "margin"   # "margin" | "outcome" | "winprob" (Experiment P2)

    def to_dict(self) -> dict:
        return {
            "input_mean": self.input_mean.tolist(),
            "input_std": self.input_std.tolist(),
            "target_std": float(self.target_std),
            "encoding_version": int(self.encoding_version),
            "target_mode": str(self.target_mode),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NormStats":
        return cls(
            input_mean=np.asarray(d["input_mean"], dtype=np.float32),
            input_std=np.asarray(d["input_std"], dtype=np.float32),
            target_std=float(d["target_std"]),
            encoding_version=int(d["encoding_version"]),
            target_mode=str(d.get("target_mode", "margin")),
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


def _encode_one(
    desc: _ExampleDescriptor, games: list[GameRecord], target_mode: str = "margin",
) -> tuple[np.ndarray, float]:
    """Encode one descriptor → (features, raw_target), from `desc.perspective`'s frame.

    Target depends on `target_mode` (Experiment P2):
    - `margin`: `score(perspective) − score(other)` — the continuous score
      diff (tiebreaker-blind), unbounded; later normalized by target_std.
    - `outcome`: `+1 / 0 / −1` for win / draw / loss, using the
      tiebreaker-aware `game.winner`. For the tanh head.
    - `winprob`: `1.0 / 0.5 / 0.0` for win / draw / loss, same `winner`
      source. For the sigmoid head.
    """
    game = games[desc.game_idx_in_list]
    state = game.terminal_state if desc.is_terminal else game.decisions[desc.snap_idx].state
    features = encode_state(state, desc.perspective)

    if target_mode == "margin":
        if desc.perspective == 0:
            target = float(game.p0_final_score - game.p1_final_score)
        else:
            target = float(game.p1_final_score - game.p0_final_score)
    elif target_mode in ("outcome", "winprob"):
        # game.winner is 0, 1, or None (true tie). Frame from perspective.
        if game.winner is None:
            won = None
        else:
            won = (game.winner == desc.perspective)
        if target_mode == "outcome":
            target = 0.0 if won is None else (1.0 if won else -1.0)
        else:  # winprob
            target = 0.5 if won is None else (1.0 if won else 0.0)
    else:
        raise ValueError(
            f"Unknown target_mode {target_mode!r}; "
            f"choose margin / outcome / winprob."
        )
    return features, target


def _encode_descriptors(
    descriptors: list[_ExampleDescriptor], games: list[GameRecord],
    target_mode: str = "margin",
) -> tuple[np.ndarray, np.ndarray]:
    """Bulk-encode all descriptors into `(X, y_raw)` numpy arrays.

    `X.shape == (n, ENCODED_DIM)`, `y_raw.shape == (n,)`, both float32.
    `y_raw` is the raw (un-normalized) target per `target_mode`.
    """
    n = len(descriptors)
    X = np.zeros((n, ENCODED_DIM), dtype=np.float32)
    y = np.zeros(n, dtype=np.float32)
    for i, desc in enumerate(descriptors):
        feats, target = _encode_one(desc, games, target_mode)
        X[i] = feats
        y[i] = target
    return X, y


# ---------------------------------------------------------------------------
# Stats computation
# ---------------------------------------------------------------------------


def _compute_norm_stats(
    X_train: np.ndarray, y_train_raw: np.ndarray, target_mode: str = "margin",
) -> NormStats:
    """Compute per-feature input mean/std + target std on the TRAIN
    split only (never peek at val/test). Constant features get
    `std = 1` (so `(x - mean) / 1 == 0` for them — division-safe and
    the feature carries no signal in this dataset).

    Target normalization applies only to `margin` mode (the target is
    unbounded score-points, so we scale it to unit-ish variance). For
    `outcome` (∈ {−1,0,+1}) and `winprob` (∈ {0,0.5,1}) the target is
    already bounded and meaningful in its own units, so `target_std=1.0`
    (a no-op) — the model's tanh/sigmoid output is used directly."""
    eps = np.float32(1e-6)
    input_mean = X_train.mean(axis=0).astype(np.float32)
    input_std = X_train.std(axis=0).astype(np.float32)
    input_std = np.where(input_std < eps, np.float32(1.0), input_std)
    if target_mode == "margin":
        target_std = float(y_train_raw.std())
        if target_std < eps:
            # Pathological: all training games tied. Use 1 to avoid div-by-zero.
            target_std = 1.0
    else:
        target_std = 1.0
    return NormStats(
        input_mean=input_mean,
        input_std=input_std,
        target_std=target_std,
        encoding_version=ENCODING_VERSION,
        target_mode=target_mode,
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
        assert X.dtype in (np.float32, np.float16), (
            f"X dtype is {X.dtype}, expected float32 or float16"
        )
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
        # shares the underlying buffer (zero-copy); cheap. X may be float16
        # (the chunked builder stores it half-precision to fit large
        # datasets in RAM); __getitem__ upcasts to float32 per item so the
        # model's f32 normalization buffers see f32 input.
        self._X = torch.from_numpy(X)
        self._y = torch.from_numpy(y_normalized)
        self._x_is_half = X.dtype == np.float16

    def __len__(self) -> int:
        return self._y.shape[0]

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        x = self._X[idx]
        if self._x_is_half:
            x = x.float()
        return x, self._y[idx]


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
    target_mode: str = "margin",
    verbose: bool = True,
) -> tuple[AgricolaValueDataset, AgricolaValueDataset, AgricolaValueDataset, NormStats]:
    """Build (train, val, test) datasets + `NormStats` from an in-memory
    list of `GameRecord`s. Useful for tests; `build_datasets` wraps
    this with on-disk loading.

    `train_sample_size`: if set, random-sample that many TRAIN
    descriptors from the full pool (decorrelates batches when records
    are correlated within a game). `None` uses all descriptors.

    `target_mode`: supervision target — `margin` (default, score-diff
    regression), `outcome` (±1/0 win/draw/loss for a tanh head), or
    `winprob` (1/0.5/0 for a sigmoid head). See FIRST_NN.md Experiment P2.

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
    X_tr, y_tr_raw = _encode_descriptors(train_descs, train_games, target_mode)
    if verbose:
        print("Pre-encoding val...")
    X_va, y_va_raw = _encode_descriptors(val_descs, val_games, target_mode)
    if verbose:
        print("Pre-encoding test...")
    X_te, y_te_raw = _encode_descriptors(test_descs, test_games, target_mode)

    stats = _compute_norm_stats(X_tr, y_tr_raw, target_mode)

    # Targets normalized; features stay raw (model normalizes inputs).
    # For outcome/winprob target_std=1.0, so this is a no-op there.
    y_tr = (y_tr_raw / stats.target_std).astype(np.float32)
    y_va = (y_va_raw / stats.target_std).astype(np.float32)
    y_te = (y_te_raw / stats.target_std).astype(np.float32)

    train_ds = AgricolaValueDataset(X_tr, y_tr)
    val_ds = AgricolaValueDataset(X_va, y_va)
    test_ds = AgricolaValueDataset(X_te, y_te)

    if verbose:
        print(f"NormStats: target_mode={stats.target_mode}, "
              f"target_std={stats.target_std:.3f}, "
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
    target_mode: str = "margin",
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
        target_mode=target_mode,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# Chunked (low-memory) builder — for datasets too large to hold all games
# in RAM at once (e.g. 55k+ games on an 8 GB machine).
# ---------------------------------------------------------------------------


def _iter_worker_pickles(run_dirs: Sequence[Path]):
    """Yield worker-pickle paths in the same stable order as
    `load_all_games_from_runs` (sorted run dir, then sorted pickle)."""
    for run_dir in run_dirs:
        games_dir = Path(run_dir) / "games"
        if not games_dir.is_dir():
            raise FileNotFoundError(
                f"{run_dir} has no 'games/' subdirectory — not a run directory?"
            )
        for pkl in sorted(games_dir.glob("worker_*.pkl")):
            yield pkl


def _seed_split(game_seed: int, split_seed: int, train_frac: float, val_frac: float) -> int:
    """Deterministic per-GAME split keyed on the game's intrinsic `seed`
    (0=train, 1=val, 2=test). Stable per game — rename-proof and invariant
    to which other run dirs are loaded (FIRST_NN §10.5). Proportions match
    train_frac / val_frac in expectation. Differs from `_split_games_by_index`'s
    exact permutation; the chunked/cache path is the standard for large data."""
    r = float(np.random.default_rng([split_seed, int(game_seed)]).random())
    if r < train_frac:
        return 0
    if r < train_frac + val_frac:
        return 1
    return 2


def _targets_all_modes(game: GameRecord, perspective: int) -> tuple[float, int, float]:
    """(margin, outcome, winprob) targets for one descriptor, from
    `perspective`'s frame. Margin = score-diff (tiebreaker-blind);
    outcome/winprob use the tiebreaker-aware `game.winner`. Stored
    together so the cache is target-mode-agnostic (§10.5)."""
    if perspective == 0:
        margin = float(game.p0_final_score - game.p1_final_score)
    else:
        margin = float(game.p1_final_score - game.p0_final_score)
    if game.winner is None:
        outcome, winprob = 0, 0.5
    elif game.winner == perspective:
        outcome, winprob = 1, 1.0
    else:
        outcome, winprob = -1, 0.0
    return margin, outcome, winprob


# Per-descriptor cache arrays (the npz field set). `X` is the expensive
# encoding; the rest are cheap metadata that let split / target / sampling
# be chosen at load time without re-encoding.
_CACHE_FIELDS = ("X", "y_margin", "y_outcome", "y_winprob",
                 "game_seed", "is_terminal", "snap_idx")


def _encode_run_dir_arrays(run_dir: Path, dt, verbose: bool = False) -> dict:
    """Encode ALL descriptors of one run dir into the cache arrays
    (per-pickle chunked, freeing games as it goes). Returns a dict with the
    `_CACHE_FIELDS`. Split-agnostic and target-agnostic — that's what makes
    the result reusable across any combination / target_mode (§10.5)."""
    games_dir = Path(run_dir) / "games"
    if not games_dir.is_dir():
        raise FileNotFoundError(f"{run_dir} has no 'games/' subdirectory.")
    parts: dict[str, list] = {f: [] for f in _CACHE_FIELDS}
    total = 0
    for pkl in sorted(games_dir.glob("worker_*.pkl")):
        games = load_game_records(pkl)  # enforces DATA_VERSION
        descs = _expand_to_descriptors(games)  # both perspectives, paired
        n = len(descs)
        X = np.zeros((n, ENCODED_DIM), dtype=dt)
        ym = np.zeros(n, np.float32); yo = np.zeros(n, np.int8)
        yw = np.zeros(n, np.float32); gs = np.zeros(n, np.int64)
        it = np.zeros(n, np.bool_); sx = np.zeros(n, np.int32)
        for i, d in enumerate(descs):
            g = games[d.game_idx_in_list]
            state = g.terminal_state if d.is_terminal else g.decisions[d.snap_idx].state
            X[i] = encode_state(state, d.perspective).astype(dt)
            m, o, w = _targets_all_modes(g, d.perspective)
            ym[i] = m; yo[i] = o; yw[i] = w
            gs[i] = g.seed; it[i] = d.is_terminal; sx[i] = d.snap_idx
        for f, a in zip(_CACHE_FIELDS, (X, ym, yo, yw, gs, it, sx)):
            parts[f].append(a)
        total += n
        del games, descs
        if verbose:
            print(f"  encoded {run_dir.name}/{pkl.name}: descs so far={total}", flush=True)
    return {f: np.concatenate(parts[f], axis=0) for f in _CACHE_FIELDS}


def _cache_path(run_dir: Path) -> Path:
    return Path(run_dir) / f"encoded_v{ENCODING_VERSION}.npz"


def _run_dir_meta(run_dir: Path) -> tuple[int, int, int] | None:
    """(completed_games, base_seed, data_version) from metadata.json, or None."""
    mp = Path(run_dir) / "metadata.json"
    if not mp.is_file():
        return None
    with mp.open() as f:
        d = json.load(f)
    return (int(d.get("completed_games", -1)), int(d.get("base_seed", -1)),
            int(d.get("data_version", -1)))


def _cache_is_valid(run_dir: Path) -> bool:
    """Cheap validity check — never loads the games (that's the cost the
    cache removes). Valid iff: cache exists, is newer than every worker
    pickle (mtime), its ENCODING_VERSION matches, and its stored
    (completed_games, base_seed, data_version) header matches the run dir's
    current metadata.json (§10.5 invalidation)."""
    cp = _cache_path(run_dir)
    if not cp.is_file():
        return False
    pkls = sorted((Path(run_dir) / "games").glob("worker_*.pkl"))
    if not pkls:
        return False
    cmt = cp.stat().st_mtime
    if any(p.stat().st_mtime > cmt for p in pkls):
        return False
    try:
        with np.load(cp) as z:  # reading scalars does not load X
            if int(z["encoding_version"]) != ENCODING_VERSION:
                return False
            hdr = (int(z["completed_games"]), int(z["base_seed"]), int(z["data_version"]))
    except Exception:
        return False
    meta = _run_dir_meta(run_dir)
    if meta is not None and hdr != meta:
        return False
    return True


def _write_cache(run_dir: Path, arrays: dict, verbose: bool = False) -> None:
    meta = _run_dir_meta(run_dir) or (-1, -1, -1)
    cp = _cache_path(run_dir)
    # tmp must end in .npz, else np.savez appends ".npz" and the rename target
    # is wrong (np.savez auto-suffix gotcha).
    tmp = cp.parent / (cp.name + ".tmp.npz")
    np.savez(
        tmp, **arrays,
        encoding_version=np.int64(ENCODING_VERSION),
        completed_games=np.int64(meta[0]), base_seed=np.int64(meta[1]),
        data_version=np.int64(meta[2]),
    )
    tmp.replace(cp)  # atomic
    if verbose:
        print(f"  wrote cache {cp.name} ({cp.stat().st_size / 1e6:.0f} MB)", flush=True)


def _load_cache(run_dir: Path) -> dict:
    with np.load(_cache_path(run_dir)) as z:
        return {f: z[f] for f in _CACHE_FIELDS}


def build_datasets_chunked(
    run_dirs: Sequence[Path] | Path | str,
    *,
    train_frac: float = 0.8,
    val_frac: float = 0.1,
    split_seed: int = 0,
    sample_seed: int = 1,
    target_mode: str = "margin",
    train_keep_frac: float = 1.0,
    store_dtype: str = "float16",
    use_cache: bool = False,
    verbose: bool = True,
) -> tuple[AgricolaValueDataset, AgricolaValueDataset, AgricolaValueDataset, NormStats]:
    """Memory-frugal dataset builder for large game collections, with an
    optional per-run-dir encoded-vector cache (FIRST_NN §10.5).

    Per run dir: if `use_cache` and a valid cache exists, load its npz
    (seconds, no game loading); else encode the run dir's descriptors
    (one pickle at a time, freeing games) and — if `use_cache` — write the
    cache. The encoding is split- and target-agnostic (stores all three
    target modes + each descriptor's game seed), so one cache serves every
    split / target_mode / `train_keep_frac` combination.

    Then, in memory (float16-dominated, fits where the all-games build
    can't): assign the train/val/test split per game via `_seed_split`
    (stable per game — rename-proof, combination-invariant), select the
    `target_mode` targets, apply `train_keep_frac` to train, and fit
    `NormStats` on the surviving train rows.

    NB: the split is seed-hash, NOT `build_datasets`'s exact permutation —
    so `use_cache`/chunked models aren't MAE-comparable to permutation-split
    models (gameplay still is). See FIRST_NN §10.5.
    """
    if isinstance(run_dirs, (str, Path)):
        run_dirs = [Path(run_dirs)]
    else:
        run_dirs = [Path(r) for r in run_dirs]
    dt = np.float16 if store_dtype == "float16" else np.float32

    # ----- Gather each run dir's full arrays (cache hit or encode[+write]) -----
    parts: list[dict] = []
    for rd in run_dirs:
        if use_cache and _cache_is_valid(rd):
            if verbose:
                print(f"  cache HIT: {rd.name}/{_cache_path(rd).name}", flush=True)
            parts.append(_load_cache(rd))
        else:
            if verbose:
                print(f"  cache MISS: encoding {rd.name}", flush=True)
            arr = _encode_run_dir_arrays(rd, dt, verbose=verbose)
            if use_cache:
                _write_cache(rd, arr, verbose=verbose)
            parts.append(arr)

    X = np.concatenate([p["X"] for p in parts], axis=0).astype(dt)
    y_margin = np.concatenate([p["y_margin"] for p in parts])
    y_outcome = np.concatenate([p["y_outcome"] for p in parts]).astype(np.float32)
    y_winprob = np.concatenate([p["y_winprob"] for p in parts])
    game_seed = np.concatenate([p["game_seed"] for p in parts])
    snap_idx = np.concatenate([p["snap_idx"] for p in parts])
    del parts

    y_raw = {"margin": y_margin, "outcome": y_outcome, "winprob": y_winprob}[target_mode]

    # ----- Split per game (seed-hash); cache the per-seed decision -----
    split_of_seed: dict[int, int] = {}
    split = np.empty(len(game_seed), dtype=np.int8)
    for i, s in enumerate(game_seed):
        s = int(s)
        sp = split_of_seed.get(s)
        if sp is None:
            sp = _seed_split(s, split_seed, train_frac, val_frac)
            split_of_seed[s] = sp
        split[i] = sp

    # ----- train_keep_frac: drop a fraction of TRAIN state-keys (both
    #       perspectives together; deterministic per (game_seed, snap_idx)) -----
    train_mask = split == 0
    if train_keep_frac < 1.0:
        for i in np.nonzero(train_mask)[0]:
            keep = float(np.random.default_rng(
                [sample_seed, int(game_seed[i]), int(snap_idx[i]) + 1]).random())
            if keep >= train_keep_frac:
                train_mask[i] = False
    val_mask = split == 1
    test_mask = split == 2

    Xtr, ytr_raw = X[train_mask], y_raw[train_mask]
    if Xtr.shape[0] == 0:
        raise ValueError("Chunked build produced no training descriptors.")

    # ----- NormStats over surviving train rows -----
    eps = 1e-6
    input_mean = Xtr.mean(axis=0, dtype=np.float64).astype(np.float32)
    input_std = Xtr.std(axis=0, dtype=np.float64).astype(np.float32)
    input_std = np.where(input_std < eps, np.float32(1.0), input_std)
    if target_mode == "margin":
        target_std = float(ytr_raw.std())
        if target_std < eps:
            target_std = 1.0
    else:
        target_std = 1.0
    stats = NormStats(
        input_mean=input_mean, input_std=input_std,
        target_std=target_std, encoding_version=ENCODING_VERSION,
        target_mode=target_mode,
    )

    def _ds(mask) -> AgricolaValueDataset:
        Xm = X[mask].astype(dt)
        ym = (y_raw[mask] / stats.target_std).astype(np.float32)
        if Xm.shape[0] == 0:
            Xm = np.zeros((0, ENCODED_DIM), dtype=dt)
            ym = np.zeros((0,), dtype=np.float32)
        return AgricolaValueDataset(Xm, ym)

    train_ds = AgricolaValueDataset(Xtr.astype(dt),
                                    (ytr_raw / stats.target_std).astype(np.float32))
    val_ds = _ds(val_mask)
    test_ds = _ds(test_mask)
    if verbose:
        print(f"Chunked build: train={len(train_ds)} val={len(val_ds)} "
              f"test={len(test_ds)} | dtype={dt.__name__} | use_cache={use_cache} "
              f"| target_mode={target_mode} target_std={target_std:.3f}", flush=True)

    return train_ds, val_ds, test_ds, stats
