"""Tests for Treegardener (occupation, A118; Artifex Expansion; players 1+).

Card text (verbatim): "In the field phase of each harvest, you get 1 wood and
you can buy up to 2 additional wood for 1 food each."

Two field-phase (harvest window #5, "field_phase") clauses:

1. "you get 1 wood" — a MANDATORY, choice-free auto: fired pre-take by the walk
   via `apply_auto_effects`, per owner per harvest, no frame needed for it.
2. "you can buy up to 2 additional wood for 1 food each" — an OPTIONAL,
   free-ordered, once-per-field-phase play-variant trigger on the
   PendingFieldPhase host: variants "1" (1 food -> 1 wood) and "2" (2 food -> 2
   wood), declinable via Proceed, offered around the mandatory CommitFieldTake in
   any order.

Drivers mirror tests/test_field_phase_window.py and tests/test_card_home_brewer.py:
build a HARVEST_FIELD state, advance to the PendingFieldPhase host for the owner,
then fire / decline around the mandatory take.
"""
import dataclasses

from agricola.actions import CommitFieldTake, FireTrigger, Proceed
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.treegardener import CARD_ID, WINDOW
from agricola.cards.triggers import AUTO_EFFECTS, PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingFieldPhase
from agricola.replace import fast_replace
from agricola.setup import setup

from tests.factories import with_phase, with_resources, with_sown_fields

import agricola.cards.treegardener  # noqa: F401  (ensures registration side effects)


# --- Helpers ----------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = dataclasses.replace(p, occupations=p.occupations | {card_id})
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(*, owner=0, owned=True, food=10, other_food=99, seed=0):
    """A HARVEST_FIELD-phase state; `owner` (optionally) owns Treegardener and has
    `food` food, the other player kept well-fed so feeding never converts."""
    state = setup(seed=seed)
    state = fast_replace(state, starting_player=owner)
    if owned:
        state = _own_occ(state, owner, CARD_ID)
    state = with_resources(state, owner, food=food)
    state = with_resources(state, 1 - owner, food=other_food)
    return with_phase(state, Phase.HARVEST_FIELD)


def _walk_to_field_frame(state, *, owner=0):
    """Advance until the owner's PendingFieldPhase host surfaces (or harvest ends)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingFieldPhase) and top.player_idx == owner:
            return state
        state = step(state, legal_actions(state)[0])
    return state


def _buy_variants(state, *, card_id=CARD_ID):
    """Sorted Treegardener buy-trigger variants currently legal."""
    return sorted(
        a.variant for a in legal_actions(state)
        if isinstance(a, FireTrigger) and a.card_id == card_id
    )


def _run_harvest(state, pick=lambda acts: acts[0]):
    """Drive the harvest to completion (into the next round's reveal)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


# --- Registration -----------------------------------------------------------

def test_registration():
    # Occupation with a no-op on-play (no structured cost/prereq/VP on occupations).
    assert CARD_ID in OCCUPATIONS
    assert WINDOW == "field_phase"
    # Clause 1: an auto on "field_phase".
    assert any(e.card_id == CARD_ID for e in AUTO_EFFECTS.get("field_phase", ()))
    # Clause 2: an optional trigger on "field_phase", with play-variants.
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("field_phase", ()))
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    # The window hook (one call covers both auto and trigger).
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("field_phase", set())


def test_on_play_is_noop():
    """The occupation's on-play does nothing (effect is the recurring field phase)."""
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) is state


# --- Clause 1: the mandatory +1 wood auto -----------------------------------

def test_auto_pays_one_wood_at_field_phase_no_frame_when_food_short():
    """With 0 food (no affordable buy), the +1 wood auto still fires and the field
    phase runs with NO PendingFieldPhase frame — the auto needs no frame."""
    state = _harvest_state(food=0)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    wood0 = state.players[0].resources.wood
    out = _advance_until_decision(state)
    # No field-phase host was ever pushed (no eligible buy trigger at 0 food).
    assert not any(isinstance(f, PendingFieldPhase) for f in out.pending_stack)
    assert out.phase == Phase.HARVEST_FEED
    assert out.players[0].resources.wood == wood0 + 1   # +1 free wood


def test_auto_fires_before_the_take():
    """The +1 wood auto is anchored pre-take (a flat state-reader): it fires
    regardless of what the take harvests, once for the owner."""
    state = _harvest_state(food=0)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)], veg_fields=[(1, 1)])
    wood0 = state.players[0].resources.wood
    grain0 = state.players[0].resources.grain
    out = _advance_until_decision(state)
    assert out.players[0].resources.wood == wood0 + 1   # +1 free wood
    assert out.players[0].resources.grain == grain0 + 1  # the take still happened


def test_auto_owner_gated():
    """The non-owner gets no free wood."""
    state = _harvest_state(owner=0, food=0)              # only player 0 owns it
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    wood1 = state.players[1].resources.wood
    out = _advance_until_decision(state)
    assert out.players[1].resources.wood == wood1       # unchanged


def test_auto_fires_each_harvest():
    """The +1 wood is per harvest: each fresh harvest field phase credits +1 wood
    (two independent fresh HARVEST_FIELD states, mirroring how each real harvest
    re-enters the field phase)."""
    for seed in (0, 1):
        state = _harvest_state(food=0, seed=seed)
        wood0 = state.players[0].resources.wood
        out = _advance_until_decision(state)
        assert out.players[0].resources.wood == wood0 + 1


# --- Clause 2: the buy trigger — offering, before & after the take -----------

def test_buy_offered_both_before_and_after_take():
    """The buy trigger is free-ordered around the mandatory take: offered BEFORE
    the take, still offered AFTER it (with Proceed added), and only one take."""
    state = _harvest_state(food=10)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    assert not top.take_fired

    # BEFORE the take: both buy quantities offered + the mandatory take; no Proceed.
    acts = legal_actions(state)
    assert CommitFieldTake() in acts
    assert _buy_variants(state) == ["1", "2"]
    assert Proceed() not in acts

    # Take the crop, then confirm the buy is STILL offered (free order) + Proceed.
    state = step(state, CommitFieldTake())
    assert state.pending_stack[-1].take_fired
    assert CommitFieldTake() not in legal_actions(state)  # one take only
    assert _buy_variants(state) == ["1", "2"]
    assert Proceed() in legal_actions(state)


def test_buy_offered_before_take_then_take_after():
    """Firing the buy BEFORE the take leaves the take still owed (no Proceed yet)."""
    state = _harvest_state(food=10)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    wood = state.players[0].resources.wood
    food = state.players[0].resources.food

    state = step(state, FireTrigger(card_id=CARD_ID, variant="1"))
    assert state.players[0].resources.wood == wood + 1
    assert state.players[0].resources.food == food - 1
    # Take still owed; no Proceed, no re-offer of the (spent) buy.
    assert legal_actions(state) == [CommitFieldTake()]


# --- Clause 2: the buy spends food correctly at each quantity ----------------

def test_buy_one_wood_for_one_food():
    state = _harvest_state(food=10)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    wood = state.players[0].resources.wood
    food = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID, variant="1"))
    assert state.players[0].resources.wood == wood + 1
    assert state.players[0].resources.food == food - 1


def test_buy_two_wood_for_two_food():
    state = _harvest_state(food=10)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    wood = state.players[0].resources.wood
    food = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID, variant="2"))
    assert state.players[0].resources.wood == wood + 2
    assert state.players[0].resources.food == food - 2


# --- Clause 2: once per field phase -----------------------------------------

def test_buy_is_once_per_field_phase():
    """"up to 2" is ONE buying decision — after firing at any quantity the buy is
    not re-offered this window (not two independent uses)."""
    state = _harvest_state(food=10)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    assert _buy_variants(state) == ["1", "2"]

    state = step(state, FireTrigger(card_id=CARD_ID, variant="1"))
    # Even with plenty of food remaining, the card is spent for this field phase.
    assert _buy_variants(state) == []
    # Only the mandatory take remains (then Proceed).
    assert legal_actions(state) == [CommitFieldTake()]


def test_buy_two_variant_also_spends_the_use():
    state = _harvest_state(food=10)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    state = step(state, FireTrigger(card_id=CARD_ID, variant="2"))
    assert _buy_variants(state) == []


# --- Clause 2: eligibility boundaries (food-short gating) ---------------------

def test_buy_food_short_offers_only_affordable_quantity():
    """With exactly 1 food, only the "1" variant is affordable ("2" needs 2 food)."""
    state = _harvest_state(food=1)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    assert _buy_variants(state) == ["1"]


def test_buy_not_offered_with_zero_food():
    """With 0 food no buy is affordable, so no PendingFieldPhase host is pushed
    (the +1 wood auto still fires — see test_auto_pays_one_wood_...)."""
    state = _harvest_state(food=0)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    out = _walk_to_field_frame(state)
    # The owner's field-phase host never surfaced (harvest walked past it).
    assert not (out.pending_stack
                and isinstance(out.pending_stack[-1], PendingFieldPhase)
                and out.pending_stack[-1].player_idx == 0)


# --- Clause 2: owner gating --------------------------------------------------

def test_buy_not_offered_when_unowned():
    """A player who does not own Treegardener is never offered the buy (and gets
    no free wood)."""
    state = _harvest_state(owned=False, food=10)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    wood0 = state.players[0].resources.wood
    out = _run_harvest(state)
    # Never offered across the whole harvest.
    assert out.phase not in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)
    # No free wood either (the auto is owner-gated too; the take itself yields
    # only grain/veg, never wood).
    assert out.players[0].resources.wood == wood0


# --- Clause 2: declinable -----------------------------------------------------

def test_buy_declinable_via_proceed():
    """Take the crop, then Proceed (decline the buy): food/points untouched beyond
    the free +1 wood; harvest completes."""
    state = _harvest_state(food=10)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    wood = state.players[0].resources.wood     # already includes the +1 auto wood
    food = state.players[0].resources.food
    state = step(state, CommitFieldTake())
    state = step(state, Proceed())             # decline the buy
    out = _advance_until_decision(state)
    assert out.players[0].resources.wood == wood     # no bought wood
    assert out.players[0].resources.food == food     # no food spent on the buy


def test_declining_via_full_harvest_run_only_grants_free_wood():
    """Running the whole harvest always picking Proceed fires only the +1 wood auto
    (the buy never fires), never during feeding."""
    state = _harvest_state(food=10)
    wood0 = state.players[0].resources.wood
    food0 = state.players[0].resources.food

    def pick(acts):
        # Take when owed; otherwise prefer Proceed; never fire the buy trigger.
        for a in acts:
            if isinstance(a, CommitFieldTake):
                return a
        for a in acts:
            if isinstance(a, Proceed):
                return a
        # No buy trigger should be picked here.
        assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID for a in acts)
        return acts[0]

    out = _run_harvest(state, pick=pick)
    assert out.players[0].resources.wood == wood0 + 1   # only the free wood
    # Feeding cost exactly 4 food (2 people x 2 food); nothing beyond that was
    # spent, so the declined buy debited no food.
    assert out.players[0].resources.food == food0 - 4


# --- Timing: the buy is NOT offered during feeding ---------------------------

def test_buy_not_offered_during_feeding():
    """The buy lives on the field phase — declining it, it is NOT re-offered in the
    feeding phase."""
    state = _harvest_state(food=10)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _walk_to_field_frame(state)
    state = step(state, CommitFieldTake())
    state = step(state, Proceed())             # decline the field-phase buy
    # Drive the rest of the harvest; the buy is never offered again.
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        assert _buy_variants(state) == []
        state = step(state, legal_actions(state)[0])
