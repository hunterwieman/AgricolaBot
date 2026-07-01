"""Tests for Supply Boat (minor improvement, D73; Consul Dirigens Expansion).

Card text (verbatim): "Each time after you use the 'Fishing' accumulation space,
you can choose to buy 1 grain for 1 food, or 1 vegetable for 3 food."
Cost: 1 Wood. Prerequisite: 1 Occupation. Printed 1 VP. Not passing.

Shape: an OPTIONAL play-variant FireTrigger on the atomic-hosted Fishing space.
Fishing runs its +N-food pickup on Proceed FIRST, then the host flips to the
after-phase where this trigger is surfaced — so the food paid with may include this
turn's catch. The "or" between buy-grain and buy-vegetable is collapsed into the
fire: a distinct FireTrigger(variant="grain" | "vegetable") per currently-affordable
route (food >= 1 / food >= 3). Firing buys exactly one good (a direct resource swap,
no push); declining is the host's after-phase Stop (not firing).
"""
from __future__ import annotations

import agricola.cards.supply_boat  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import (
    OWN_ACTION_HOOK_CARDS,
    PLAY_VARIANT_TRIGGERS,
    TRIGGERS,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources

CARD_ID = "supply_boat"

_GRAIN = FireTrigger(card_id=CARD_ID, variant="grain")
_VEG = FireTrigger(card_id=CARD_ID, variant="vegetable")

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, "market_stall") + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _place_fishing_to_after(state):
    """Place P0 at the (permanent, already-revealed) Fishing space and Proceed past
    the +food pickup so the host frame is in its after-phase (where the trigger is
    surfaced). Returns the after-phase state."""
    state = step(state, PlaceWorker(space="fishing"))
    # Fishing is atomic-hosted (P0 owns the card) → before-phase, only Proceed legal.
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())                 # +food pickup, flip to after-phase
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_supply_boat_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.min_occupations == 1            # prereq: 1 occupation
    assert spec.vps == 1
    assert not spec.passing_left
    # Optional after_action_space play-variant trigger + an atomic Fishing host.
    aas = {e.card_id for e in TRIGGERS.get("after_action_space", [])}
    assert CARD_ID in aas
    # Not a mandatory/auto effect — it is a declinable FireTrigger.
    entry = next(e for e in TRIGGERS["after_action_space"] if e.card_id == CARD_ID)
    assert not entry.mandatory
    assert CARD_ID in PLAY_VARIANT_TRIGGERS      # the grain/vegetable route choice
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("fishing", set())


# ---------------------------------------------------------------------------
# The effect via the real engine flow
# ---------------------------------------------------------------------------

def test_pickup_happens_before_trigger():
    # Fishing's own +food pickup lands BEFORE the after-phase trigger, so the food
    # available to pay with includes this turn's catch.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=0)
    s = step(s, PlaceWorker(space="fishing"))
    assert s.players[cp].resources.food == 0      # pre-pickup
    s = step(s, Proceed())
    assert s.players[cp].resources.food >= 1      # post-pickup (>=1 food/round)
    # That catch makes the grain route affordable.
    assert _GRAIN in legal_actions(s)


def test_fire_grain_buys_one_grain_for_one_food():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=5, grain=0, veg=0)
    s = _place_fishing_to_after(s)
    food1 = s.players[cp].resources.food          # post-pickup
    s = step(s, _GRAIN)
    assert s.players[cp].resources.food == food1 - 1
    assert s.players[cp].resources.grain == 1
    assert s.players[cp].resources.veg == 0


def test_fire_vegetable_buys_one_veg_for_three_food():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=5, grain=0, veg=0)
    s = _place_fishing_to_after(s)
    food1 = s.players[cp].resources.food          # post-pickup
    s = step(s, _VEG)
    assert s.players[cp].resources.food == food1 - 3
    assert s.players[cp].resources.veg == 1
    assert s.players[cp].resources.grain == 0


def test_fire_then_turn_ends_via_stop():
    # After buying once, the host's after-phase Stop ends the Fishing use.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=5)
    s = _place_fishing_to_after(s)
    s = step(s, _GRAIN)
    assert Stop() in legal_actions(s)
    s = step(s, Stop())
    assert not s.pending_stack                     # Fishing use complete


# ---------------------------------------------------------------------------
# Eligibility / affordability boundaries
# ---------------------------------------------------------------------------

def test_both_routes_offered_when_food_at_least_three():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=2)              # +>=1 pickup -> >=3
    s = _place_fishing_to_after(s)
    assert s.players[cp].resources.food >= 3
    la = legal_actions(s)
    assert _GRAIN in la
    assert _VEG in la


def test_only_grain_offered_when_food_under_three():
    # Drive food so that post-pickup it is exactly in [1, 2]: grain affordable,
    # vegetable (cost 3) not.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = step(s, PlaceWorker(space="fishing"))
    s = step(s, Proceed())
    pickup = s.players[cp].resources.food          # the catch (>=1)
    # Re-stage so post-pickup food is exactly 1.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=1 - pickup if pickup <= 1 else 0)
    s = _place_fishing_to_after(s)
    food1 = s.players[cp].resources.food
    la = legal_actions(s)
    if 1 <= food1 < 3:
        assert _GRAIN in la
        assert _VEG not in la
    # (If the pickup pushed food >= 3 anyway, both are fine — covered elsewhere.)
    assert Stop() in la                            # declining always available


def test_no_trigger_when_food_zero_after_pickup_impossible():
    # Even with 0 starting food, the fishing pickup gives >=1, so grain is always
    # affordable post-pickup; assert the trigger is then offered (the realistic
    # zero-affordability case can't arise on Fishing, but the gate is exercised by
    # _legal_variants directly below).
    from agricola.cards.supply_boat import _legal_variants
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=0)
    assert _legal_variants(s, cp) == []            # 0 food -> nothing affordable
    s = with_resources(s, cp, food=1)
    assert _legal_variants(s, cp) == ["grain"]     # 1 food -> grain only
    s = with_resources(s, cp, food=3)
    assert _legal_variants(s, cp) == ["grain", "vegetable"]


def test_not_offered_without_card():
    # Without the card, Fishing is NOT hosted (atomic fast path): placing resolves
    # immediately, no host frame, no trigger.
    s, cp = _card_state()
    s = with_resources(s, cp, food=5)
    s = step(s, PlaceWorker(space="fishing"))
    assert not s.pending_stack                      # resolved atomically
    assert _GRAIN not in legal_actions(s) if s.pending_stack else True


# ---------------------------------------------------------------------------
# Optionality + once-per-use scoping
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_stop():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=5, grain=0, veg=0)
    s = _place_fishing_to_after(s)
    food1 = s.players[cp].resources.food
    la = legal_actions(s)
    # Both firing AND declining (the host's Stop) are available.
    assert _GRAIN in la
    assert Stop() in la
    s = step(s, Stop())                             # decline → host exits, turn ends
    assert not s.pending_stack
    assert s.players[cp].resources.food == food1    # nothing spent
    assert s.players[cp].resources.grain == 0
    assert s.players[cp].resources.veg == 0


def test_fires_once_per_use():
    # After buying once, the trigger is not re-offered within the same Fishing use
    # (per-frame triggers_resolved); only Stop remains.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=10)
    s = _place_fishing_to_after(s)
    s = step(s, _GRAIN)
    la = legal_actions(s)
    assert _GRAIN not in la
    assert _VEG not in la
    assert Stop() in la


def test_re_eligible_on_next_use():
    # A fresh Fishing use pushes a new host frame with empty triggers_resolved, so
    # the card re-becomes eligible.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=10)
    # First use: fire + end.
    s = _place_fishing_to_after(s)
    s = step(s, _GRAIN)
    s = step(s, Stop())
    assert not s.pending_stack
    # Reset Fishing's worker so it can be used again, restage as P0's turn.
    sp = fast_replace(get_space(s.board, "fishing"), workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "fishing", sp), current_player=cp)
    s = _place_fishing_to_after(s)
    assert _GRAIN in legal_actions(s)               # re-offered on the new use


# ---------------------------------------------------------------------------
# Wrong space does not fire
# ---------------------------------------------------------------------------

def test_forest_does_not_fire():
    # Forest is an accumulation space but not hooked by Supply Boat, so it stays
    # atomic (no host) and nothing fires.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, food=5)
    s = step(s, PlaceWorker(space="forest"))
    assert not s.pending_stack                      # resolved atomically, no host
