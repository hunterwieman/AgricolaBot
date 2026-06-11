"""End-to-end smoke for the joint trainer (`shared_training.train_shared`).

Generates a handful of random-agent games (self-contained — no self-play data),
writes them as a run-dir worker pickle, and runs a 2-epoch joint train. Confirms
the full pipeline wires up: one-pass dataset build → shared model → interleaved
per-task training → a saved checkpoint with finite value + per-head metrics. The
fast-loader path is exercised (it's the default). Quality isn't asserted (2
epochs on a few games), only that the joint pipeline runs and produces a model.
"""
from __future__ import annotations

import pickle

from agricola.agents.base import RandomAgent
from agricola.agents.nn.recording import play_recording_game
from agricola.agents.nn.shared_model import SharedTrunkModel
from agricola.agents.nn.shared_training import train_shared
from agricola.setup import setup_env


def _write_games(run_dir, n=14):
    games = []
    for i in range(n):
        initial, env = setup_env(i)
        rec = play_recording_game(
            initial, RandomAgent(seed=i), RandomAgent(seed=i + 1000),
            dealer=env.resolve, game_idx=i, seed=i,
            p0_config_path="random", p1_config_path="random",
            p0_temperature=0.0, p1_temperature=0.0)
        games.append(rec)
    (run_dir / "games").mkdir(parents=True)
    with (run_dir / "games" / "worker_00.pkl").open("wb") as f:
        pickle.dump(games, f)


def test_train_shared_runs_end_to_end(tmp_path):
    run_dir = tmp_path / "run"
    _write_games(run_dir)

    log, best_path = train_shared(
        run_dir, tmp_path / "out",
        trunk_hidden_dims=[32, 32], embedding_dim=16, pointer_head_dims=[8],
        batch_size=64, max_epochs=2, steps_per_epoch=8, dropout=0.0,
        use_cache=False, device="cpu", verbose=False)

    # A checkpoint was written and reloads as a SharedTrunkModel.
    assert best_path.with_suffix(".pt").exists()
    SharedTrunkModel.load(best_path)

    # The epoch log carries a finite value val-MSE. (Per-head val CEs are logged
    # too, but on this tiny set a head can land a degenerate 1-row val split — not
    # meaningful to assert here; the real trainer has thousands of val rows/head.)
    assert len(log) >= 1
    last = log[-1]
    assert last["val_mse"] == last["val_mse"] and last["val_mse"] >= 0.0  # not NaN
    assert "fixed_val_ce" in last


def test_train_shared_hard_targets_runs(tmp_path):
    """`--hard-targets` (one-hot BC) path also trains — random games carry no π,
    so soft and hard agree here, but the flag must be plumbed through."""
    run_dir = tmp_path / "run"
    _write_games(run_dir, n=10)
    log, best_path = train_shared(
        run_dir, tmp_path / "out",
        trunk_hidden_dims=[16], embedding_dim=8, pointer_head_dims=[8],
        batch_size=64, max_epochs=1, steps_per_epoch=5, dropout=0.0,
        soft_targets=False, use_cache=False, device="cpu", verbose=False)
    assert best_path.with_suffix(".pt").exists()
    assert log[-1]["val_mse"] >= 0.0
