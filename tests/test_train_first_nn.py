"""Integration test for the training script (`scripts/train_first_nn.py`).

Runs a tiny end-to-end training cycle with a small in-memory dataset
written to a fake run directory. Verifies:

- The script completes a few epochs without error.
- All expected output files are produced (checkpoint, log, config,
  test metrics, plots if matplotlib is installed).
- Per-epoch log entries have the expected fields.
- The saved-best checkpoint loads and produces a forward pass.
- Training reduces train loss over the first few epochs (sanity check
  that gradients are flowing).
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path

import pytest
import torch

from agricola.agents.base import RandomAgent
from agricola.agents.nn import play_recording_game
from agricola.agents.nn.encoder import ENCODED_DIM
from agricola.agents.nn.model import NormalizedValueModel
from agricola.agents.nn.training import train
from agricola.legality import legal_actions
from agricola.setup import setup, setup_env


def _record_one_game(seed: int):
    initial, env = setup_env(seed=seed)
    return play_recording_game(
        initial,
        RandomAgent(seed=seed),
        RandomAgent(seed=seed + 1),
        dealer=env.resolve,
        game_idx=seed, seed=seed,
        p0_config_path="random", p1_config_path="random",
        p0_temperature=0.0, p1_temperature=0.0,
        legal_actions_fn=legal_actions,
    )


@pytest.fixture(scope="module")
def tiny_run_dir(tmp_path_factory):
    """Build a tiny on-disk run with 12 games (default split puts >=1
    game in every split). Module-scoped so the ~6s fixture cost is paid
    once per test run."""
    tmp = tmp_path_factory.mktemp("tiny_run")
    run_dir = tmp / "fake_run"
    games_dir = run_dir / "games"
    games_dir.mkdir(parents=True)
    games = [_record_one_game(seed) for seed in range(12)]
    with (games_dir / "worker_00.pkl").open("wb") as f:
        pickle.dump(games, f)
    return run_dir


def test_train_smoke(tiny_run_dir, tmp_path):
    """End-to-end smoke: train 3 epochs, no early stop, verify all
    artifacts are produced and loadable."""
    out_dir = tmp_path / "out"
    log, best_path = train(
        run_dirs=tiny_run_dir,
        out_dir=out_dir,
        hidden_dims=[16, 16],
        max_epochs=3,
        early_stop_patience=99,   # don't stop early in 3 epochs
        batch_size=64,
        verbose=False,
    )
    assert len(log) == 3

    # All expected artifacts exist.
    assert (out_dir / "config.json").is_file()
    assert (out_dir / "norm_stats.json").is_file()
    assert (out_dir / "train_log.jsonl").is_file()
    assert (out_dir / "best.pt").is_file()
    assert (out_dir / "best.meta.json").is_file()
    assert (out_dir / "test_metrics.json").is_file()

    # Per-epoch log entries have the expected fields.
    for entry in log:
        for field in (
            "epoch", "train_mse", "train_mae_margin",
            "val_mse", "val_mae_margin", "is_best", "patience", "time_s",
        ):
            assert field in entry, f"Missing field {field!r} in log entry"

    # Best checkpoint loads and runs forward.
    model = NormalizedValueModel.load(best_path)
    x = torch.randn(4, ENCODED_DIM)
    with torch.no_grad():
        y = model.predict_margin(x)
    assert y.shape == (4,)
    assert torch.all(torch.isfinite(y))


def test_train_log_jsonl_format(tiny_run_dir, tmp_path):
    """Each line of train_log.jsonl is a valid JSON object matching the
    in-memory log entry."""
    out_dir = tmp_path / "out"
    log, _ = train(
        run_dirs=tiny_run_dir,
        out_dir=out_dir,
        hidden_dims=[16],
        max_epochs=2,
        early_stop_patience=99,
        batch_size=64,
        verbose=False,
    )
    lines = (out_dir / "train_log.jsonl").read_text().strip().splitlines()
    assert len(lines) == len(log)
    for line, entry in zip(lines, log):
        loaded = json.loads(line)
        assert loaded["epoch"] == entry["epoch"]
        assert loaded["train_mse"] == pytest.approx(entry["train_mse"])
        assert loaded["val_mse"] == pytest.approx(entry["val_mse"])


def test_train_config_persisted(tiny_run_dir, tmp_path):
    """config.json captures the hyperparameters the run was launched
    with — useful for reproducibility / comparing runs."""
    out_dir = tmp_path / "out"
    train(
        run_dirs=tiny_run_dir,
        out_dir=out_dir,
        hidden_dims=[16],
        max_epochs=1,
        batch_size=64,
        lr=5e-4,
        weight_decay=0.01,
        verbose=False,
    )
    with (out_dir / "config.json").open("r") as f:
        cfg = json.load(f)
    assert cfg["hidden_dims"] == [16]
    assert cfg["max_epochs"] == 1
    assert cfg["batch_size"] == 64
    assert cfg["lr"] == 5e-4
    assert cfg["weight_decay"] == 0.01


def test_train_reduces_train_loss(tiny_run_dir, tmp_path):
    """Gradients flowing → train MSE should drop noticeably over 5
    epochs on a tiny but real dataset. Loose threshold (50% drop) so we
    don't flake on optimization noise."""
    out_dir = tmp_path / "out"
    log, _ = train(
        run_dirs=tiny_run_dir,
        out_dir=out_dir,
        hidden_dims=[32, 32],
        max_epochs=5,
        early_stop_patience=99,
        batch_size=64,
        lr=1e-3,
        verbose=False,
    )
    assert log[-1]["train_mse"] < 0.5 * log[0]["train_mse"], (
        f"train_mse didn't drop enough: first={log[0]['train_mse']:.4f}, "
        f"last={log[-1]['train_mse']:.4f}"
    )


def test_train_early_stop_triggers(tiny_run_dir, tmp_path):
    """With patience=1 and a sufficiently-trained tiny model, early
    stop should trigger before max_epochs."""
    out_dir = tmp_path / "out"
    log, _ = train(
        run_dirs=tiny_run_dir,
        out_dir=out_dir,
        hidden_dims=[16],
        max_epochs=50,
        early_stop_patience=1,
        batch_size=64,
        verbose=False,
    )
    assert len(log) < 50, (
        f"Early stop didn't trigger with patience=1; ran {len(log)} epochs"
    )


def test_test_metrics_contains_expected_fields(tiny_run_dir, tmp_path):
    out_dir = tmp_path / "out"
    train(
        run_dirs=tiny_run_dir,
        out_dir=out_dir,
        hidden_dims=[16],
        max_epochs=2,
        early_stop_patience=99,
        batch_size=64,
        verbose=False,
    )
    with (out_dir / "test_metrics.json").open("r") as f:
        m = json.load(f)
    for field in (
        "best_epoch", "best_val_mse",
        "test_mse_normalized", "test_mae_margin",
    ):
        assert field in m
