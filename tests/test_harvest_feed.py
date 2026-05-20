"""Tests for the HARVEST_FEED resolution (Task 7).

Engine-level integration tests covering PendingHarvestFeed legality
enumeration, CommitHarvestConversion (joinery/pottery/basketmaker),
CommitConvert (Pareto-frontier conversion), pre-debit semantics, begging
assignment, and the gratuitous-Stop floor.

Frontier tuples below (from food_payment_frontier / harvest_feed_frontier)
use the REMAINING convention. CommitConvert(...) uses CONSUMED amounts —
inverted from the frontier's REMAINING via consumed = player_max - remaining.
"""
from __future__ import annotations

import dataclasses

import pytest

from agricola.actions import (
    CommitConvert,
    CommitHarvestConversion,
    Stop,
)
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed
from agricola.setup import setup

from tests.factories import (
    with_animals,
    with_majors,
    with_pending_stack,
    with_phase,
    with_people,
    with_resources,
)


# --- Helpers ----------------------------------------------------------------

def _harvest_feed_state(seed=0, *, sp=None):
    """Return a state at Phase.HARVEST_FEED with FEED pendings pushed for
    both players (SP on top). Caller is responsible for adjusting resources
    BEFORE calling — pre-debit happens during _initiate_harvest_feed.
    """
    state = setup(seed=seed)
    if sp is not None:
        state = dataclasses.replace(state, starting_player=sp)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    return state


def _force_food_owed(state, player_idx, food_owed):
    """Replace the FEED pending for `player_idx` with a fresh one carrying
    the given food_owed. Used to construct precise FEED scenarios."""
    new_stack = []
    for f in state.pending_stack:
        if isinstance(f, PendingHarvestFeed) and f.player_idx == player_idx:
            new_stack.append(dataclasses.replace(f, food_owed=food_owed))
        else:
            new_stack.append(f)
    return dataclasses.replace(state, pending_stack=tuple(new_stack))


def _top_pending(state) -> PendingHarvestFeed:
    return state.pending_stack[-1]


# --- Pre-debit & begging ----------------------------------------------------

def test_pre_debit_full_food_means_zero_owed():
    """Player with 5 food, need=4 -> pre-debit 4, food_owed=0, supply=1."""
    state = setup(seed=0)
    state = with_resources(state, 0, food=5)
    state = with_resources(state, 1, food=5)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    for p_idx in (0, 1):
        pendings = [f for f in state.pending_stack
                    if isinstance(f, PendingHarvestFeed) and f.player_idx == p_idx]
        assert pendings[0].food_owed == 0
        assert state.players[p_idx].resources.food == 1


def test_pre_debit_short_food_pre_owed():
    """Player with 1 food, need=4 -> pre-debit 1, food_owed=3, supply=0."""
    state = setup(seed=0)
    state = with_resources(state, 0, food=1)
    state = with_resources(state, 1, food=10)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    p0_pending = [f for f in state.pending_stack
                  if isinstance(f, PendingHarvestFeed) and f.player_idx == 0][0]
    assert p0_pending.food_owed == 3
    assert state.players[0].resources.food == 0


def test_newborn_discount_reduces_need():
    """newborn from this round: need = 2*people_total - newborns.
    2 adults + 1 newborn -> need = 2*3 - 1 = 5."""
    state = setup(seed=0)
    state = with_people(state, 0, total=3, home=3, newborns=1)
    state = with_resources(state, 0, food=0)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    p0_pending = [f for f in state.pending_stack
                  if isinstance(f, PendingHarvestFeed) and f.player_idx == 0][0]
    assert p0_pending.food_owed == 5   # 2*3 - 1


# --- Trivial FEED -----------------------------------------------------------

def test_trivial_feed_just_stop():
    """Player with food_owed=0, no convertibles, no crafts -> the only legal
    actions are the singleton CommitConvert(0,0,0,0,0); after commit, only
    Stop. This is the gratuitous floor."""
    state = setup(seed=0)
    state = with_resources(state, 0, food=10)
    state = with_resources(state, 1, food=10)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    # SP is on top; pick actions for them.
    actions = legal_actions(state)
    assert actions == [CommitConvert(grain=0, veg=0, sheep=0, boar=0, cattle=0)]

    state = step(state, actions[0])
    # After CommitConvert, only Stop is legal.
    actions = legal_actions(state)
    assert actions == [Stop()]


def test_begging_assignment_no_convertibles():
    """Player with 0 food, need=4, no convertibles -> begging 4 after commit."""
    state = setup(seed=0)
    state = with_resources(state, 0, food=0)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    sp = state.starting_player
    # Force SP to be player 0 so we drive their FEED.
    if sp != 0:
        # Swap pendings so player 0 is on top.
        state = dataclasses.replace(
            state, pending_stack=tuple(reversed(state.pending_stack)),
            starting_player=0,
        )
    actions = legal_actions(state)
    convert_actions = [a for a in actions if isinstance(a, CommitConvert)]
    # Only one possible config: consume nothing.
    assert convert_actions == [CommitConvert(0, 0, 0, 0, 0)]

    state = step(state, convert_actions[0])
    assert state.players[0].begging_markers == 4


# --- Grain conversion -------------------------------------------------------

def test_grain_1to1_conversion():
    """3 grain, food_owed=2, no cooking. food_payment_frontier yields three
    REMAINING points: keep 3 (consume 0), keep 2 (consume 1), keep 1 (consume 2)."""
    state = setup(seed=0)
    # Set up player 0 with the specific scenario; force SP to be 0.
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=0, grain=3)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    state = _force_food_owed(state, 0, 2)

    actions = legal_actions(state)
    convert_actions = {(a.grain, a.veg, a.sheep, a.boar, a.cattle)
                       for a in actions if isinstance(a, CommitConvert)}
    # consume 0 = beg 2; consume 1 = beg 1; consume 2 = full pay
    assert convert_actions == {(0, 0, 0, 0, 0), (1, 0, 0, 0, 0), (2, 0, 0, 0, 0)}

    # Pick consume-2-grain (full pay) -> 1 grain remains, 0 begging.
    state = step(state, CommitConvert(grain=2, veg=0, sheep=0, boar=0, cattle=0))
    assert state.players[0].resources.grain == 1
    assert state.players[0].begging_markers == 0


# --- Veg conversion ---------------------------------------------------------

def test_veg_no_cooking_one_to_one():
    """2 veg, food_owed=2, no cooking (veg rate=1)."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=0, veg=2)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    state = _force_food_owed(state, 0, 2)

    state = step(state, CommitConvert(grain=0, veg=2, sheep=0, boar=0, cattle=0))
    assert state.players[0].resources.veg == 0
    assert state.players[0].begging_markers == 0


def test_veg_with_fireplace_rate_two():
    """1 veg, food_owed=2, Fireplace (veg rate=2)."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={0: 0})  # Fireplace
    state = with_resources(state, 0, food=0, veg=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    state = _force_food_owed(state, 0, 2)

    state = step(state, CommitConvert(grain=0, veg=1, sheep=0, boar=0, cattle=0))
    assert state.players[0].resources.veg == 0
    assert state.players[0].begging_markers == 0


def test_veg_with_cooking_hearth_rate_three():
    """1 veg, food_owed=3, Cooking Hearth (veg rate=3)."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={2: 0})  # Cooking Hearth
    state = with_resources(state, 0, food=0, veg=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    state = _force_food_owed(state, 0, 3)

    state = step(state, CommitConvert(grain=0, veg=1, sheep=0, boar=0, cattle=0))
    assert state.players[0].resources.veg == 0
    assert state.players[0].begging_markers == 0


# --- Craft conversions ------------------------------------------------------

def test_joinery_use_true_reduces_food_owed():
    """Player owns Joinery (idx 7) and has 1 wood. food_owed=4. Firing
    Joinery costs 1 wood, produces 2 food (all goes to food_owed).
    """
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0})  # Joinery
    state = with_resources(state, 0, food=0, wood=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    state = _force_food_owed(state, 0, 4)

    # Both use=False and use=True should be legal.
    actions = legal_actions(state)
    joinery_actions = [a for a in actions if isinstance(a, CommitHarvestConversion)
                       and a.conversion_id == "joinery"]
    assert CommitHarvestConversion(conversion_id="joinery", use=True) in joinery_actions
    assert CommitHarvestConversion(conversion_id="joinery", use=False) in joinery_actions

    state = step(state, CommitHarvestConversion(conversion_id="joinery", use=True))

    # 1 wood spent; food_owed reduced from 4 to 2; supply.food unchanged.
    assert state.players[0].resources.wood == 0
    assert state.players[0].resources.food == 0
    assert "joinery" in state.players[0].harvest_conversions_used
    # Joinery no longer offered.
    actions = legal_actions(state)
    joinery_actions = [a for a in actions if isinstance(a, CommitHarvestConversion)
                       and a.conversion_id == "joinery"]
    assert joinery_actions == []
    # The pending's food_owed reflects the reduction.
    assert _top_pending(state).food_owed == 2


def test_joinery_unaffordable_only_use_false():
    """Player owns Joinery but has 0 wood -> only use=False is legal."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0})  # Joinery
    state = with_resources(state, 0, food=0, wood=0)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    state = _force_food_owed(state, 0, 4)

    actions = legal_actions(state)
    joinery_actions = [a for a in actions if isinstance(a, CommitHarvestConversion)
                       and a.conversion_id == "joinery"]
    assert joinery_actions == [CommitHarvestConversion(conversion_id="joinery", use=False)]


def test_joinery_still_offered_when_food_owed_zero():
    """Even when food_owed=0, the agent CAN fire Joinery (the food goes to
    surplus). Once-per-harvest budget — no preservation of optionality."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0})  # Joinery
    state = with_resources(state, 0, food=99, wood=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    # food_owed should already be 0 after pre-debit.
    assert _top_pending(state).food_owed == 0

    actions = legal_actions(state)
    joinery_actions = [a for a in actions if isinstance(a, CommitHarvestConversion)
                       and a.conversion_id == "joinery"]
    assert CommitHarvestConversion(conversion_id="joinery", use=True) in joinery_actions


def test_joinery_fires_food_to_surplus_when_overpays():
    """Joinery fires (2 food) when food_owed=1. 1 -> owed, 1 -> surplus."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0})
    state = with_resources(state, 0, food=0, wood=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    state = _force_food_owed(state, 0, 1)

    state = step(state, CommitHarvestConversion(conversion_id="joinery", use=True))
    assert state.players[0].resources.food == 1   # 1 surplus
    assert _top_pending(state).food_owed == 0


def test_multiple_crafts_all_offered():
    """Owning all 3 crafts -> the enumerator offers all 6 craft actions
    (use=True/False × 3) plus the conversion frontier."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0, 8: 0, 9: 0})  # Joinery + Pottery + Basket
    state = with_resources(state, 0, food=0, wood=1, clay=1, reed=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    actions = legal_actions(state)
    craft_ids_seen = {(a.conversion_id, a.use) for a in actions
                      if isinstance(a, CommitHarvestConversion)}
    assert craft_ids_seen == {
        ("joinery", True), ("joinery", False),
        ("pottery", True), ("pottery", False),
        ("basketmaker", True), ("basketmaker", False),
    }


# --- conversion_done & Stop gating ------------------------------------------

def test_stop_illegal_before_convert():
    """Stop is not in legal_actions before CommitConvert."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=10)
    state = with_resources(state, 1, food=10)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    actions = legal_actions(state)
    assert Stop() not in actions


def test_stop_only_legal_after_convert():
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=10)
    state = with_resources(state, 1, food=10)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert legal_actions(state) == [Stop()]


# --- Push order -------------------------------------------------------------

def test_push_order_sp_on_top():
    """starting_player=1 -> player 1's pending on top first."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=1)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    assert state.pending_stack[-1].player_idx == 1
    assert state.pending_stack[0].player_idx == 0


def test_push_order_drives_alternation_via_stop():
    """After SP Stops, the non-SP's frame is on top."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=1)
    state = with_resources(state, 0, food=99)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    # SP (player 1) does the gratuitous CommitConvert + Stop.
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    state = step(state, Stop())

    # Player 0's frame is now on top.
    assert state.pending_stack[-1].player_idx == 0


# --- Pareto invariants ------------------------------------------------------

def test_pareto_excludes_over_conversion():
    """3 grain, food_owed=2, no cooking. (consume 3) would over-convert and
    is dominated by (consume 2) on grain dim — should NOT be in legal actions."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=0, grain=3)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)
    state = _force_food_owed(state, 0, 2)

    actions = legal_actions(state)
    convert_grains = {a.grain for a in actions if isinstance(a, CommitConvert)}
    assert 3 not in convert_grains   # over-conversion pruned
    assert {0, 1, 2} <= convert_grains
