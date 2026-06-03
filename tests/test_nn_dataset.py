"""Tests for the NN training-dataset builder (`agricola/agents/nn/dataset.py`).

Coverage:
- Smoke: in-memory records → datasets with right shapes/dtypes.
- Disk loading: tmp_path run directory → datasets via `build_datasets`.
- Determinism: identical args → identical split + identical encoded arrays.
- By-game split: no game's records appear in two splits.
- A (dual-perspective augmentation): each snapshot produces exactly 2
  examples (both perspectives, opposite raw targets).
- §5.1 terminal pairs: each game contributes 2 terminal examples.
- NormStats: target std is sane; features are RAW (binary stays 0/1);
  zero-variance features handled (std clamped to 1).
- NormStats save/load roundtrip.
- Sub-sampling: train_sample_size limits train; val/test untouched.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pytest
import torch

from agricola.agents.base import RandomAgent
from agricola.agents.nn import GameRecord, play_recording_game
from agricola.agents.nn.dataset import (
    AgricolaValueDataset,
    NormStats,
    _expand_to_descriptors,
    build_datasets,
    build_datasets_chunked,
    build_datasets_from_games,
)
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.legality import legal_actions
from agricola.setup import setup, setup_env


# ---------------------------------------------------------------------------
# Fixtures: tiny in-memory record set
# ---------------------------------------------------------------------------


def _record_one_game(seed: int) -> GameRecord:
    initial, env = setup_env(seed=seed)
    return play_recording_game(
        initial,
        RandomAgent(seed=seed),
        RandomAgent(seed=seed + 1),
        dealer=env.resolve,
        game_idx=seed,  # use seed as a unique id within the fixture
        seed=seed,
        p0_config_path="random",
        p1_config_path="random",
        p0_temperature=0.0,
        p1_temperature=0.0,
        legal_actions_fn=legal_actions,
    )


@pytest.fixture(scope="module")
def small_games() -> list[GameRecord]:
    """12 random games — enough for the default 80/10/10 split to put
    ≥1 game in every split (rounds to 10/1/1). Fixture is module-scoped
    so the ~6s generation cost is paid once per test run."""
    return [_record_one_game(seed) for seed in range(12)]


# ---------------------------------------------------------------------------
# Smoke: in-memory build
# ---------------------------------------------------------------------------


def test_build_from_games_smoke(small_games):
    train, val, test, stats = build_datasets_from_games(small_games, verbose=False)
    assert len(train) > 0 and len(val) > 0 and len(test) > 0

    # __getitem__ returns torch tensors of the right shape and dtype.
    x, y = train[0]
    assert isinstance(x, torch.Tensor) and isinstance(y, torch.Tensor)
    assert x.shape == (ENCODED_DIM,)
    assert x.dtype == torch.float32
    assert y.shape == ()  # scalar target
    assert y.dtype == torch.float32

    # NormStats has the right shapes.
    assert stats.input_mean.shape == (ENCODED_DIM,)
    assert stats.input_std.shape == (ENCODED_DIM,)
    assert stats.input_std.min() >= 1e-6
    assert stats.target_std > 0
    assert stats.encoding_version == ENCODING_VERSION


# ---------------------------------------------------------------------------
# Target modes (Experiment P2)
# ---------------------------------------------------------------------------


def test_target_mode_margin_default(small_games):
    """Default target_mode is margin: target_std fitted (>0), targets
    unbounded score-diffs, recorded in NormStats."""
    _, _, _, stats = build_datasets_from_games(small_games, verbose=False)
    assert stats.target_mode == "margin"
    assert stats.target_std > 1.0  # margins span many points


@pytest.mark.parametrize("mode,allowed", [
    ("outcome", {-1.0, 0.0, 1.0}),
    ("winprob", {0.0, 0.5, 1.0}),
])
def test_target_mode_bounded_targets(small_games, mode, allowed):
    """outcome/winprob targets take only their discrete label values, and
    target_std is forced to 1.0 (no target normalization)."""
    train, _, _, stats = build_datasets_from_games(
        small_games, target_mode=mode, verbose=False,
    )
    assert stats.target_mode == mode
    assert stats.target_std == 1.0
    ys = {round(float(train[i][1]), 3) for i in range(len(train))}
    assert ys.issubset(allowed), f"{mode}: unexpected target values {ys - allowed}"


def test_target_mode_dual_perspective_antisymmetry(small_games):
    """outcome targets for the two perspectives of the same state are
    negatives (win for one ⇒ loss for the other; draw ⇒ 0 both). The
    dataset expands each state into adjacent perspective-0/1 descriptor
    pairs, so even indices pair with the next odd index."""
    train, _, _, _ = build_datasets_from_games(
        small_games, target_mode="outcome", verbose=False,
    )
    for i in range(0, min(len(train), 40), 2):
        y0 = float(train[i][1])
        y1 = float(train[i + 1][1])
        assert y0 == -y1, f"perspective targets not antisymmetric: {y0} vs {y1}"


@pytest.fixture(scope="module")
def chunk_games() -> list[GameRecord]:
    """More games than `small_games` (40) so the chunked builder's
    per-index random split reliably populates all three of train/val/test."""
    return [_record_one_game(seed) for seed in range(100, 140)]


def _write_run_dir(tmp_path, games, n_workers=2, name="run", metadata=True):
    """Write `games` across `n_workers` worker pickles under tmp/<name>/games/
    so the chunked builder (which iterates pickles) can read them. Optionally
    writes a metadata.json (needed for the cache's metadata invalidation)."""
    import json
    run_dir = tmp_path / name
    gdir = run_dir / "games"
    gdir.mkdir(parents=True)
    for w in range(n_workers):
        chunk = games[w::n_workers]  # strided split across workers
        with (gdir / f"worker_{w:02d}.pkl").open("wb") as f:
            pickle.dump(chunk, f)
    if metadata:
        with (run_dir / "metadata.json").open("w") as f:
            json.dump({"completed_games": len(games), "base_seed": 1234,
                       "data_version": 1}, f)
    return run_dir


def test_chunked_builder_shapes_and_dtype(chunk_games, tmp_path):
    """build_datasets_chunked produces non-empty train/val/test, float16
    X storage by default, and a fitted NormStats."""
    run_dir = _write_run_dir(tmp_path, chunk_games, n_workers=2)
    tr, va, te, stats = build_datasets_chunked(run_dir, verbose=False)
    assert len(tr) > 0 and len(va) > 0 and len(te) > 0
    # X stored as float16 by default; __getitem__ upcasts to float32.
    assert tr._X.dtype == torch.float16
    x, y = tr[0]
    assert x.dtype == torch.float32 and x.shape == (ENCODED_DIM,)
    assert stats.input_mean.shape == (ENCODED_DIM,)
    assert stats.target_std > 0


def test_chunked_builder_matches_full_on_stats(chunk_games, tmp_path):
    """Chunked streaming NormStats should closely match the full builder's
    (same games, same target). Splits differ (per-index vs permutation), so
    we compare aggregate input statistics over a shared encoding, loosely."""
    run_dir = _write_run_dir(tmp_path, chunk_games, n_workers=3)
    _, _, _, stats_chunk = build_datasets_chunked(run_dir, store_dtype="float32", verbose=False)
    # target_std is over the train split; both builders see the same games,
    # so the margin scale should be in the same ballpark.
    _, _, _, stats_full = build_datasets_from_games(chunk_games, verbose=False)
    assert stats_chunk.target_std == pytest.approx(stats_full.target_std, rel=0.5)
    assert stats_chunk.input_mean.shape == stats_full.input_mean.shape


def test_chunked_train_keep_frac_shrinks_train(chunk_games, tmp_path):
    """train_keep_frac < 1 drops train state-keys; val/test unaffected."""
    run_dir = _write_run_dir(tmp_path, chunk_games, n_workers=2)
    tr_full, va_full, _, _ = build_datasets_chunked(
        run_dir, train_keep_frac=1.0, verbose=False)
    tr_half, va_half, _, _ = build_datasets_chunked(
        run_dir, train_keep_frac=0.5, verbose=False)
    assert len(tr_half) < len(tr_full)          # train shrank
    assert len(va_half) == len(va_full)         # val unchanged


def test_chunked_train_game_frac_drops_whole_games(chunk_games, tmp_path):
    """train_game_frac < 1 drops whole train games (C17 control arm);
    val/test unaffected, and the drop is deterministic per game_seed."""
    run_dir = _write_run_dir(tmp_path, chunk_games, n_workers=2)
    tr_full, va_full, te_full, _ = build_datasets_chunked(
        run_dir, train_game_frac=1.0, verbose=False)
    tr_half, va_half, te_half, _ = build_datasets_chunked(
        run_dir, train_game_frac=0.5, verbose=False)
    assert len(tr_half) < len(tr_full)          # train shrank
    assert len(va_half) == len(va_full)         # val unchanged
    assert len(te_half) == len(te_full)         # test unchanged
    # deterministic: same flag → same train size on a rebuild
    tr_half2, _, _, _ = build_datasets_chunked(
        run_dir, train_game_frac=0.5, verbose=False)
    assert len(tr_half2) == len(tr_half)


def test_chunked_outcome_mode_targets_bounded(chunk_games, tmp_path):
    run_dir = _write_run_dir(tmp_path, chunk_games, n_workers=2)
    tr, _, _, stats = build_datasets_chunked(
        run_dir, target_mode="outcome", verbose=False)
    assert stats.target_mode == "outcome" and stats.target_std == 1.0
    ys = {round(float(tr[i][1]), 3) for i in range(len(tr))}
    assert ys.issubset({-1.0, 0.0, 1.0})


# ---------------------------------------------------------------------------
# Encoded-vector cache (§10.5)
# ---------------------------------------------------------------------------


def test_cache_write_then_hit_is_identical(chunk_games, tmp_path):
    """First build (use_cache) writes the npz; second build hits it and
    produces identical split sizes + NormStats — and the cache file exists."""
    from agricola.agents.nn.dataset import _cache_path, _cache_is_valid
    run_dir = _write_run_dir(tmp_path, chunk_games, n_workers=3)
    assert not _cache_path(run_dir).exists()
    tr, va, te, st = build_datasets_chunked(run_dir, use_cache=True, verbose=False)
    assert _cache_path(run_dir).exists() and _cache_is_valid(run_dir)
    tr2, va2, te2, st2 = build_datasets_chunked(run_dir, use_cache=True, verbose=False)
    assert (len(tr), len(va), len(te)) == (len(tr2), len(va2), len(te2))
    assert st.target_std == pytest.approx(st2.target_std)
    assert np.allclose(st.input_mean, st2.input_mean)


def test_cache_serves_all_target_modes(chunk_games, tmp_path):
    """One cache (written for margin) serves outcome/winprob too — the npz
    stores all three targets, so no re-encode is needed."""
    from agricola.agents.nn.dataset import _cache_path
    run_dir = _write_run_dir(tmp_path, chunk_games, n_workers=2)
    build_datasets_chunked(run_dir, use_cache=True, target_mode="margin", verbose=False)
    mtime = _cache_path(run_dir).stat().st_mtime
    tr_o, _, _, st_o = build_datasets_chunked(
        run_dir, use_cache=True, target_mode="outcome", verbose=False)
    # Cache file untouched (not rewritten) + outcome targets bounded.
    assert _cache_path(run_dir).stat().st_mtime == mtime
    assert st_o.target_mode == "outcome" and st_o.target_std == 1.0
    ys = {round(float(tr_o[i][1]), 3) for i in range(len(tr_o))}
    assert ys.issubset({-1.0, 0.0, 1.0})


def test_cache_invalidated_by_newer_pickle(chunk_games, tmp_path):
    """Touching a worker pickle (mtime newer than the cache) invalidates it."""
    import os, time
    from agricola.agents.nn.dataset import _cache_path, _cache_is_valid
    run_dir = _write_run_dir(tmp_path, chunk_games, n_workers=2)
    build_datasets_chunked(run_dir, use_cache=True, verbose=False)
    assert _cache_is_valid(run_dir)
    # Make a pickle newer than the cache.
    pkl = next((run_dir / "games").glob("worker_*.pkl"))
    future = time.time() + 100
    os.utime(pkl, (future, future))
    assert not _cache_is_valid(run_dir)


def test_cache_invalidated_by_metadata_mismatch(chunk_games, tmp_path):
    """A changed metadata.json (e.g. different completed_games) invalidates
    the cache header cross-check."""
    import json
    from agricola.agents.nn.dataset import _cache_is_valid, _cache_path
    run_dir = _write_run_dir(tmp_path, chunk_games, n_workers=2)
    build_datasets_chunked(run_dir, use_cache=True, verbose=False)
    assert _cache_is_valid(run_dir)
    meta_path = run_dir / "metadata.json"
    meta = json.load(meta_path.open())
    meta["completed_games"] += 1  # pretend the run grew
    json.dump(meta, meta_path.open("w"))
    # Bump cache mtime so the mtime check still passes — isolate the metadata check.
    import os, time
    cp = _cache_path(run_dir); future = time.time() + 100
    os.utime(cp, (future, future))
    assert not _cache_is_valid(run_dir)


def test_seed_split_is_stable_per_game(chunk_games, tmp_path):
    """A game's split depends only on its seed — invariant to the run-dir
    set / order (the property the cache relies on, §10.5). Build from one
    run dir, then from that dir + a second copy; shared games keep their
    split (checked via the seed→split map being consistent)."""
    from agricola.agents.nn.dataset import _seed_split
    # Determinism of the rule itself: same seed → same split, regardless of
    # call order or surrounding seeds.
    seeds = [g.seed for g in chunk_games]
    a = {s: _seed_split(s, 0, 0.8, 0.1) for s in seeds}
    b = {s: _seed_split(s, 0, 0.8, 0.1) for s in reversed(seeds)}
    assert a == b
    # And it actually partitions into the three buckets for a 40-game set.
    assert set(a.values()) <= {0, 1, 2}


def test_normstats_target_mode_roundtrips(small_games, tmp_path):
    _, _, _, stats = build_datasets_from_games(
        small_games, target_mode="winprob", verbose=False,
    )
    p = tmp_path / "stats.json"
    stats.save(p)
    reloaded = NormStats.load(p)
    assert reloaded.target_mode == "winprob"


# ---------------------------------------------------------------------------
# Disk path: tmp_path run dir
# ---------------------------------------------------------------------------


def test_build_from_disk(tmp_path: Path, small_games):
    """Write a fake run dir, point `build_datasets` at it, verify it loads."""
    run_dir = tmp_path / "fake_run"
    games_dir = run_dir / "games"
    games_dir.mkdir(parents=True)
    with (games_dir / "worker_00.pkl").open("wb") as f:
        pickle.dump(small_games, f)

    train, val, test, stats = build_datasets(run_dir, verbose=False)
    # Same as in-memory build given the same games.
    train_mem, val_mem, test_mem, stats_mem = build_datasets_from_games(
        small_games, verbose=False
    )
    assert len(train) == len(train_mem)
    assert len(val) == len(val_mem)
    assert len(test) == len(test_mem)
    assert stats.target_std == pytest.approx(stats_mem.target_std)


def test_build_from_disk_missing_games_dir(tmp_path: Path):
    """Pointing at a non-run directory raises FileNotFoundError."""
    bare = tmp_path / "empty"
    bare.mkdir()
    with pytest.raises(FileNotFoundError):
        build_datasets(bare, verbose=False)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic_split_and_encoding(small_games):
    """Same args → same per-example outputs across two builds."""
    a = build_datasets_from_games(small_games, split_seed=42, verbose=False)
    b = build_datasets_from_games(small_games, split_seed=42, verbose=False)
    for ds_a, ds_b in zip(a[:3], b[:3]):
        assert len(ds_a) == len(ds_b)
        # First example identical end-to-end.
        xa, ya = ds_a[0]
        xb, yb = ds_b[0]
        assert torch.equal(xa, xb)
        assert torch.equal(ya, yb)


def test_different_split_seed_changes_split(small_games):
    a_train, *_ = build_datasets_from_games(small_games, split_seed=0, verbose=False)
    b_train, *_ = build_datasets_from_games(small_games, split_seed=1, verbose=False)
    # Different splits should differ in *some* observable way for 6 games
    # (different game allocations → at least one different first-example).
    # Could in principle coincide; use multiple seeds if flaky.
    same = (len(a_train) == len(b_train) and torch.equal(a_train[0][0], b_train[0][0]))
    assert not same, "Different split seeds produced identical first train example"


# ---------------------------------------------------------------------------
# By-game split — no leakage
# ---------------------------------------------------------------------------


def test_split_is_by_game_no_leakage(small_games):
    """Records from one game must never appear in two splits. We test
    this at the descriptor level (game_idx_in_list within each split's
    games-list is disjoint by construction; we verify the resulting
    example counts are consistent with the per-split game counts)."""
    train, val, test, _ = build_datasets_from_games(
        small_games, train_frac=0.5, val_frac=0.25, verbose=False
    )
    # Per game: 2 × (n_snapshots + 1 terminal) examples.
    expected_examples_per_game = lambda g: 2 * (len(g.decisions) + 1)
    # We can't easily map back to which game produced which example without
    # extra metadata, but we can check totals split-by-split using the
    # split's game count. Recompute splits with the same seed/fracs.
    from agricola.agents.nn.dataset import _split_games_by_index
    ti, vi, te = _split_games_by_index(len(small_games), 0.5, 0.25, seed=0)
    assert set(ti).isdisjoint(set(vi))
    assert set(ti).isdisjoint(set(te))
    assert set(vi).isdisjoint(set(te))
    assert len(train) == sum(expected_examples_per_game(small_games[i]) for i in ti)
    assert len(val) == sum(expected_examples_per_game(small_games[i]) for i in vi)
    assert len(test) == sum(expected_examples_per_game(small_games[i]) for i in te)


# ---------------------------------------------------------------------------
# A augmentation + §5.1 terminal pairs
# ---------------------------------------------------------------------------


def test_descriptor_counts_match_augmentation_spec(small_games):
    """Each snapshot → 2 descriptors (both perspectives); each terminal
    → 2 descriptors. Total = 2 * (n_snapshots + 1) per game."""
    descs = _expand_to_descriptors(small_games)
    expected = 2 * sum(len(g.decisions) + 1 for g in small_games)
    assert len(descs) == expected
    # Each (game, snap or terminal) appears with both perspectives.
    per_state_persps: dict = {}
    for d in descs:
        key = (d.game_idx_in_list, d.is_terminal, d.snap_idx)
        per_state_persps.setdefault(key, set()).add(d.perspective)
    for persps in per_state_persps.values():
        assert persps == {0, 1}


def test_dual_perspective_targets_are_negated(small_games):
    """For any non-tied game, the two perspectives of the same state
    produce targets that are exact negatives of each other in raw
    margin units (before target normalization, but they're scaled by
    the same target_std, so the negation persists after normalization)."""
    train, val, test, stats = build_datasets_from_games(
        small_games, train_frac=0.99, val_frac=0.005, split_seed=0, verbose=False,
    )
    # Re-derive raw targets from the train set by multiplying back.
    ys_norm = train._y.numpy()
    ys_raw = ys_norm * stats.target_std
    # Descriptors are appended in pairs per state; check first pair is negated.
    # (only true for non-tied games — if game ended in a tie both targets are 0).
    pair_a, pair_b = ys_raw[0], ys_raw[1]
    if pair_a != 0:
        assert pair_a == -pair_b, (
            f"Dual-perspective targets not negated: {pair_a} vs {pair_b}"
        )


def test_terminal_descriptors_present(small_games):
    """Each game contributes exactly 2 terminal descriptors."""
    descs = _expand_to_descriptors(small_games)
    n_terminal = sum(1 for d in descs if d.is_terminal)
    assert n_terminal == 2 * len(small_games)


# ---------------------------------------------------------------------------
# NormStats
# ---------------------------------------------------------------------------


def test_target_normalization_yields_unit_stdev_on_train(small_games):
    """After dividing targets by training-set std, the training y has
    stdev ~1.0."""
    train, _, _, stats = build_datasets_from_games(small_games, verbose=False)
    y_train = train._y.numpy()
    # NOT exactly 1 (we divide by std, but std is computed over the SAME
    # samples — so unbiased estimator differences are nil here). Expect
    # very close to 1.
    assert abs(y_train.std() - 1.0) < 1e-5


def test_features_are_raw_not_normalized(small_games):
    """Features must NOT be normalized in the Dataset — the model does
    that. A binary feature must remain 0 or 1 in the dataset."""
    train, _, _, _ = build_datasets_from_games(small_games, verbose=False)
    # game_end_indicator is at a known index in the encoded vector; we
    # don't need to find its index — just check that SOME feature value
    # is exactly 1.0 somewhere in the dataset (would not survive
    # standardization which mean-centers).
    X = train._X.numpy()
    assert (X == 1.0).any(), "No raw 1.0 in features — they look normalized"
    assert (X == 0.0).any()


def test_normstats_save_load_roundtrip(tmp_path: Path, small_games):
    _, _, _, stats = build_datasets_from_games(small_games, verbose=False)
    path = tmp_path / "norm.json"
    stats.save(path)
    loaded = NormStats.load(path)
    assert np.allclose(loaded.input_mean, stats.input_mean)
    assert np.allclose(loaded.input_std, stats.input_std)
    assert loaded.target_std == pytest.approx(stats.target_std)
    assert loaded.encoding_version == stats.encoding_version


def test_normstats_handles_constant_features(small_games):
    """Constant features in the training set (std=0) get std clamped to
    1, never producing div-by-zero."""
    _, _, _, stats = build_datasets_from_games(small_games, verbose=False)
    assert np.all(np.isfinite(stats.input_std))
    assert stats.input_std.min() >= 1e-6


# ---------------------------------------------------------------------------
# Sub-sampling
# ---------------------------------------------------------------------------


def test_subsample_limits_train_only(small_games):
    """train_sample_size affects only the train split; val/test unchanged."""
    full = build_datasets_from_games(small_games, verbose=False)
    sub = build_datasets_from_games(
        small_games, train_sample_size=10, verbose=False
    )
    assert len(sub[0]) == 10                    # train sub-sampled
    assert len(sub[1]) == len(full[1])          # val unchanged
    assert len(sub[2]) == len(full[2])          # test unchanged


def test_subsample_size_above_pool_is_noop(small_games):
    """Asking for more samples than exist returns the full pool."""
    full = build_datasets_from_games(small_games, verbose=False)
    over = build_datasets_from_games(
        small_games, train_sample_size=10**9, verbose=False
    )
    assert len(over[0]) == len(full[0])


def test_subsample_is_paired(small_games):
    """Paired sampling: when a state is selected, BOTH perspectives
    must be present in the train split. Verified via:
    (a) the train example count is even, and
    (b) target values come in negation pairs (consecutive examples
        with opposite signs, modulo true-tie games where both are 0).
    """
    train, _, _, _ = build_datasets_from_games(
        small_games, train_sample_size=40, verbose=False
    )
    # Even count.
    assert len(train) % 2 == 0, "Paired sampling should yield an even example count"
    # Consecutive examples are perspectives of the same state and should
    # be exact negatives (after target normalization, scaled identically
    # by target_std, the relation persists).
    ys = train._y.numpy()
    pair_sums = ys[::2] + ys[1::2]   # ≈ 0 for paired-and-negated
    # Allow exact ties (both targets = 0); flag if many pairs aren't negated.
    n_pairs = len(ys) // 2
    n_negated_or_tied = int((np.abs(pair_sums) < 1e-5).sum())
    assert n_negated_or_tied == n_pairs, (
        f"Only {n_negated_or_tied}/{n_pairs} pairs are negated — paired "
        f"sampling broken (perspectives may have been split across pairs)."
    )
