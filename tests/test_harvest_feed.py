"""Tests for the HARVEST_FEED resolution (Task 7).

Engine-level integration tests covering PendingHarvestFeed legality
enumeration, CommitHarvestConversion (joinery/pottery/basketmaker),
CommitConvert (Pareto-frontier conversion + final food payment), begging
assignment, and the gratuitous-Stop floor.

Frontier tuples below (from food_payment_frontier / harvest_feed_frontier)
use the REMAINING convention. CommitConvert(...) uses CONSUMED amounts —
inverted from the frontier's REMAINING via consumed = player_max - remaining.

Food-payment semantics: payment is deferred to CommitConvert. The pending
carries no food_owed; food_owed is recomputed dynamically as
max(0, need - p.resources.food) on each legality call. CommitConvert pays
min(need, supply + food_produced) and assigns any shortfall as begging
markers.
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

def _top_pending(state) -> PendingHarvestFeed:
    return state.pending_stack[-1]


# --- No pre-debit & dynamic food_owed ---------------------------------------

def test_init_does_not_debit_food():
    """_initiate_harvest_feed leaves p.resources.food untouched.

    Payment is deferred to CommitConvert.
    """
    state = setup(seed=0)
    state = with_resources(state, 0, food=5)
    state = with_resources(state, 1, food=5)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    assert state.players[0].resources.food == 5
    assert state.players[1].resources.food == 5
    # Pending no longer carries food_owed.
    for f in state.pending_stack:
        assert isinstance(f, PendingHarvestFeed)
        assert not hasattr(f, "food_owed")
        assert f.conversion_done is False


def test_full_food_zero_owed_trivial_commit_keeps_surplus():
    """Player with 5 food, need=4 -> dynamic food_owed=0; CommitConvert(0,0,0,0,0)
    pays 4 from supply, 1 surplus remains."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=5)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    # Only the trivial commit is legal (no convertibles, food_owed=0).
    actions = legal_actions(state)
    assert actions == [CommitConvert(0, 0, 0, 0, 0)]
    state = step(state, actions[0])
    assert state.players[0].resources.food == 1
    assert state.players[0].begging_markers == 0


def test_short_food_shortfall_becomes_begging():
    """Player with 1 food, need=4 -> dynamic food_owed=3; with no convertibles,
    CommitConvert(0,...) pays 1 food and assigns 3 begging markers."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    actions = legal_actions(state)
    assert actions == [CommitConvert(0, 0, 0, 0, 0)]
    state = step(state, actions[0])
    assert state.players[0].resources.food == 0
    assert state.players[0].begging_markers == 3


def test_newborn_discount_reduces_need():
    """newborn from this round: need = 2*people_total - newborns.
    2 adults + 1 newborn -> need = 2*3 - 1 = 5; 0 food, no convertibles -> beg 5."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_people(state, 0, total=3, home=3, newborns=1)
    state = with_resources(state, 0, food=0)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert state.players[0].begging_markers == 5   # 2*3 - 1


# --- Trivial FEED -----------------------------------------------------------

def test_trivial_feed_just_stop():
    """Player with enough food, no convertibles, no crafts -> the only legal
    action is the singleton CommitConvert(0,0,0,0,0); after commit, only Stop."""
    state = setup(seed=0)
    state = with_resources(state, 0, food=10)
    state = with_resources(state, 1, food=10)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    actions = legal_actions(state)
    assert actions == [CommitConvert(grain=0, veg=0, sheep=0, boar=0, cattle=0)]

    state = step(state, actions[0])
    actions = legal_actions(state)
    assert actions == [Stop()]


def test_begging_assignment_no_convertibles():
    """Player with 0 food, need=4, no convertibles -> begging 4 after commit."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=0)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    actions = legal_actions(state)
    convert_actions = [a for a in actions if isinstance(a, CommitConvert)]
    assert convert_actions == [CommitConvert(0, 0, 0, 0, 0)]

    state = step(state, convert_actions[0])
    assert state.players[0].begging_markers == 4


# --- Grain conversion -------------------------------------------------------

def test_grain_1to1_conversion():
    """3 grain, need=2, no cooking. food_owed=2 dynamically.
    food_payment_frontier yields three REMAINING points: keep 3 (consume 0),
    keep 2 (consume 1), keep 1 (consume 2)."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_people(state, 0, total=1, home=1, newborns=0)  # need=2
    state = with_resources(state, 0, food=0, grain=3)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    actions = legal_actions(state)
    convert_actions = {(a.grain, a.veg, a.sheep, a.boar, a.cattle)
                       for a in actions if isinstance(a, CommitConvert)}
    assert convert_actions == {(0, 0, 0, 0, 0), (1, 0, 0, 0, 0), (2, 0, 0, 0, 0)}

    state = step(state, CommitConvert(grain=2, veg=0, sheep=0, boar=0, cattle=0))
    assert state.players[0].resources.grain == 1
    assert state.players[0].begging_markers == 0


# --- Veg conversion ---------------------------------------------------------

def test_veg_no_cooking_one_to_one():
    """2 veg, need=2, no cooking (veg rate=1)."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_people(state, 0, total=1, home=1, newborns=0)  # need=2
    state = with_resources(state, 0, food=0, veg=2)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    state = step(state, CommitConvert(grain=0, veg=2, sheep=0, boar=0, cattle=0))
    assert state.players[0].resources.veg == 0
    assert state.players[0].begging_markers == 0


def test_veg_with_fireplace_rate_two():
    """1 veg, need=2, Fireplace (veg rate=2)."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_people(state, 0, total=1, home=1, newborns=0)
    state = with_majors(state, owner_by_idx={0: 0})  # Fireplace
    state = with_resources(state, 0, food=0, veg=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    state = step(state, CommitConvert(grain=0, veg=1, sheep=0, boar=0, cattle=0))
    assert state.players[0].resources.veg == 0
    assert state.players[0].begging_markers == 0


def test_veg_with_cooking_hearth_rate_three():
    """1 veg, need=3, Cooking Hearth (veg rate=3). 1 newborn, 1 adult -> need=3."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_people(state, 0, total=2, home=2, newborns=1)   # need = 2*2 - 1 = 3
    state = with_majors(state, owner_by_idx={2: 0})  # Cooking Hearth
    state = with_resources(state, 0, food=0, veg=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    state = step(state, CommitConvert(grain=0, veg=1, sheep=0, boar=0, cattle=0))
    assert state.players[0].resources.veg == 0
    assert state.players[0].begging_markers == 0


# --- Craft conversions ------------------------------------------------------

def test_joinery_use_true_adds_food_to_supply():
    """Player owns Joinery (idx 7) and has 1 wood. need=4, food=0.
    Firing Joinery costs 1 wood and adds 2 food to supply (no food_owed
    bookkeeping). After the craft, food_owed = max(0, 4 - 2) = 2.
    """
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0})  # Joinery
    state = with_resources(state, 0, food=0, wood=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    # Both use=False and use=True legal.
    actions = legal_actions(state)
    joinery_actions = [a for a in actions if isinstance(a, CommitHarvestConversion)
                       and a.conversion_id == "joinery"]
    assert CommitHarvestConversion(conversion_id="joinery", use=True) in joinery_actions
    assert CommitHarvestConversion(conversion_id="joinery", use=False) in joinery_actions

    state = step(state, CommitHarvestConversion(conversion_id="joinery", use=True))

    # 1 wood spent; food in supply went from 0 -> 2; once-per-harvest budget marked.
    assert state.players[0].resources.wood == 0
    assert state.players[0].resources.food == 2
    assert "joinery" in state.players[0].harvest_conversions_used
    # Joinery no longer offered.
    actions = legal_actions(state)
    joinery_actions = [a for a in actions if isinstance(a, CommitHarvestConversion)
                       and a.conversion_id == "joinery"]
    assert joinery_actions == []

    # Commit (no further conversion): pays 2 food, begs 2.
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert state.players[0].resources.food == 0
    assert state.players[0].begging_markers == 2


def test_joinery_unaffordable_only_use_false():
    """Player owns Joinery but has 0 wood -> only use=False is legal."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0})  # Joinery
    state = with_resources(state, 0, food=0, wood=0)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    actions = legal_actions(state)
    joinery_actions = [a for a in actions if isinstance(a, CommitHarvestConversion)
                       and a.conversion_id == "joinery"]
    assert joinery_actions == [CommitHarvestConversion(conversion_id="joinery", use=False)]


def test_joinery_still_offered_when_food_owed_zero():
    """Even when food_owed=0 (player has plenty of food), the agent CAN fire
    Joinery — the food simply lands in surplus. Once-per-harvest craft budgets
    are event-bound and surface regardless of the optionality principle."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0})  # Joinery
    state = with_resources(state, 0, food=99, wood=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    actions = legal_actions(state)
    joinery_actions = [a for a in actions if isinstance(a, CommitHarvestConversion)
                       and a.conversion_id == "joinery"]
    assert CommitHarvestConversion(conversion_id="joinery", use=True) in joinery_actions


def test_joinery_fires_food_to_surplus_when_overpays():
    """Joinery fires (2 food) when need=1. food_in_supply goes 0 -> 2.
    After commit: pay 1 food, surplus 1 stays in supply."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_people(state, 0, total=1, home=1, newborns=1)   # need = 2*1 - 1 = 1
    state = with_majors(state, owner_by_idx={7: 0})
    state = with_resources(state, 0, food=0, wood=1)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    state = step(state, CommitHarvestConversion(conversion_id="joinery", use=True))
    assert state.players[0].resources.food == 2     # 2 food just produced
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert state.players[0].resources.food == 1     # paid 1, 1 surplus
    assert state.players[0].begging_markers == 0


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

    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    state = step(state, Stop())

    assert state.pending_stack[-1].player_idx == 0


# --- Pareto invariants ------------------------------------------------------

def test_pareto_excludes_over_conversion():
    """3 grain, need=2, no cooking. (consume 3) would over-convert and
    is dominated by (consume 2) on grain dim — should NOT be in legal actions."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_people(state, 0, total=1, home=1, newborns=0)   # need=2
    state = with_resources(state, 0, food=0, grain=3)
    state = with_resources(state, 1, food=99)
    state = with_phase(state, Phase.HARVEST_FEED)
    state = _initiate_harvest_feed(state)

    actions = legal_actions(state)
    convert_grains = {a.grain for a in actions if isinstance(a, CommitConvert)}
    assert 3 not in convert_grains   # over-conversion pruned
    assert {0, 1, 2} <= convert_grains
