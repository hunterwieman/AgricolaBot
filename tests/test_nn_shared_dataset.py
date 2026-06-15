"""Tests for the one-pass cached joint dataset builder (`shared_dataset.py`).

Covers: the in-memory build (value + every fixed/pointer head from one pass),
π normalization, the consistent seed-split across tasks, shared-input-norm
fitting, and the per-run-dir cache round-trip (encode once → pure `np.load`).
"""
from __future__ import annotations

import pickle

import numpy as np
import pytest

from agricola.agents.base import RandomAgent
from agricola.agents.nn import GameRecord, play_recording_game
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODER_V2, ENCODING_VERSION
from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS
from agricola.agents.nn.shared_dataset import (
    _cache_complete,
    _chunk_dir,
    build_shared_datasets,
    build_shared_datasets_from_games,
)
from agricola.legality import legal_actions
from agricola.setup import setup_env


def _record(seed: int) -> GameRecord:
    initial, env = setup_env(seed=seed)
    return play_recording_game(
        initial, RandomAgent(seed=seed), RandomAgent(seed=seed + 1),
        dealer=env.resolve, game_idx=seed, seed=seed,
        p0_config_path="random", p1_config_path="random",
        p0_temperature=0.0, p1_temperature=0.0, legal_actions_fn=legal_actions)


@pytest.fixture(scope="module")
def games() -> list[GameRecord]:
    # 30 games → the 80/10/10 seed-hash split populates all three buckets.
    return [_record(s) for s in range(30)]


def test_in_memory_build_shapes_and_splits(games):
    sd = build_shared_datasets_from_games(games, verbose=False)
    # value: dual-perspective + terminals, all populated
    vt, vv, vte = sd.value
    assert len(vt) > 0 and len(vv) > 0 and len(vte) > 0
    x, y = vt[0]
    assert x.shape == (ENCODED_DIM,)
    # every head present in the bundle
    assert set(sd.fixed) == set(HEADS)
    assert set(sd.pointer) == set(POINTER_HEADS)
    # input norm fit, correct version
    assert sd.input_stats.encoding_version == ENCODING_VERSION
    assert sd.input_stats.target_std > 0
    assert sd.input_stats.input_mean.shape == (ENCODED_DIM,)


def test_pi_is_normalized_per_example(games):
    sd = build_shared_datasets_from_games(games, verbose=False)
    # fixed heads: π over classes sums to 1
    pl_train = sd.fixed["placement"][0]
    assert len(pl_train) > 0
    assert np.allclose(pl_train._pi.sum(dim=1).numpy(), 1.0, atol=1e-5)
    # pointer heads: π over each segment's candidates sums to 1
    for name, (tr, _, _) in sd.pointer.items():
        if len(tr) == 0:
            continue
        off = tr._off
        for i in range(len(tr)):
            seg = tr._pi[int(off[i]):int(off[i + 1])]
            assert abs(float(seg.sum()) - 1.0) < 1e-5


def test_split_sizes_match_datasets(games):
    sd = build_shared_datasets_from_games(games, verbose=False)
    # the recorded `sizes` agree with the actual dataset lengths, per task
    assert sd.sizes["value"] == tuple(len(d) for d in sd.value)
    for name, triple in sd.fixed.items():
        assert sd.sizes[f"fixed:{name}"] == tuple(len(d) for d in triple)
    for name, triple in sd.pointer.items():
        assert sd.sizes[f"ptr:{name}"] == tuple(len(d) for d in triple)


def test_cache_roundtrip(games, tmp_path):
    # Lay out a run dir (run/games/worker_00.pkl), build twice with use_cache.
    games_dir = tmp_path / "run" / "games"
    games_dir.mkdir(parents=True)
    with (games_dir / "worker_00.pkl").open("wb") as f:
        pickle.dump(games, f)
    run_dir = tmp_path / "run"

    sd1 = build_shared_datasets(run_dir, use_cache=True, verbose=False)
    # per-pickle chunk cache written on the miss (the OOM-safe format)
    assert _cache_complete(run_dir, ENCODER_V2)
    assert list(_chunk_dir(run_dir, ENCODER_V2).glob("chunk_*.npz"))
    sd2 = build_shared_datasets(run_dir, use_cache=True, verbose=False)  # hit
    # identical sizes from cache vs fresh encode
    assert sd1.sizes == sd2.sizes
    assert np.allclose(sd1.input_stats.input_mean, sd2.input_stats.input_mean)
    assert np.allclose(sd1.input_stats.target_std, sd2.input_stats.target_std)
