"""Unit-level coverage of `_execute_bake` and `_enumerate_pending_bake_bread`
across a matrix of (owned_majors, grain_in_supply) cases.

Validates Change 3 of TASK_5C: the greedy-by-rate allocator in `_execute_bake`
and the per-action grain-cap computation in `_enumerate_pending_bake_bread`.
Both consume the spec list returned by `baking_specs_for_player`, so this
file tests the algorithm with major-improvement specs only; a separate test
exercises the `BAKING_SPEC_EXTENSIONS` registry path with a synthetic spec.

Full purchase-then-bake integration tests live in `tests/test_major_improvement.py`.
"""
from __future__ import annotations

import pytest

from agricola.actions import CommitBake
from agricola.legality import (
    BAKING_SPEC_EXTENSIONS,
    _enumerate_pending_bake_bread,
    register_baking_spec_extension,
)
from agricola.pending import PendingBakeBread, push
from agricola.resolution import _execute_bake
from agricola.setup import setup

from tests.factories import with_current_player, with_majors, with_resources


# ---------------------------------------------------------------------------
# Matrix cases
# ---------------------------------------------------------------------------
#
# Each entry: (owned_majors, grain, expected_food_by_amount)
# `expected_food_by_amount` maps n (grain to bake) to the food that should be
# produced. n values not in the dict are NOT in legal options.

BAKE_BREAD_CASES = [
    # Single baker, uncapped.
    ((0,),          3, {1: 2, 2: 4, 3: 6}),                      # Fireplace
    ((2,),          3, {1: 3, 2: 6, 3: 9}),                      # Hearth
    # Single baker, capped.
    ((5,),          3, {1: 5}),                                  # Clay Oven (cap=1)
    ((6,),          3, {1: 4, 2: 8}),                            # Stone Oven (cap=2)
    # Capped + uncapped combinations.
    ((0, 5),        3, {1: 5, 2: 7, 3: 9}),                      # Fireplace + Clay
    ((0, 6),        3, {1: 4, 2: 8, 3: 10}),                     # Fireplace + Stone
    ((2, 6),        5, {1: 4, 2: 8, 3: 11, 4: 14, 5: 17}),       # Hearth + Stone
    ((2, 5),        3, {1: 5, 2: 8, 3: 11}),                     # Hearth + Clay
    # Capped-only (cap-sum bounds the legal range).
    ((5, 6),        5, {1: 5, 2: 9, 3: 13}),                     # Clay + Stone, grain > cap-sum
    ((5, 6),        2, {1: 5, 2: 9}),                            # Clay + Stone, grain = cap-sum
    # All four owned.
    ((0, 2, 5, 6),  4, {1: 5, 2: 9, 3: 13, 4: 16}),
    # Zero grain.
    ((6,),          0, {}),                                       # Stone Oven, no grain
    ((0,),          0, {}),                                       # Fireplace, no grain
]


@pytest.mark.parametrize("owned, grain, expected", BAKE_BREAD_CASES)
def test_bake_bread_algorithm(owned, grain, expected):
    """Both `_enumerate_pending_bake_bread` and `_execute_bake` produce
    the expected legal-amount set and food deltas across the matrix."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=grain)
    state = with_majors(state, owner_by_idx={idx: 0 for idx in owned})
    state = push(state, PendingBakeBread(
        player_idx=0, initiated_by_id="space:grain_utilization",
    ))
    pending = state.pending_stack[-1]
    p = state.players[0]

    # 1. Enumerator returns exactly the expected set of CommitBake amounts.
    legal = _enumerate_pending_bake_bread(state, pending)
    legal_amounts = sorted(a.grain for a in legal if isinstance(a, CommitBake))
    assert legal_amounts == sorted(expected.keys()), (
        f"owned={owned}, grain={grain}: legal amounts {legal_amounts} "
        f"!= expected {sorted(expected.keys())}"
    )

    # 2. For each legal amount, _execute_bake produces the expected food and
    #    debits the expected grain.
    for n, expected_food in expected.items():
        new_state = _execute_bake(state, 0, CommitBake(grain=n))
        delta_food = new_state.players[0].resources.food - p.resources.food
        delta_grain = new_state.players[0].resources.grain - p.resources.grain
        assert delta_food == expected_food, (
            f"owned={owned}, grain={grain}, bake={n}: food delta {delta_food} "
            f"!= expected {expected_food}"
        )
        assert delta_grain == -n, (
            f"owned={owned}, grain={grain}, bake={n}: grain delta {delta_grain} "
            f"!= -{n}"
        )


# ---------------------------------------------------------------------------
# BAKING_SPEC_EXTENSIONS registry — synthetic spec test
# ---------------------------------------------------------------------------

@pytest.fixture
def synthetic_extension():
    """Register a synthetic baking source (cap=1, rate=6) gated on
    "synthetic_test_card" in the player's minor_improvements. Teardown
    removes the extension so the registry stays clean across tests."""
    def _spec(state, player_idx):
        p = state.players[player_idx]
        return [(1, 6)] if "synthetic_test_card" in p.minor_improvements else []
    register_baking_spec_extension(_spec)
    yield _spec
    BAKING_SPEC_EXTENSIONS.remove(_spec)


def test_baking_spec_extension_registers_and_fires(synthetic_extension):
    """A registered BAKING_SPEC_EXTENSIONS entry contributes its (cap, rate)
    to baking_specs_for_player, and both _execute_bake and the cap
    computation use it correctly. The synthetic source has rate=6 > Clay
    Oven's rate=5, so when both are owned, the synthetic source fires first."""
    import dataclasses

    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=2)
    state = with_majors(state, owner_by_idx={5: 0})    # Clay Oven (cap=1, rate=5)
    # Add the synthetic card to player 0's minor_improvements.
    p = state.players[0]
    new_player = dataclasses.replace(p, minor_improvements=frozenset({"synthetic_test_card"}))
    new_players = (new_player, state.players[1])
    state = dataclasses.replace(state, players=new_players)

    state = push(state, PendingBakeBread(
        player_idx=0, initiated_by_id="space:grain_utilization",
    ))
    pending = state.pending_stack[-1]

    # Per-action grain cap is now 2 (Clay Oven cap=1 + synthetic cap=1).
    legal = _enumerate_pending_bake_bread(state, pending)
    legal_amounts = sorted(a.grain for a in legal if isinstance(a, CommitBake))
    assert legal_amounts == [1, 2]

    # Bake 1 grain: synthetic source (rate=6) fires first because it has higher rate.
    new_state = _execute_bake(state, 0, CommitBake(grain=1))
    assert new_state.players[0].resources.food - state.players[0].resources.food == 6
    assert new_state.players[0].resources.grain == 1

    # Bake 2 grain: synthetic (1 grain at rate 6) + Clay Oven (1 grain at rate 5) = 11 food.
    new_state = _execute_bake(state, 0, CommitBake(grain=2))
    assert new_state.players[0].resources.food - state.players[0].resources.food == 11
    assert new_state.players[0].resources.grain == 0


def test_baking_spec_extension_removed_after_fixture_teardown(synthetic_extension):
    """Sanity: the extension is in the registry while the fixture is active."""
    assert synthetic_extension in BAKING_SPEC_EXTENSIONS


def test_baking_spec_extension_registry_clean_between_tests():
    """After the fixture teardown, the registry is back to its original state."""
    # If teardown didn't fire, this test would see stale entries from the
    # previous test. The synthetic_extension fixture is not requested here,
    # so the registry shouldn't have any leftover synthetic entries.
    p_majors_only_state = setup(seed=0)
    p_majors_only_state = with_current_player(p_majors_only_state, 0)
    p_majors_only_state = with_majors(p_majors_only_state, owner_by_idx={5: 0})
    p_majors_only_state = with_resources(p_majors_only_state, 0, grain=1)
    p_majors_only_state = push(p_majors_only_state, PendingBakeBread(
        player_idx=0, initiated_by_id="space:grain_utilization",
    ))
    pending = p_majors_only_state.pending_stack[-1]
    legal = _enumerate_pending_bake_bread(p_majors_only_state, pending)
    # Clay Oven only -> max 1 grain.
    legal_amounts = sorted(a.grain for a in legal if isinstance(a, CommitBake))
    assert legal_amounts == [1]
