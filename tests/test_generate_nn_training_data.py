"""Integration tests for the batch generator script
(`scripts/generate_nn_training_data.py`).

Uses `random` agents to keep tests fast (no per-state evaluator
cost). The script's logic is agnostic to which agents are used, so
this exercises the full pipeline: plan → workers → pickle write →
metadata → resume — without paying the cost of a real heuristic game.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make scripts/ importable for the test.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from agricola.agents.nn import GameRecord, load_game_records
from generate_nn_training_data import (
    GamePlan,
    _build_agent,
    _resolve_config_cached,
    compute_plan,
    generate_dataset,
    partition_plan,
)
from agricola.legality import legal_actions


# ---------------------------------------------------------------------------
# Plan computation
# ---------------------------------------------------------------------------


def test_compute_plan_deterministic():
    """Same args → same plan. This is the load-bearing property for
    resume-on-existing: regenerating the plan in a second invocation
    must produce identical (game_idx, seed, configs, temps) tuples."""
    configs = ("random", "t2")
    plan_a = compute_plan(n_games=10, base_seed=42, approved_configs=configs)
    plan_b = compute_plan(n_games=10, base_seed=42, approved_configs=configs)
    assert plan_a == plan_b


def test_compute_plan_size_matches_n_games():
    """The plan has exactly n_games entries with sequential game_idxs."""
    plan = compute_plan(n_games=37, base_seed=0, approved_configs=("random",))
    assert len(plan) == 37
    assert [p.game_idx for p in plan] == list(range(37))


def test_compute_plan_seeds_are_unique():
    """Each game gets a unique seed (used for setup() and as the base
    for per-agent RNG seeds). Collisions would silently make games
    identical."""
    plan = compute_plan(n_games=100, base_seed=42, approved_configs=("random",))
    seeds = [p.seed for p in plan]
    assert len(set(seeds)) == len(seeds)


def test_compute_plan_draws_from_approved_configs():
    """Every drawn config is from the approved list."""
    configs = ("random", "t2")
    plan = compute_plan(n_games=50, base_seed=0, approved_configs=configs)
    for p in plan:
        assert p.p0_config in configs
        assert p.p1_config in configs


def test_compute_plan_temperatures_are_in_range():
    """Temperatures are either in [0.3, 1.0] (skilled mode) or exactly
    4.0 (exploration mode). The bimodal draw should never produce
    anything else."""
    plan = compute_plan(n_games=1000, base_seed=0, approved_configs=("random",))
    for p in plan:
        for t in (p.p0_temperature, p.p1_temperature):
            assert (0.3 <= t <= 1.0) or (t == 4.0), \
                f"Unexpected temperature {t!r}"


def test_compute_plan_temperatures_include_both_modes():
    """Across many games, we should see both modes of the bimodal
    distribution. With 5% probability per draw, in 1000 games × 2
    agents = 2000 draws, expect ~100 T=4.0 draws. We check ≥10 to be
    robust to the seed."""
    plan = compute_plan(n_games=1000, base_seed=0, approved_configs=("random",))
    n_exploration = sum(
        (p.p0_temperature == 4.0) + (p.p1_temperature == 4.0)
        for p in plan
    )
    assert n_exploration >= 10, \
        f"Only {n_exploration} exploration-mode draws in 2000 attempts"


# ---------------------------------------------------------------------------
# Partition
# ---------------------------------------------------------------------------


def test_partition_balanced():
    """Workers get roughly equal slices."""
    plan = compute_plan(n_games=10, base_seed=0, approved_configs=("random",))
    slices = partition_plan(plan, n_workers=3)
    assert len(slices) == 3
    # 10 / 3 = 4, 4, 2 (or similar)
    sizes = [len(s) for s in slices]
    assert sum(sizes) == 10
    assert max(sizes) - min(sizes) <= 1


def test_partition_no_overlap():
    """Game_idxs across workers are disjoint and cover the full range."""
    plan = compute_plan(n_games=20, base_seed=0, approved_configs=("random",))
    slices = partition_plan(plan, n_workers=4)
    all_idxs = [p.game_idx for s in slices for p in s]
    assert sorted(all_idxs) == list(range(20))


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------


def test_resolve_config_random():
    """The 'random' sentinel returns (None, 'random')."""
    cfg, arch = _resolve_config_cached("random")
    assert cfg is None
    assert arch == "random"


def test_resolve_config_t2():
    """The 't2' sentinel returns the V1 CONFIG_V1_T2."""
    cfg, arch = _resolve_config_cached("t2")
    assert cfg is not None
    assert arch == "v1"


def test_resolve_config_v3_json():
    """A V3 JSON path resolves to a HeuristicConfigV3."""
    cfg, arch = _resolve_config_cached("tuned_configs/v3_best.json")
    assert cfg is not None
    assert arch == "v3"


def test_build_agent_random():
    agent = _build_agent("random", seed=42, temperature=0.0,
                         legal_actions_fn=legal_actions)
    # Smoke check: agent is callable.
    assert callable(agent)


# ---------------------------------------------------------------------------
# Full pipeline integration (small, fast)
# ---------------------------------------------------------------------------


def test_generate_dataset_smoke(tmp_path: Path):
    """End-to-end: generate 4 games on 2 workers with random agents.

    Verify file layout, metadata, and that records load via
    `load_game_records` (i.e., the dataset is internally consistent)."""
    meta = generate_dataset(
        n_games=4,
        out_dir=tmp_path / "run1",
        n_workers=2,
        base_seed=0,
        approved_configs=("random",),
        restricted=False,  # RandomAgent ignores this, but the plumbing exercises it.
        verbose=False,
    )

    # Metadata sanity.
    assert meta["planned_games"] == 4
    assert meta["completed_games"] == 4
    assert meta["errored_games"] == []
    assert meta["n_workers"] == 2
    assert meta["data_version"] == 1
    assert meta["approved_configs"] == ["random"]

    # File layout.
    run_dir = tmp_path / "run1"
    assert (run_dir / "metadata.json").is_file()
    assert (run_dir / "games" / "worker_00.pkl").is_file()
    assert (run_dir / "games" / "worker_01.pkl").is_file()

    # Records load cleanly and total to n_games.
    all_records: list[GameRecord] = []
    for w in (0, 1):
        all_records.extend(load_game_records(
            run_dir / "games" / f"worker_{w:02d}.pkl"
        ))
    assert len(all_records) == 4

    # game_idxs cover 0..3, no duplicates.
    idxs = sorted(rec.game_idx for rec in all_records)
    assert idxs == [0, 1, 2, 3]

    # Each record has decisions and a terminal state.
    for rec in all_records:
        assert len(rec.decisions) > 0
        assert rec.terminal_state is not None
        assert rec.p0_config_path == "random"
        assert rec.p1_config_path == "random"


def test_generate_dataset_resume(tmp_path: Path):
    """Running the same generator twice on the same out-dir should NOT
    double-up games. Second invocation skips everything (n_completed=0,
    n_skipped=4)."""
    out_dir = tmp_path / "run_resume"

    # First run: produces 4 games.
    meta_first = generate_dataset(
        n_games=4,
        out_dir=out_dir,
        n_workers=2,
        base_seed=0,
        approved_configs=("random",),
        restricted=False,
        verbose=False,
    )
    assert meta_first["completed_games"] == 4

    # Capture worker pickle mtimes BEFORE second run (to verify they
    # don't get rewritten — workers should skip everything).
    pkl_paths = [out_dir / "games" / f"worker_{w:02d}.pkl" for w in (0, 1)]
    original_sizes = [p.stat().st_size for p in pkl_paths]

    # Second run: same params, same out_dir → resume.
    meta_second = generate_dataset(
        n_games=4,
        out_dir=out_dir,
        n_workers=2,
        base_seed=0,
        approved_configs=("random",),
        restricted=False,
        verbose=False,
    )

    # Same total count (no duplicates).
    assert meta_second["completed_games"] == 4

    # Worker pickles unchanged.
    for path, size_before in zip(pkl_paths, original_sizes):
        assert path.stat().st_size == size_before

    # All records still load cleanly.
    all_records = []
    for w in (0, 1):
        all_records.extend(load_game_records(
            out_dir / "games" / f"worker_{w:02d}.pkl"
        ))
    assert len(all_records) == 4


def test_generate_dataset_resume_partial(tmp_path: Path):
    """A run that adds MORE games on top of an existing partial run:
    play first 2 games, then re-invoke with n_games=4. The first 2
    should be skipped, only games 2 and 3 played fresh."""
    out_dir = tmp_path / "run_extend"

    # First pass: 2 games.
    meta_first = generate_dataset(
        n_games=2,
        out_dir=out_dir,
        n_workers=1,  # single worker for simplicity
        base_seed=0,
        approved_configs=("random",),
        restricted=False,
        verbose=False,
    )
    assert meta_first["completed_games"] == 2

    # Second pass: 4 games (same out_dir).
    meta_second = generate_dataset(
        n_games=4,
        out_dir=out_dir,
        n_workers=1,
        base_seed=0,
        approved_configs=("random",),
        restricted=False,
        verbose=False,
    )

    # Total is 4 (not 2+4=6 — the first 2 were skipped).
    assert meta_second["completed_games"] == 4

    # The 4 game_idxs are [0, 1, 2, 3]; no duplicates.
    records = load_game_records(out_dir / "games" / "worker_00.pkl")
    idxs = sorted(rec.game_idx for rec in records)
    assert idxs == [0, 1, 2, 3]
