"""Tests for Transactor (occupation, D98; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "Immediately before the final harvest at the end of round
14, you can take all the building resources that are left on the entire game
board."

An optional TRIGGER on harvest window #1 ``immediately_before_harvest``, gated on
``state.round_number == 14`` (each round's harvest resolves while round_number
still equals that round; round 14's is the final harvest). Firing it sweeps every
action space's ``accumulated`` building resources (wood/clay/reed/stone) into the
owner's supply and zeroes the board; food/animal accumulation (the scalar
``accumulated_amount``) is not a building resource and is untouched. Declining is
the window frame's ``Proceed``.

These tests drive the REAL harvest walk (``_advance_until_decision`` + ``step``)
per the harvest-window test convention (see tests/test_harvest_windows.py).
"""
from __future__ import annotations

import dataclasses

import agricola.cards.transactor  # noqa: F401  (register the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import get_space

from tests.factories import with_phase, with_resources, with_round, with_space

CARD_ID = "transactor"
WINDOW_ID = "immediately_before_harvest"

_BUILDING_SPACES = ("forest", "clay_pit", "reed_bank",
                    "western_quarry", "eastern_quarry")


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, player_idx):
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _stock_board(state):
    """Put a known spread of building resources on the five accumulation spaces
    (revealing the stage quarries so the layout is reachable in a real game),
    plus 2 food on fishing — which is NOT a building resource."""
    state = with_space(state, "forest", accumulated=Resources(wood=6))
    state = with_space(state, "clay_pit", accumulated=Resources(clay=3))
    state = with_space(state, "reed_bank", accumulated=Resources(reed=2))
    state = with_space(state, "western_quarry",
                       accumulated=Resources(stone=2), revealed=True)
    state = with_space(state, "eastern_quarry",
                       accumulated=Resources(stone=1), revealed=True)
    state = with_space(state, "fishing", accumulated_amount=2)
    return state


def _empty_board(state):
    for sid in _BUILDING_SPACES:
        state = with_space(state, sid, accumulated=Resources())
    return state


def _harvest_state(*, round_number=14, give_occ=True, stocked=True):
    """A HARVEST_FIELD-phase state at `round_number`. P0 owns Transactor (unless
    give_occ is False); both players are food-rich so feeding is painless."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = with_round(state, round_number)
    if give_occ:
        state = _give_occupation(state, 0)
    state = _stock_board(state) if stocked else _empty_board(state)
    state = with_resources(state, 0, food=10)
    state = with_resources(state, 1, food=99)
    return state


def _at_window_frame(state):
    """Advance to the harvest's first decision and assert it is P0's
    immediately_before_harvest window frame."""
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == WINDOW_ID
    assert top.player_idx == 0
    return state


def _drive_harvest_collecting_offers(state):
    """Drive the whole harvest with first-legal-action picks, recording the
    window_id of every decision at which the Transactor FireTrigger is offered."""
    offers = []
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
               for a in legal_actions(state)):
            top = state.pending_stack[-1]
            offers.append(getattr(top, "window_id", type(top).__name__))
        state = step(state, legal_actions(state)[0])
    return state, offers


# --- Registration -----------------------------------------------------------

def test_registered_as_occupation_and_window_trigger():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in HARVEST_WINDOW_CARDS.get(WINDOW_ID, set())
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get(WINDOW_ID, ()))


def test_on_play_is_noop():
    """Pure recurring-window occupation: no on-play clause in the text."""
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) == state


# --- The sweep at the final harvest (positive) --------------------------------

def test_sweep_surfaces_immediately_before_the_round_14_harvest():
    state = _at_window_frame(_harvest_state())
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts
    assert Proceed() in acts
    # Window #1 precedes the FIELD band: the cursor pins the resume point at
    # the next raw-ladder position (no band offset before the band).
    assert state.harvest_cursor == 1


def test_sweep_takes_all_building_resources_and_empties_the_board():
    state = _at_window_frame(_harvest_state())
    res0 = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID))

    # All building resources on the board, in one take.
    assert state.players[0].resources.wood == res0.wood + 6
    assert state.players[0].resources.clay == res0.clay + 3
    assert state.players[0].resources.reed == res0.reed + 2
    assert state.players[0].resources.stone == res0.stone + 3  # 2 + 1
    # Every accumulation space is emptied.
    for sid in _BUILDING_SPACES:
        assert get_space(state.board, sid).accumulated == Resources(), sid


def test_sweep_ignores_food_accumulation():
    """Fishing's 2 accumulated food is NOT a building resource: not taken, not
    cleared."""
    state = _at_window_frame(_harvest_state())
    food0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == food0
    assert get_space(state.board, "fishing").accumulated_amount == 2


def test_sweep_is_once_per_window():
    state = _at_window_frame(_harvest_state())
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert legal_actions(state) == [Proceed()]


def test_decline_takes_nothing():
    state = _at_window_frame(_harvest_state())
    res0 = state.players[0].resources
    state = step(state, Proceed())
    assert state.players[0].resources == res0
    assert get_space(state.board, "forest").accumulated == Resources(wood=6)


def test_round_14_harvest_is_the_final_one():
    """After the round-14 harvest completes, the game heads to scoring — the
    printed "final harvest" and the engine's last harvest coincide."""
    state, offers = _drive_harvest_collecting_offers(_harvest_state())
    assert offers == [WINDOW_ID]
    assert state.phase == Phase.BEFORE_SCORING


# --- The round gate (negative) -------------------------------------------------

def test_not_offered_at_an_earlier_harvest():
    """A stocked board at a non-14 round's harvest: the window frame never
    appears (eligibility gates on round 14)."""
    state, offers = _drive_harvest_collecting_offers(
        _harvest_state(round_number=1))
    assert offers == []


def test_eligibility_gates_on_round_and_board():
    from agricola.cards.transactor import _eligible
    # Round 14 with goods on the board: eligible.
    assert _eligible(_harvest_state(), 0, frozenset()) is True
    # Any earlier round, same goods: not eligible.
    for rn in (1, 4, 7, 9, 11, 13):
        assert _eligible(_harvest_state(round_number=rn), 0, frozenset()) is False
    # Round 14 but nothing left on the board: nothing to take.
    assert _eligible(_harvest_state(stocked=False), 0, frozenset()) is False


def test_not_offered_when_board_empty():
    state, offers = _drive_harvest_collecting_offers(_harvest_state(stocked=False))
    assert offers == []


# --- Owner-gating ---------------------------------------------------------------

def test_not_offered_when_unowned():
    state, offers = _drive_harvest_collecting_offers(
        _harvest_state(give_occ=False))
    assert offers == []


def test_non_owner_gets_no_window_frame():
    """Only the owner is offered the sweep; P1 never sees a window frame."""
    state = _harvest_state()
    p1_frames = 0
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.player_idx == 1:
            p1_frames += 1
        acts = legal_actions(state)
        proceeds = [a for a in acts if isinstance(a, Proceed)]
        state = step(state, proceeds[0] if proceeds else acts[0])
    assert p1_frames == 0
