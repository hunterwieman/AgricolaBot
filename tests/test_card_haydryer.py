"""Tests for Haydryer (occupation, A166; Artifex Expansion; players 4+).

Card text (verbatim): "Immediately before each harvest, you can buy 1 cattle for
4 food minus 1 food for each pasture you have. (The minimum cost is 0)."

An optional TRIGGER on harvest window #1 ``immediately_before_harvest`` — the
first window of the ladder, before start_of_harvest and the field phase. Firing
it pays ``max(0, 4 - #pastures)`` food and grants 1 cattle via
``helpers.grant_animals`` (the accommodation barrier handles a cattle that does
not fit). Declining is the window frame's ``Proceed``; the once-per-window
``triggers_resolved`` makes the buy once per harvest. No round gate — "each
harvest" (the round-14 gate on this window belongs to Transactor).

Players 4+: not dealt in the 2-player pool, but the tests own the card directly
(the established fixture pattern), which exercises the machinery it registers.

These tests drive the REAL harvest walk (``_advance_until_decision`` + ``step``)
per the harvest-window test convention (see tests/test_harvest_windows.py).
"""
from __future__ import annotations

import dataclasses

import agricola.cards.haydryer  # noqa: F401  (register the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pasture import Pasture
from agricola.pending import PendingAccommodate, PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.setup import setup

from tests.factories import with_animals, with_phase, with_resources

CARD_ID = "haydryer"
WINDOW_ID = "immediately_before_harvest"


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, player_idx):
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _add_pastures(state, idx, n):
    """Give player `idx` exactly `n` single-cell pastures (sets the pasture
    cache directly — the established test fixture; `_price` reads only its
    length)."""
    cells = [(2, c) for c in range(n)]
    pastures = tuple(
        Pasture(cells=frozenset({cell}), num_stables=0, capacity=2) for cell in cells
    )
    fy = fast_replace(state.players[idx].farmyard, pastures=pastures)
    p = fast_replace(state.players[idx], farmyard=fy)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _harvest_state(*, owner_food=10, give_occ=True, pastures=0):
    """A HARVEST_FIELD-phase state (round 1 — the window fires at EVERY harvest,
    so no round pinning is needed). P0 owns Haydryer (unless give_occ is False)
    with owner_food food and `pastures` pastures; P1 is food-rich so its feeding
    is trivial."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    if pastures:
        state = _add_pastures(state, 0, pastures)
    state = with_resources(state, 0, food=owner_food)
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
    """Drive the whole harvest with first-legal-action picks, recording every
    decision at which the Haydryer FireTrigger is offered as
    (window_id | frame-type-name). Returns (final_state, offers)."""
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


# --- The price: 4 food minus 1 per pasture, floored at 0 ---------------------

def test_price_scales_with_pastures_and_floors_at_zero():
    from agricola.cards.haydryer import _price
    for n, expected in [(0, 4), (1, 3), (2, 2), (3, 1), (4, 0), (5, 0)]:
        state = _harvest_state(pastures=n)
        assert _price(state, 0) == expected, f"{n} pastures"


# --- The buy at its window (positive) ----------------------------------------

def test_buy_surfaces_immediately_before_harvest():
    """The frame is the harvest's FIRST decision — before the field take (the
    fields are still sown when the offer surfaces)."""
    state = _at_window_frame(_harvest_state())
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts
    assert Proceed() in acts
    # Window #1 precedes the FIELD band: the cursor pins the resume point at
    # the next raw-ladder position (no band offset before the band).
    assert state.harvest_cursor == 1


def test_buy_pays_four_food_with_no_pastures():
    state = _at_window_frame(_harvest_state(owner_food=10, pastures=0))
    cattle0 = state.players[0].animals.cattle
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == 10 - 4
    assert state.players[0].animals.cattle == cattle0 + 1


def test_buy_discounted_by_pastures():
    state = _at_window_frame(_harvest_state(owner_food=10, pastures=3))
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == 10 - 1
    assert state.players[0].animals.cattle == 1


def test_buy_free_with_four_pastures_even_at_zero_food():
    """"(The minimum cost is 0)" — with >= 4 pastures the buy costs nothing and
    is offered even to a player with no food."""
    state = _at_window_frame(_harvest_state(owner_food=0, pastures=4))
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == 0
    assert state.players[0].animals.cattle == 1


def test_buy_is_once_per_harvest():
    state = _at_window_frame(_harvest_state())
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert legal_actions(state) == [Proceed()]


def test_decline_grants_nothing():
    state = _at_window_frame(_harvest_state())
    state = step(state, Proceed())
    assert state.players[0].resources.food == 10
    assert state.players[0].animals.cattle == 0


# --- The cattle routes through the accommodation barrier ---------------------

def test_unhousable_cattle_surfaces_accommodation():
    """With the house-pet slot already taken (1 sheep) and no pastures, the
    bought cattle cannot be housed: the grant routes through grant_animals and
    the accommodation barrier stacks a PendingAccommodate on the window frame."""
    state = _harvest_state(owner_food=10, pastures=0)
    state = with_animals(state, 0, sheep=1)
    state = _at_window_frame(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert isinstance(state.pending_stack[-1], PendingAccommodate)
    # 2 animals held (transiently over capacity), price already paid.
    assert state.players[0].animals.cattle == 1
    assert state.players[0].animals.sheep == 1
    assert state.players[0].resources.food == 10 - 4


# --- Eligibility boundaries ---------------------------------------------------

def test_not_offered_when_food_short():
    """4 food needed with no pastures; with 3 food the buy is unaffordable, so
    no immediately_before_harvest frame is pushed and the trigger never appears."""
    state, offers = _drive_harvest_collecting_offers(
        _harvest_state(owner_food=3, pastures=0))
    assert offers == []


def test_not_offered_when_unowned():
    state, offers = _drive_harvest_collecting_offers(
        _harvest_state(give_occ=False))
    assert offers == []


def test_offered_only_to_owner_and_only_at_window_one():
    """Owner-gating + not-firing-elsewhere: across a full harvest the trigger is
    offered exactly once, at the immediately_before_harvest window, and P1
    (non-owner) never sees a window frame."""
    state = _harvest_state()

    offers = []
    p1_frames = 0
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.player_idx == 1:
            p1_frames += 1
        if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
               for a in legal_actions(state)):
            offers.append(top.window_id)
        # Decline the buy so the walk covers the whole harvest un-fired.
        acts = legal_actions(state)
        proceeds = [a for a in acts if isinstance(a, Proceed)]
        state = step(state, proceeds[0] if proceeds else acts[0])

    assert offers == [WINDOW_ID]
    assert p1_frames == 0


def test_no_round_gate_fires_at_any_harvest():
    """"each harvest" — eligibility holds at any round (contrast Transactor's
    round-14 gate on the same window)."""
    from agricola.cards.haydryer import _eligible
    for rn in (1, 4, 7, 9, 11, 13, 14):
        state = dataclasses.replace(_harvest_state(), round_number=rn)
        assert _eligible(state, 0, frozenset()) is True, f"round {rn}"
