"""Tests for Bellfounder (occupation, D107; Consul Dirigens Expansion).

Card text (verbatim): "In the returning home phase of each round, if you have
at least 1 clay, you can use this card to discard all of your clay and get
your choice of 3 food or 1 bonus point."

The effect rides the round-end ladder's ``returning_home`` window (ruling 49,
2026-07-12) as an optional play-variant trigger, the payout choice surfaced
WIDE (user decision 2026-07-14): FireTrigger variants "food" (+3 food) and
"point" (+1 bonus point banked in the CardStore, read back by the end-game
scoring term — the Big Country banked-VP idiom). Either fire discards ALL the
player's clay; the payout is flat, never per clay. "Each round" includes
harvest rounds (no Silage-style non-harvest carve-out). These tests drive the
REAL round-end walk (`_advance_until_decision` from a drained WORK state).
"""
from __future__ import annotations

import agricola.cards.bellfounder  # noqa: F401  (register the card)

import dataclasses

from agricola.actions import FireTrigger, Proceed
from agricola.cards.bellfounder import CARD_ID, _score, _variants
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup

from tests.factories import with_resources


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _drained_work_state(seed=0, round_number=1):
    """A WORK state with every person placed — the round-end ladder runs next."""
    state = setup(seed)
    state = dataclasses.replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _bellfounder_state(*, clay=0, round_number=1, owned=True, banked=None):
    """A drained WORK state; P0 (optionally) owns Bellfounder with the given
    supply clay (and optionally a pre-banked point count from earlier rounds)."""
    state = _drained_work_state(round_number=round_number)
    p = state.players[0]
    if owned:
        state = _edit_player(state, 0, occupations=p.occupations | {CARD_ID})
    state = with_resources(state, 0, clay=clay)
    if banked is not None:
        p = state.players[0]
        state = _edit_player(state, 0, card_state=p.card_state.set(CARD_ID, banked))
    return state


def _walk_to_window(state):
    """Advance to P0's returning_home window frame (the ladder pauses there)."""
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow), (
        f"no returning_home window surfaced (top={top!r}, phase={state.phase})")
    assert top.window_id == "returning_home" and top.player_idx == 0
    return state


def _bellfounder_fires(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _no_returning_home_pause(state):
    """Advance and assert the walk never pauses at a returning_home window
    (the trigger was ineligible / unowned, so no frame was ever pushed)."""
    state = _advance_until_decision(state)
    assert not any(
        isinstance(f, PendingHarvestWindow) and f.window_id == "returning_home"
        for f in state.pending_stack)
    return state


def _scoring_fn():
    """The card's registered end-game scoring term (subset lookup, never
    exact-set)."""
    fns = [fn for cid, fn in SCORING_TERMS if cid == CARD_ID]
    assert len(fns) == 1
    return fns[0]


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS                 # the occupation spec
    entry = CARDS[CARD_ID]
    assert entry.event == "returning_home"        # ruling 49's rung
    assert entry.mandatory is False               # "you can"
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert _scoring_fn() is _score                # the banked-VP scoring term


# --- The variants (unit) -----------------------------------------------------

def test_variants_both_payouts_with_any_clay():
    assert _variants(_bellfounder_state(clay=1), 0) == ["food", "point"]
    assert _variants(_bellfounder_state(clay=7), 0) == ["food", "point"]


def test_variants_empty_without_clay():
    assert _variants(_bellfounder_state(clay=0), 0) == []


# --- Real-walk fires ----------------------------------------------------------

def test_food_fire_discards_all_clay_for_flat_3_food():
    """With 3 clay, firing "food" discards ALL 3 clay and grants exactly 3
    food — flat, not per clay. Once per round: only Proceed remains, and
    declining it onward reaches PREPARATION."""
    state = _walk_to_window(_bellfounder_state(clay=3))
    assert _bellfounder_fires(state) == [
        FireTrigger(card_id=CARD_ID, variant="food"),
        FireTrigger(card_id=CARD_ID, variant="point"),
    ]
    food_before = state.players[0].resources.food

    state = step(state, FireTrigger(card_id=CARD_ID, variant="food"))
    p = state.players[0]
    assert p.resources.clay == 0                  # ALL the clay discarded
    assert p.resources.food == food_before + 3    # a flat 3 food (not 9)
    assert p.card_state.get(CARD_ID) is None      # nothing banked
    # Once per round: the frame's triggers_resolved swallows a re-offer.
    assert legal_actions(state) == [Proceed()]

    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION       # round 1: no harvest


def test_point_fire_discards_all_clay_and_banks_1_point():
    """With 2 clay, firing "point" discards both clay and banks exactly 1
    bonus point — asserted in the CardStore AND through the registered
    scoring term (the end-game value)."""
    state = _walk_to_window(_bellfounder_state(clay=2))
    food_before = state.players[0].resources.food

    state = step(state, FireTrigger(card_id=CARD_ID, variant="point"))
    p = state.players[0]
    assert p.resources.clay == 0                  # ALL the clay discarded
    assert p.resources.food == food_before        # no food from this payout
    assert p.card_state.get(CARD_ID) == 1         # the banked point
    assert _scoring_fn()(state, 0) == 1           # the scoring term reads it
    assert _scoring_fn()(state, 1) == 0           # the opponent banks nothing
    assert legal_actions(state) == [Proceed()]    # once per round


def test_bank_accumulates_across_rounds():
    """A point banked in an earlier round (pre-set CardStore) plus this
    round's "point" fire = 2 banked points at the scoring term."""
    state = _walk_to_window(_bellfounder_state(clay=1, round_number=2, banked=1))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="point"))
    assert state.players[0].card_state.get(CARD_ID) == 2
    assert _scoring_fn()(state, 0) == 2


# --- Eligibility boundaries ------------------------------------------------------

def test_zero_clay_never_hosts():
    """No clay -> ineligible: the window never pauses and nothing changes."""
    state = _bellfounder_state(clay=0)
    food_before = state.players[0].resources.food
    out = _no_returning_home_pause(state)
    assert out.phase == Phase.PREPARATION
    assert out.players[0].resources.food == food_before
    assert out.players[0].card_state.get(CARD_ID) is None


def test_unowned_never_hosts():
    state = _bellfounder_state(clay=3, owned=False)
    out = _no_returning_home_pause(state)
    assert out.phase == Phase.PREPARATION
    assert out.players[0].resources.clay == 3


def test_hand_only_inert():
    """The card in hand (not played) never hosts the window."""
    state = _bellfounder_state(clay=3, owned=False)
    p = state.players[0]
    state = _edit_player(state, 0, hand_occupations=p.hand_occupations | {CARD_ID})
    out = _no_returning_home_pause(state)
    assert out.players[0].resources.clay == 3
    assert out.players[0].card_state.get(CARD_ID) is None


# --- "Each round" — harvest rounds included, and it fires again next round --------

def test_fires_on_harvest_rounds_too():
    """"Each round" has no non-harvest carve-out: round 4's returning home
    phase (which a harvest follows) still offers the trigger, and after the
    fire + Proceed the walk runs into that harvest."""
    state = _walk_to_window(_bellfounder_state(clay=2, round_number=4))
    food_before = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID, variant="food"))
    p = state.players[0]
    assert p.resources.clay == 0
    assert p.resources.food == food_before + 3
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                           Phase.HARVEST_BREED)


def test_fresh_offer_each_round():
    """A fresh window frame each round re-offers the trigger (the
    once-per-round latch is per frame, not per game): a round-2 walk with new
    clay offers both variants again even after an earlier-round bank."""
    state = _walk_to_window(_bellfounder_state(clay=1, round_number=2, banked=1))
    assert _bellfounder_fires(state) == [
        FireTrigger(card_id=CARD_ID, variant="food"),
        FireTrigger(card_id=CARD_ID, variant="point"),
    ]


# --- Declining / opponent ----------------------------------------------------------

def test_decline_keeps_the_clay():
    state = _walk_to_window(_bellfounder_state(clay=3))
    assert _bellfounder_fires(state) != []        # it was on offer
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    p = state.players[0]
    assert p.resources.clay == 3                  # Proceed keeps the clay
    assert p.card_state.get(CARD_ID) is None
    assert state.phase == Phase.PREPARATION


def test_opponent_unaffected():
    """P1's clay survives P0's fire, and P1 (not owning the card) gets no
    offer of their own."""
    state = _bellfounder_state(clay=3)
    state = with_resources(state, 1, clay=2)
    state = _walk_to_window(state)
    state = step(state, FireTrigger(card_id=CARD_ID, variant="food"))
    assert state.players[1].resources.clay == 2
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION       # no P1 window paused the walk
    assert state.players[1].resources.clay == 2


# --- Labels ----------------------------------------------------------------------

def test_action_labels():
    from agricola.cards.display import variant_label

    assert variant_label(CARD_ID, "food") == "discard all clay → 3 food"
    assert variant_label(CARD_ID, "point") == "discard all clay → 1 bonus point"
