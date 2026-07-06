"""Tests for Value Assets (minor improvement, B82; Bubulcus Expansion).

Card text (verbatim, from agricola/cards/data/revised_minor_improvements.json):
"After each harvest, you can buy exactly one of the following goods: 1 Food →
1 Wood; 1 Food → 1 Clay; 2 Food → 1 Reed; 2 Food → 1 Stone"
No cost. No prerequisite. VPs: 0 (printed blank). Not passing.

Implemented as an OPTIONAL PLAY-VARIANT TRIGGER on the ``after_harvest``
window (per user ruling 18, 2026-07-05, "immediately after each harvest" =
"after each harvest" — ONE window, shared with Elephantgrass Plant). Four
purchase variants whose prices DIFFER per output (wood/clay 1 food, reed/stone
2 food), affordability-filtered per variant; firing one buys exactly one good,
once per harvest (the frame's ``triggers_resolved``).

These tests drive REAL harvests through the walk (mirroring
tests/test_card_elephantgrass_plant.py), reaching the per-player
``PendingHarvestWindow`` for ``after_harvest`` — including the shared-window
interaction with Elephantgrass Plant (buy a reed, then swap it for the bonus
point) and the final-harvest (round 14) firing.
"""
from __future__ import annotations

import dataclasses

import pytest

import agricola.cards.value_assets  # noqa: F401  (register the card)
import agricola.cards.elephantgrass_plant  # noqa: F401  (the shared-window partner)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.value_assets import CARD_ID, WINDOW_ID, _PURCHASES
from agricola.cards.elephantgrass_plant import CARD_ID as ELEPHANTGRASS_ID
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed, PendingHarvestWindow
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import GameState

from tests.factories import with_minors, with_phase, with_resources, with_round


# --- Helpers ----------------------------------------------------------------

def _harvest_state(*, food=10, reed=0, owned=True, with_elephantgrass=False,
                   round_number=None) -> GameState:
    """A HARVEST_FIELD-phase state with P0 owning Value Assets (optionally also
    Elephantgrass Plant), given food/reed; P1 food-rich so only P0's frames are
    interesting. Feeding costs P0 4 food (2 adults), so the food surviving to
    the after_harvest window is ``food - 4``."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    if round_number is not None:
        state = with_round(state, round_number)
    minors = set()
    if owned:
        minors.add(CARD_ID)
    if with_elephantgrass:
        minors.add(ELEPHANTGRASS_ID)
    state = with_minors(state, 0, frozenset(minors))
    state = with_resources(state, 0, food=food, reed=reed)
    state = with_resources(state, 1, food=99)
    return state


def _walk_to_after_harvest(state):
    """Drive the harvest walk until P0's after_harvest window frame is on top.
    Returns (state, purchase_ever_offered_in_feeding)."""
    saw_purchase_in_feeding = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed):
            if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state)):
                saw_purchase_in_feeding = True
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == WINDOW_ID
                and top.player_idx == 0):
            return state, saw_purchase_in_feeding
        state = step(state, legal_actions(state)[0])
    return state, saw_purchase_in_feeding


def _fire_variants(acts, card_id=CARD_ID):
    return sorted(a.variant for a in acts
                  if isinstance(a, FireTrigger) and a.card_id == card_id)


# --- Registration (spec vs the JSON row) ------------------------------------

def test_registration_spec_matches_json():
    """JSON row B82: cost null, vps null (printed blank -> 0), prereq null,
    passing_left null."""
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources()      # no cost
    assert spec.cost.animals == type(spec.cost.animals)()
    assert spec.alt_costs == ()
    assert spec.vps == 0
    assert spec.prereq is None
    assert spec.min_occupations == 0 and spec.max_occupations is None
    assert spec.passing_left is False


def test_registered_as_after_harvest_play_variant_trigger():
    """Optional (declinable) play-variant trigger on the after_harvest window
    — NOT an automatic effect (the text is "you can")."""
    entry = CARDS[CARD_ID]
    assert entry.event == WINDOW_ID == "after_harvest"
    assert entry.mandatory is False
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("after_harvest", set())


def test_purchase_table_matches_printed_text():
    """The four printed exchange rates, exactly: 1F->1W; 1F->1C; 2F->1R; 2F->1S."""
    assert _PURCHASES == {
        "wood":  (1, Resources(wood=1)),
        "clay":  (1, Resources(clay=1)),
        "reed":  (2, Resources(reed=1)),
        "stone": (2, Resources(stone=1)),
    }


# --- The trigger surfaces at the after_harvest window ------------------------

def test_surfaces_at_after_harvest_window_not_feeding():
    """With plenty of food (10 - 4 feeding = 6), all four variants are offered
    at P0's after_harvest window frame — and never during feeding."""
    state, saw_in_feeding = _walk_to_after_harvest(_harvest_state(food=10))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "after_harvest" and top.player_idx == 0
    acts = legal_actions(state)
    assert _fire_variants(acts) == sorted(_PURCHASES)
    assert Proceed() in acts                       # declinable ("you can")
    assert not saw_in_feeding


# --- Each variant's exact debit/credit ---------------------------------------

@pytest.mark.parametrize("tag,price,field", [
    ("wood", 1, "wood"),
    ("clay", 1, "clay"),
    ("reed", 2, "reed"),
    ("stone", 2, "stone"),
])
def test_variant_debits_price_credits_one_good(tag, price, field):
    state, _ = _walk_to_after_harvest(_harvest_state(food=10))
    before = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID, variant=tag))
    r = state.players[0].resources
    assert r.food == before.food - price
    assert getattr(r, field) == getattr(before, field) + 1
    # Every other good is untouched.
    for other in ("wood", "clay", "reed", "stone", "grain", "veg"):
        if other != field:
            assert getattr(r, other) == getattr(before, other)


# --- Affordability filtering (prices differ per variant) ---------------------

def test_one_food_offers_only_wood_and_clay():
    """food=5 -> exactly 1 food survives feeding -> only the 1-food variants
    (wood, clay) are offered; reed and stone (2 food) are not."""
    state, _ = _walk_to_after_harvest(_harvest_state(food=5))
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    assert state.players[0].resources.food == 1
    assert _fire_variants(legal_actions(state)) == ["clay", "wood"]


def test_no_food_no_trigger_no_frame():
    """food=4 -> feeding consumes it all -> nothing affordable -> the trigger
    is never eligible and (nothing else being registered for P0) no
    after_harvest frame is pushed at all; the harvest runs to completion."""
    end, _ = _walk_to_after_harvest(_harvest_state(food=4))
    assert end.phase == Phase.PREPARATION          # frame never appeared
    assert end.players[0].resources.food == 0


def test_variants_fn_filters_per_price():
    """Direct unit check of the per-variant price filter."""
    from agricola.cards.value_assets import _variants
    state = _harvest_state(food=0)
    assert _variants(state, 0) == []
    state = with_resources(state, 0, food=1)
    assert sorted(_variants(state, 0)) == ["clay", "wood"]
    state = with_resources(state, 0, food=2)
    assert sorted(_variants(state, 0)) == ["clay", "reed", "stone", "wood"]


def test_eligibility_gates_on_ownership_and_food():
    from agricola.cards.value_assets import _eligible
    state = _harvest_state(food=1)
    assert _eligible(state, 0, frozenset()) is True
    # Non-owner seat (P1 has 99 food but does not own the card).
    assert _eligible(state, 1, frozenset()) is False
    # Owner with no food cannot afford even the cheapest variant.
    state0 = with_resources(state, 0, food=0)
    assert _eligible(state0, 0, frozenset()) is False


# --- Once per harvest ("buy exactly one") ------------------------------------

def test_once_per_harvest():
    """After buying one good, no re-offer this window even with food left."""
    state, _ = _walk_to_after_harvest(_harvest_state(food=10))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="wood"))
    assert state.players[0].resources.food == 5    # 6 - 1, plenty left
    assert _fire_variants(legal_actions(state)) == []
    assert legal_actions(state) == [Proceed()]


# --- Optionality: declining grants nothing -----------------------------------

def test_decline_via_proceed_grants_nothing():
    state, _ = _walk_to_after_harvest(_harvest_state(food=10))
    before = state.players[0].resources
    state = step(state, Proceed())
    assert state.players[0].resources == before


# --- Ownership boundaries -----------------------------------------------------

def test_unowned_never_offered():
    """No after_harvest frame appears when nobody owns the card."""
    end, _ = _walk_to_after_harvest(_harvest_state(food=10, owned=False))
    assert end.phase == Phase.PREPARATION          # frame never appeared


def test_not_offered_to_non_owner():
    """P1 owning the card must not push an after_harvest frame for P0."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = with_minors(state, 1, frozenset({CARD_ID}))  # opponent owns it
    state = with_resources(state, 0, food=10)
    state = with_resources(state, 1, food=99)
    saw_p0_frame = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "after_harvest"
                and top.player_idx == 0):
            saw_p0_frame = True
        state = step(state, legal_actions(state)[0])
    assert not saw_p0_frame


# --- The Elephantgrass Plant interaction (shared window, ruling 18) ----------

def test_buy_reed_then_feed_it_to_elephantgrass():
    """Ruling 18 (2026-07-05): "immediately after each harvest" = "after each
    harvest" — ONE shared window, so a reedless player can buy a reed via
    Value Assets (2 food) and then swap it to Elephantgrass Plant for the
    bonus point, all within the same frame."""
    # 6 food -> 2 survive feeding; 0 reed.
    state, _ = _walk_to_after_harvest(
        _harvest_state(food=6, reed=0, with_elephantgrass=True))
    acts = legal_actions(state)
    # 2 food affords every variant; Elephantgrass is NOT offered (no reed yet).
    assert _fire_variants(acts) == sorted(_PURCHASES)
    assert FireTrigger(card_id=ELEPHANTGRASS_ID) not in acts

    # Buy the reed: 2 food -> 1 reed.
    state = step(state, FireTrigger(card_id=CARD_ID, variant="reed"))
    p = state.players[0]
    assert p.resources.food == 0 and p.resources.reed == 1
    # The just-bought reed makes Elephantgrass eligible ON THE SAME FRAME.
    acts = legal_actions(state)
    assert FireTrigger(card_id=ELEPHANTGRASS_ID) in acts
    assert _fire_variants(acts) == []              # Value Assets is spent

    # Swap it: 1 reed -> 1 banked bonus point.
    state = step(state, FireTrigger(card_id=ELEPHANTGRASS_ID))
    p = state.players[0]
    assert p.resources.reed == 0
    assert p.card_state.get(ELEPHANTGRASS_ID, 0) == 1
    assert legal_actions(state) == [Proceed()]     # both cards resolved


def test_elephantgrass_first_then_buy_the_reed_back():
    """The other order within the shared frame: swap the held reed to
    Elephantgrass first, then buy a replacement reed with Value Assets."""
    # 6 food -> 2 survive feeding; 1 reed held.
    state, _ = _walk_to_after_harvest(
        _harvest_state(food=6, reed=1, with_elephantgrass=True))
    acts = legal_actions(state)
    assert FireTrigger(card_id=ELEPHANTGRASS_ID) in acts
    assert _fire_variants(acts) == sorted(_PURCHASES)

    state = step(state, FireTrigger(card_id=ELEPHANTGRASS_ID))
    p = state.players[0]
    assert p.resources.reed == 0
    assert p.card_state.get(ELEPHANTGRASS_ID, 0) == 1
    # Value Assets is still live: buy the reed back (2 food).
    state = step(state, FireTrigger(card_id=CARD_ID, variant="reed"))
    p = state.players[0]
    assert p.resources.food == 0 and p.resources.reed == 1
    assert legal_actions(state) == [Proceed()]


# --- The final harvest (round 14) ---------------------------------------------

def test_fires_after_the_final_harvest_before_scoring():
    """"After EACH harvest" includes the last one: the window runs after the
    round-14 harvest, the purchase is offered and works, and the game then
    moves to scoring."""
    state, _ = _walk_to_after_harvest(_harvest_state(food=10, round_number=14))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "after_harvest" and top.player_idx == 0
    before = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID, variant="stone"))
    r = state.players[0].resources
    assert r.food == before.food - 2 and r.stone == before.stone + 1
    state = step(state, Proceed())
    assert state.phase == Phase.BEFORE_SCORING


# --- On-play: no immediate effect ---------------------------------------------

def test_on_play_is_a_noop():
    """Value Assets has no on-play clause: playing it grants nothing
    immediately; the whole effect is the recurring after-harvest purchase."""
    state = setup(0)
    before = state.players[0].resources
    after = MINORS[CARD_ID].on_play(state, 0)
    assert after.players[0].resources == before
