"""Tests for Elephantgrass Plant (minor improvement, C34; Corbarius Expansion).

Card text (verbatim): "Immediately after each harvest, you can use this card to
exchange exactly 1 reed for 1 bonus point."
Cost 2 clay, 1 stone. Prereq: 2 occupations. VPs: 0 (printed).

The reed->point swap is an optional TRIGGER on the ``after_harvest`` window
(outside the harvest, strictly after ``end_of_harvest``; ruling 2026-07-03 —
and per the 2026-07-05 ruling "immediately after each harvest" is the SAME
instant as "after each harvest", one window). Firing it spends exactly 1 reed
and banks 1 bonus point (no food); declining is the window frame's ``Proceed``.
Bonus points are banked in the CardStore and read by the scoring term at end-game.

Mis-timing history: the swap previously rode the ``HARVEST_CONVERSIONS`` seam,
surfacing during the FEED sub-phase. It has been migrated to the after-harvest
window per the printed "immediately after each harvest" and the 2026-07-03
ruling. These tests drive the REAL harvest walk and assert the swap surfaces at
the ``after_harvest`` window, never during feeding.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.elephantgrass_plant  # noqa: F401  (register the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.elephantgrass_plant import CARD_ID
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed, PendingHarvestWindow
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.state import GameState
from agricola.setup import setup

from tests.factories import with_minors, with_phase, with_resources


# --- Helpers ----------------------------------------------------------------

def _with_occupations(state, player_idx, occupations: frozenset):
    """Give a player a set of (dummy) occupation card ids — only the COUNT is
    read by prereq_met, so the ids need not be registered."""
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=occupations)
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _harvest_state(*, reed=0, food=10, owned=True) -> GameState:
    """A HARVEST_FIELD-phase state with P0 owning Elephantgrass Plant, given
    reed/food; P1 food-rich so only P0's frames are interesting."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    if owned:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=food, reed=reed)
    state = with_resources(state, 1, food=99)
    return state


def _walk_to_after_harvest(state):
    """Drive the harvest walk until P0's after_harvest window frame is
    on top. Returns (state, swap_ever_offered_in_feeding)."""
    saw_swap_in_feeding = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed):
            if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state)):
                saw_swap_in_feeding = True
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "after_harvest"
                and top.player_idx == 0):
            return state, saw_swap_in_feeding
        state = step(state, legal_actions(state)[0])
    return state, saw_swap_in_feeding


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(clay=2, stone=1)
    assert spec.min_occupations == 2
    assert spec.vps == 0
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)
    # Migrated off HARVEST_CONVERSIONS onto the after_harvest window.
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("after_harvest", set())
    assert any(e.card_id == CARD_ID
               for e in TRIGGERS.get("after_harvest", ()))


def test_no_longer_on_harvest_conversions():
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
    assert CARD_ID not in HARVEST_CONVERSIONS


# --- Prerequisite -----------------------------------------------------------

def test_prereq_requires_two_occupations():
    spec = MINORS[CARD_ID]
    state = setup(seed=0)
    state = _with_occupations(state, 0, frozenset())
    assert prereq_met(spec, state, 0) is False
    state = _with_occupations(state, 0, frozenset({"a"}))
    assert prereq_met(spec, state, 0) is False
    state = _with_occupations(state, 0, frozenset({"a", "b"}))
    assert prereq_met(spec, state, 0) is True
    state = _with_occupations(state, 0, frozenset({"a", "b", "c"}))
    assert prereq_met(spec, state, 0) is True


# --- The swap surfaces at after_harvest (not feeding) ------------

def test_swap_surfaces_at_after_harvest_not_feeding():
    state, saw_swap_in_feeding = _walk_to_after_harvest(
        _harvest_state(reed=1))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "after_harvest"
    assert top.player_idx == 0
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)
    assert not saw_swap_in_feeding


def test_fire_spends_one_reed_banks_one_point_no_food():
    """Fire the swap: spend 1 reed, gain NO food, bank 1 bonus point."""
    state, _ = _walk_to_after_harvest(_harvest_state(reed=2, food=10))
    food0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))
    p = state.players[0]
    assert p.resources.reed == 1            # 2 - 1 spent
    assert p.resources.food == food0        # no food added
    assert p.card_state.get(CARD_ID, 0) == 1  # 1 banked point


def test_once_per_harvest():
    """After firing, only Proceed remains this window (even with reed left)."""
    state, _ = _walk_to_after_harvest(_harvest_state(reed=3, food=10))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert legal_actions(state) == [Proceed()]


def test_optional_decline_via_proceed():
    """The swap is optional — Proceed leaves reed/points untouched."""
    state, _ = _walk_to_after_harvest(_harvest_state(reed=2, food=10))
    state = step(state, Proceed())
    p = state.players[0]
    assert p.resources.reed == 2
    assert p.card_state.get(CARD_ID, 0) == 0


# --- Eligibility boundaries -------------------------------------------------

def test_offered_only_when_owned():
    """No frame appears at the window when the player does not own the card."""
    saw_window = False
    state = _harvest_state(reed=1, owned=False)
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "after_harvest"):
            saw_window = True
        state = step(state, legal_actions(state)[0])
    assert not saw_window


def test_offered_only_when_reed_affordable():
    """With 0 reed, eligibility fails and no window frame is pushed for P0."""
    saw_window = False
    state = _harvest_state(reed=0)
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "after_harvest"
                and top.player_idx == 0):
            saw_window = True
        state = step(state, legal_actions(state)[0])
    assert not saw_window


def test_eligibility_gates_on_ownership_and_reed():
    from agricola.cards.elephantgrass_plant import _eligible
    state = _harvest_state(reed=1)
    assert _eligible(state, 0, frozenset()) is True
    # Non-owner seat.
    assert _eligible(state, 1, frozenset()) is False
    # Owner with no reed cannot afford it.
    state0 = with_resources(state, 0, reed=0, food=10)
    assert _eligible(state0, 0, frozenset()) is False


def test_not_offered_to_non_owner():
    """P1 owning the card must not push a window frame for P0."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = with_minors(state, 1, frozenset({CARD_ID}))  # opponent owns it
    state = with_resources(state, 0, reed=5, food=10)
    state = with_resources(state, 1, food=99, reed=5)
    saw_p0_window = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "after_harvest"
                and top.player_idx == 0):
            saw_p0_window = True
        state = step(state, legal_actions(state)[0])
    assert not saw_p0_window


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    score_fn = _score_fn()
    state = setup(seed=0)
    # No bank -> 0.
    assert score_fn(state, 0) == 0
    # Bank 4 points across harvests.
    p = state.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, 4))
    state = dataclasses.replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2))
    )
    assert score_fn(state, 0) == 4
    # Opponent (no bank) scores 0.
    assert score_fn(state, 1) == 0
