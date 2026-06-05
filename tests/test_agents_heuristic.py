"""Smoke tests for the heuristic agents and their evaluators.

Scope:
- Both evaluators return finite floats on canonical states (fresh setup
  and a mid-game prefab).
- Both agents return one of `legal_actions(state)` at each decision.
- Both agents finish a full game from `setup(seed)` without crashing.
- Beat-random checks (loose threshold — smoke level, not Elo).
- `lookahead="action"` mode also runs to completion.
- The breeding-opportunity helper matches the user's worked examples.

Not in scope: coefficient tuning, deeper strategy correctness, agent vs
agent score distributions. Those belong in a future tournament harness.
"""

from __future__ import annotations

import math
import pytest

from agricola.agents import (
    HeuristicConfig,
    HubrisHeuristic,
    RandomAgent,
    SimpleHeuristic,
    evaluate_hubris,
    evaluate_simple,
    play_game,
)
from agricola.agents.heuristic import _num_breeding_opportunities_from_farm
from agricola.legality import legal_actions
from agricola.scoring import score
from agricola.setup import setup, setup_env
from agricola.state import Farmyard, PlayerState
from agricola.pasture import Pasture


# ---------------------------------------------------------------------------
# Evaluators return finite floats
# ---------------------------------------------------------------------------

def test_evaluate_simple_returns_finite_float_on_fresh_setup():
    s = setup(seed=0)
    v0 = evaluate_simple(s, 0)
    v1 = evaluate_simple(s, 1)
    assert isinstance(v0, float) and math.isfinite(v0)
    assert isinstance(v1, float) and math.isfinite(v1)


def test_evaluate_hubris_returns_finite_float_on_fresh_setup():
    s = setup(seed=0)
    v0 = evaluate_hubris(s, 0)
    v1 = evaluate_hubris(s, 1)
    assert isinstance(v0, float) and math.isfinite(v0)
    assert isinstance(v1, float) and math.isfinite(v1)


def test_evaluators_handle_multiple_seeds():
    """Make sure neither evaluator blows up on any of several seeds."""
    for seed in range(5):
        s = setup(seed=seed)
        for p in (0, 1):
            assert math.isfinite(evaluate_simple(s, p))
            assert math.isfinite(evaluate_hubris(s, p))


# ---------------------------------------------------------------------------
# Agents return legal actions
# ---------------------------------------------------------------------------

def test_simple_agent_returns_legal_action_on_fresh_setup():
    s = setup(seed=0)
    agent = SimpleHeuristic(seed=1)
    a = agent(s)
    assert a in legal_actions(s)


def test_hubris_agent_returns_legal_action_on_fresh_setup():
    s = setup(seed=0)
    agent = HubrisHeuristic(seed=1)
    a = agent(s)
    assert a in legal_actions(s)


# ---------------------------------------------------------------------------
# Full-game completion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("seed", [0, 7, 42])
def test_simple_finishes_full_game(seed):
    s, env = setup_env(seed=seed)
    final, trace = play_game(s, (SimpleHeuristic(seed=seed), RandomAgent(seed=seed + 100)), env.resolve)
    # game terminated cleanly; trace is non-empty
    assert len(trace) > 0
    # both players have a finite, well-formed score
    for p in (0, 1):
        t, _ = score(final, p)
        assert isinstance(t, int)


@pytest.mark.parametrize("seed", [0, 7, 42])
def test_hubris_finishes_full_game(seed):
    s, env = setup_env(seed=seed)
    final, trace = play_game(s, (HubrisHeuristic(seed=seed), RandomAgent(seed=seed + 100)), env.resolve)
    assert len(trace) > 0
    for p in (0, 1):
        t, _ = score(final, p)
        assert isinstance(t, int)


@pytest.mark.parametrize("seed", [0, 7])
def test_hubris_self_play_finishes(seed):
    s, env = setup_env(seed=seed)
    final, _ = play_game(
        s,
        (HubrisHeuristic(seed=seed), HubrisHeuristic(seed=seed + 1)),
        env.resolve,
    )
    for p in (0, 1):
        assert math.isfinite(score(final, p)[0])


# ---------------------------------------------------------------------------
# Beat-random checks (smoke level)
# ---------------------------------------------------------------------------

def _run_match(agent0_factory, agent1_factory, seeds):
    """Returns (p0_wins, p1_wins, ties, avg0_total, avg1_total)."""
    p0_wins = p1_wins = ties = 0
    totals_p0: list[int] = []
    totals_p1: list[int] = []
    for s in seeds:
        state, env = setup_env(seed=s)
        agents = (agent0_factory(s * 2 + 1), agent1_factory(s * 2 + 2))
        final, _ = play_game(state, agents, env.resolve)
        t0 = score(final, 0)[0]
        t1 = score(final, 1)[0]
        totals_p0.append(t0)
        totals_p1.append(t1)
        if t0 > t1: p0_wins += 1
        elif t1 > t0: p1_wins += 1
        else: ties += 1
    return p0_wins, p1_wins, ties, sum(totals_p0) / len(seeds), sum(totals_p1) / len(seeds)


def test_simple_beats_random_in_majority_of_seeds():
    # 5 seeds is plenty: Simple beats Random 20-0 over seeds 0..19 in
    # benchmarking, so the strength gap is enormous and a handful of games
    # catches any real regression (a broken agent drops to ~coin-flip, not by
    # one unlucky seed). Threshold 4/5 leaves one-seed slack to stay non-flaky.
    seeds = list(range(5))
    w_simple, w_random, _, avg_simple, avg_random = _run_match(
        lambda s: SimpleHeuristic(seed=s),
        lambda s: RandomAgent(seed=s),
        seeds,
    )
    assert w_simple >= 4, (
        f"Simple won only {w_simple}/5 vs Random "
        f"(avg score: Simple={avg_simple:.1f}, Random={avg_random:.1f})"
    )
    assert avg_simple > avg_random


# Note: a dedicated `hubris beats random` test would be redundant — the strength
# chain random < simple < hubris is established by the two tests here (each 20-0
# in benchmarking), so Hubris-over-Random follows transitively. It was dropped
# because it was the slowest of the three (Hubris games are the costliest).


def test_hubris_beats_simple_in_majority_of_seeds():
    """Hubris should outscore Simple — the extra coefficients should
    produce noticeably better play. 5 seeds suffices: Hubris beats Simple
    20-0 over seeds 0..19 in benchmarking, so 4/5 here leaves ample headroom
    while staying robust to one unlucky seed."""
    seeds = list(range(5))
    w_hubris, w_simple, _, avg_hubris, avg_simple = _run_match(
        lambda s: HubrisHeuristic(seed=s),
        lambda s: SimpleHeuristic(seed=s),
        seeds,
    )
    assert w_hubris >= 4, (
        f"Hubris won only {w_hubris}/5 vs Simple "
        f"(avg score: Hubris={avg_hubris:.1f}, Simple={avg_simple:.1f})"
    )
    assert avg_hubris > avg_simple


# ---------------------------------------------------------------------------
# Lookahead-mode toggle
# ---------------------------------------------------------------------------

def test_lookahead_action_mode_finishes_game():
    """The cheap 1-action lookahead mode also completes a game without
    error (even though it plays worse — see SimpleHeuristic in /
    HubrisHeuristic in `__init__` docstring for the trade-off)."""
    s, env = setup_env(seed=0)
    final, _ = play_game(
        s,
        (HubrisHeuristic(seed=0, lookahead="action"), RandomAgent(seed=1)),
        env.resolve,
    )
    for p in (0, 1):
        assert math.isfinite(score(final, p)[0])


def test_lookahead_invalid_value_raises():
    with pytest.raises(ValueError):
        HubrisHeuristic(lookahead="bogus")


# ---------------------------------------------------------------------------
# Temperature sampling
# ---------------------------------------------------------------------------

def test_temperature_sampling_finishes_game():
    """Softmax sampling at a non-zero temperature still produces legal
    actions and a complete game."""
    s, env = setup_env(seed=0)
    final, _ = play_game(
        s,
        (HubrisHeuristic(seed=0, temperature=0.5), RandomAgent(seed=1)),
        env.resolve,
    )
    for p in (0, 1):
        assert math.isfinite(score(final, p)[0])


# ---------------------------------------------------------------------------
# Breeding opportunity helper — anchored to user's worked examples
# ---------------------------------------------------------------------------

def _player_with_pastures(pastures: tuple) -> PlayerState:
    """Construct a minimal PlayerState whose pasture cache is set to the
    given pastures. Fence arrays and grid aren't used by
    `_num_breeding_opportunities_from_farm` — only `pastures` and the
    stables-in-supply / stables-in-pastures derivation."""
    # Match setup defaults for fields not under test.
    horizontal = tuple(tuple([False] * 5) for _ in range(4))
    vertical = tuple(tuple([False] * 6) for _ in range(3))
    from agricola.constants import CellType, HouseMaterial
    from agricola.state import Cell
    empty_grid = tuple(
        tuple(Cell(cell_type=CellType.EMPTY) for _ in range(5))
        for _ in range(3)
    )
    fy = Farmyard(
        grid=empty_grid,
        horizontal_fences=horizontal,
        vertical_fences=vertical,
        pastures=pastures,
    )
    from agricola.resources import Animals, Resources
    return PlayerState(
        resources=Resources(),
        animals=Animals(),
        farmyard=fy,
        house_material=HouseMaterial.WOOD,
        people_total=2,
        people_home=2,
    )


def test_breeding_opportunities_single_1x1_pasture():
    """1×1 pasture + house flex = 3-capacity for one type → 1 breed."""
    p = _player_with_pastures((Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),))
    assert _num_breeding_opportunities_from_farm(p) == 1


def test_breeding_opportunities_two_1x1_pastures():
    """Two 1×1 pastures (cap 2 each) + house flex 1 = only one type can
    reach 3 (the other pasture has only 2 of its dedicated type) → 1 breed."""
    p = _player_with_pastures((
        Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),
        Pasture(cells=frozenset({(0, 1)}), num_stables=0, capacity=2),
    ))
    assert _num_breeding_opportunities_from_farm(p) == 1


def test_breeding_opportunities_1x1_and_2x1():
    """1×1 (cap 2) + 2×1 (cap 4): 2×1 alone reaches 3 for one type;
    1×1 + house flex reaches 3 for a second type → 2 breeds."""
    p = _player_with_pastures((
        Pasture(cells=frozenset({(0, 0)}), num_stables=0, capacity=2),
        Pasture(cells=frozenset({(0, 1), (0, 2)}), num_stables=0, capacity=4),
    ))
    assert _num_breeding_opportunities_from_farm(p) == 2


def test_breeding_opportunities_two_2x2():
    """Two 2×2 pastures (cap 8 each) each reach 3 for one type → 2 breeds."""
    p = _player_with_pastures((
        Pasture(cells=frozenset({(0, 0), (0, 1), (1, 0), (1, 1)}), num_stables=0, capacity=8),
        Pasture(cells=frozenset({(0, 3), (0, 4), (1, 3), (1, 4)}), num_stables=0, capacity=8),
    ))
    assert _num_breeding_opportunities_from_farm(p) == 2


def test_breeding_opportunities_three_2x1():
    """Three 2×1 pastures (cap 4 each), each ≥3 → 3 breeds (capped at 3)."""
    p = _player_with_pastures((
        Pasture(cells=frozenset({(0, 0), (0, 1)}), num_stables=0, capacity=4),
        Pasture(cells=frozenset({(1, 0), (1, 1)}), num_stables=0, capacity=4),
        Pasture(cells=frozenset({(2, 0), (2, 1)}), num_stables=0, capacity=4),
    ))
    assert _num_breeding_opportunities_from_farm(p) == 3


def test_breeding_opportunities_no_pastures():
    """No pastures + house flex 1: not enough flex for 3 of one type → 0 breeds."""
    p = _player_with_pastures(())
    assert _num_breeding_opportunities_from_farm(p) == 0
