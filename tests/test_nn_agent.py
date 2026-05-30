"""Tests for `NNAgent` and its underlying NN-backed evaluators.

Coverage:
- Both evaluators (simple + differential) return finite floats.
- Differential evaluator is exactly antisymmetric under perspective flip
  (V_diff(s, 0) = −V_diff(s, 1)) — load-bearing property of D.
- `NNAgent` returns actions that are in `legal_actions(state)`.
- `NNAgent` plays a full game without crashing (vs. RandomAgent).
- Both differential and non-differential modes work end-to-end.
- Deterministic given a fixed seed.
- A model saved + reloaded via `NormalizedValueModel.load` still
  produces an `NNAgent` that runs.
- Drop-in compatibility: `play_match`-style usage works.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import numpy as np
import pytest
import torch

from agricola.agents.base import RandomAgent, decider_of, play_game
from agricola.agents.nn import play_recording_game
from agricola.agents.nn.agent import (
    NNAgent,
    nn_evaluator,
    nn_evaluator_differential,
)
from agricola.agents.nn.dataset import NormStats
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.agents.nn.model import ConfigurableMLP, NormalizedValueModel
from agricola.agents.nn.training import train
from agricola.constants import Phase
from agricola.legality import legal_actions
from agricola.setup import setup


# ---------------------------------------------------------------------------
# Fixtures: a trained tiny model
# ---------------------------------------------------------------------------


def _record_one_game(seed: int):
    initial = setup(seed=seed)
    return play_recording_game(
        initial,
        RandomAgent(seed=seed),
        RandomAgent(seed=seed + 1),
        game_idx=seed, seed=seed,
        p0_config_path="random", p1_config_path="random",
        p0_temperature=0.0, p1_temperature=0.0,
        legal_actions_fn=legal_actions,
    )


@pytest.fixture(scope="module")
def trained_model(tmp_path_factory) -> NormalizedValueModel:
    """Tiny dataset → tiny model → 2-epoch training. Module-scoped so
    the cost (~5 s) is paid once for the whole agent-test module."""
    tmp = tmp_path_factory.mktemp("trained")
    run_dir = tmp / "fake_run"
    games_dir = run_dir / "games"
    games_dir.mkdir(parents=True)
    games = [_record_one_game(seed) for seed in range(12)]
    with (games_dir / "worker_00.pkl").open("wb") as f:
        pickle.dump(games, f)

    out_dir = tmp / "out"
    _, best_path = train(
        run_dirs=run_dir,
        out_dir=out_dir,
        hidden_dims=[16, 16],
        max_epochs=2,
        early_stop_patience=99,
        batch_size=64,
        verbose=False,
    )
    return NormalizedValueModel.load(best_path)


@pytest.fixture
def fresh_untrained_model() -> NormalizedValueModel:
    """An untrained model (default init only) — fine for testing
    evaluator/agent mechanics where playing strength doesn't matter."""
    stats = NormStats(
        input_mean=np.zeros(ENCODED_DIM, dtype=np.float32),
        input_std=np.ones(ENCODED_DIM, dtype=np.float32),
        target_std=10.0,
        encoding_version=ENCODING_VERSION,
    )
    mlp = ConfigurableMLP(input_dim=ENCODED_DIM, hidden_dims=[16])
    return NormalizedValueModel(mlp, stats)


# ---------------------------------------------------------------------------
# Evaluator functions
# ---------------------------------------------------------------------------


def test_simple_evaluator_returns_finite_float(fresh_untrained_model):
    state = setup(0)
    v = nn_evaluator(state, 0, fresh_untrained_model)
    assert isinstance(v, float)
    assert np.isfinite(v)


def test_differential_evaluator_returns_finite_float(fresh_untrained_model):
    state = setup(0)
    v = nn_evaluator_differential(state, 0, fresh_untrained_model)
    assert isinstance(v, float)
    assert np.isfinite(v)


def test_differential_evaluator_is_antisymmetric(fresh_untrained_model):
    """The load-bearing property of D: V_diff(s, 0) = −V_diff(s, 1)
    exactly, by construction, regardless of how the model was trained."""
    state = setup(7)
    v_p0 = nn_evaluator_differential(state, 0, fresh_untrained_model)
    v_p1 = nn_evaluator_differential(state, 1, fresh_untrained_model)
    assert v_p0 == pytest.approx(-v_p1, abs=1e-5), (
        f"D should be antisymmetric: got v_p0={v_p0}, v_p1={v_p1}, "
        f"v_p0 + v_p1 = {v_p0 + v_p1} (should be ≈ 0)"
    )


def test_simple_evaluator_not_strictly_antisymmetric_untrained(fresh_untrained_model):
    """Sanity inverse of the previous: the SIMPLE evaluator on an
    untrained model is NOT antisymmetric (it would only be after
    training with A augmentation). Confirms our two evaluators differ
    in the expected direction."""
    state = setup(7)
    v_p0 = nn_evaluator(state, 0, fresh_untrained_model)
    v_p1 = nn_evaluator(state, 1, fresh_untrained_model)
    # On an untrained net with non-zero outputs, perfect antisymmetry
    # would be a remarkable coincidence — assert NOT exactly negated.
    # (Allow a tiny tolerance for the truly-degenerate symmetric case.)
    assert abs(v_p0 + v_p1) > 1e-6 or v_p0 == 0.0


# ---------------------------------------------------------------------------
# NNAgent construction and basic usage
# ---------------------------------------------------------------------------


def test_nnagent_construct_default_differential(fresh_untrained_model):
    """Default construction uses the differential evaluator."""
    agent = NNAgent(fresh_untrained_model)
    assert agent.differential is True
    assert agent.evaluator is nn_evaluator_differential


def test_nnagent_construct_simple(fresh_untrained_model):
    agent = NNAgent(fresh_untrained_model, differential=False)
    assert agent.differential is False
    assert agent.evaluator is nn_evaluator


def test_nnagent_construct_sets_model_eval(fresh_untrained_model):
    """`model.eval()` is called at construction (catches future
    bugs if dropout/BN is added later)."""
    fresh_untrained_model.train()  # mark as training first
    NNAgent(fresh_untrained_model)
    assert not fresh_untrained_model.training, (
        "NNAgent should put the model in eval mode at construction"
    )


# ---------------------------------------------------------------------------
# NNAgent in-game behavior
# ---------------------------------------------------------------------------


def test_nnagent_returns_legal_action(fresh_untrained_model):
    """`agent(state)` returns an action that is in `legal_actions(state)`.
    This is the agent-protocol contract — break it and play_game fails."""
    state = setup(0)
    agent = NNAgent(fresh_untrained_model, seed=42)
    action = agent(state)
    assert action in legal_actions(state)


@pytest.mark.parametrize("differential", [True, False])
def test_nnagent_plays_full_game_vs_random(fresh_untrained_model, differential):
    """Drop-in compatibility: NNAgent works with `play_game` against
    a RandomAgent. Plays to BEFORE_SCORING without raising."""
    initial = setup(seed=0)
    nn_agent = NNAgent(fresh_untrained_model, differential=differential, seed=1)
    random_agent = RandomAgent(seed=2)
    terminal_state, _ = play_game(initial, (nn_agent, random_agent))
    assert terminal_state.phase == Phase.BEFORE_SCORING


def test_nnagent_deterministic_given_seed(fresh_untrained_model):
    """Two NNAgents with the same seed produce the same action on the
    same state. Required for reproducibility / match-runner correctness."""
    state = setup(0)
    a = NNAgent(fresh_untrained_model, seed=7, temperature=0.5)
    b = NNAgent(fresh_untrained_model, seed=7, temperature=0.5)
    # Take a few actions; if they ever disagree, determinism is broken.
    for _ in range(3):
        action_a = a(state)
        action_b = b(state)
        assert action_a == action_b, (
            f"Determinism broken: {action_a} vs {action_b}"
        )


def test_nnagent_with_trained_model_runs_full_game(trained_model):
    """Real end-to-end check: a model that actually completed training
    can be wrapped in NNAgent and play a game."""
    initial = setup(seed=11)
    nn_agent = NNAgent(trained_model, seed=0)
    opp = RandomAgent(seed=1)
    terminal, _ = play_game(initial, (nn_agent, opp))
    assert terminal.phase == Phase.BEFORE_SCORING


# ---------------------------------------------------------------------------
# Persistence integration
# ---------------------------------------------------------------------------


def test_saved_model_can_be_reloaded_into_nnagent(trained_model, tmp_path):
    """Save the trained model, reload it, wrap in an NNAgent — still
    plays. Tests the production inference path end-to-end."""
    save_path = tmp_path / "model"
    trained_model.save(save_path)
    reloaded = NormalizedValueModel.load(save_path)
    agent = NNAgent(reloaded, seed=0)
    state = setup(0)
    action = agent(state)
    assert action in legal_actions(state)
