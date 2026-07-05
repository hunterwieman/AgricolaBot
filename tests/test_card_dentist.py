"""Tests for Dentist (occupation, E110; Ephipparius Expansion; players 1+).

Card text: "At the start of each harvest, you can place 1 wood from your supply on
this card, irretrievably. In each feeding phase, you get 1 food for each wood on
this card."

Two effects on two harvest windows:
- The BANK: an optional trigger on ``start_of_harvest`` (window #2) — place 1 wood
  from supply onto the card (a wood-on-card counter in CardStore), declinable.
- The PAYOUT: a ``"feeding"`` auto — 1 food per wood on the card, at the FEED
  entry (before payment, so the food is payable).
"""
from __future__ import annotations

import agricola.cards.dentist  # noqa: F401  (register the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.dentist import CARD_ID
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import GameState

from tests.factories import with_phase, with_round, with_sown_fields


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _set_wood_on_card(state, idx, n):
    p = state.players[idx]
    return _edit_player(state, idx, card_state=p.card_state.set(CARD_ID, n))


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state with enough food that feeding is painless."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = _edit_player(state, idx, resources=fast_replace(
            state.players[idx].resources, food=food))
    return state


def _run_harvest(state, pick=lambda acts: acts[0]):
    """Drive the whole harvest to completion (into the next round's reveal)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


def _fire_dentist_else_first(acts):
    for a in acts:
        if isinstance(a, FireTrigger) and a.card_id == CARD_ID:
            return a
    return acts[0]


def _proceed_else_first(acts):
    for a in acts:
        if isinstance(a, Proceed):
            return a
    return acts[0]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation_no_on_play_effect():
    assert CARD_ID in OCCUPATIONS
    # No on-play clause: playing it changes nothing.
    s = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) == s


def test_registered_on_both_windows():
    # The bank is a trigger on start_of_harvest; the payout an auto on feeding.
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("start_of_harvest", ())}
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("feeding", ())}
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("start_of_harvest", set())
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("feeding", set())


# ---------------------------------------------------------------------------
# The bank (start_of_harvest optional trigger)
# ---------------------------------------------------------------------------

def test_bank_offered_and_fires():
    """The bank surfaces as a FireTrigger at start_of_harvest; firing it debits 1
    wood from supply and records 1 wood on the card."""
    state = _own(_harvest_state(), 0)
    state = _edit_player(state, 0, resources=fast_replace(
        state.players[0].resources, wood=3))
    state = _advance_until_decision(state)
    # Walk to the start_of_harvest PendingHarvestWindow frame.
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.window_id == "start_of_harvest":
            break
        state = step(state, legal_actions(state)[0])
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_harvest" and top.player_idx == 0
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts and Proceed() in acts

    wood_before = state.players[0].resources.wood
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.wood == wood_before - 1
    assert state.players[0].card_state.get(CARD_ID, 0) == 1
    # Once per window: only Proceed remains.
    assert legal_actions(state) == [Proceed()]


def test_bank_not_offered_without_wood():
    """No wood in supply -> the bank is ineligible, so no frame is even pushed."""
    state = _own(_harvest_state(), 0)
    state = _edit_player(state, 0, resources=fast_replace(
        state.players[0].resources, wood=0))
    state = _advance_until_decision(state)
    saw_bank_frame = False
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.window_id == "start_of_harvest":
            saw_bank_frame = True
        state = step(state, legal_actions(state)[0])
    assert not saw_bank_frame


def test_bank_declined_places_nothing():
    """Proceed at the bank window leaves wood in supply and 0 wood on the card."""
    state = _own(_harvest_state(), 0)
    state = _edit_player(state, 0, resources=fast_replace(
        state.players[0].resources, wood=3))
    after = _run_harvest(state, _proceed_else_first)
    assert after.players[0].card_state.get(CARD_ID, 0) == 0
    assert after.players[0].resources.wood == 3


def test_bank_accumulates_across_harvests():
    """Each harvest banks at most one wood; the counter accumulates."""
    state = _own(_harvest_state(), 0)
    state = _edit_player(state, 0, resources=fast_replace(
        state.players[0].resources, wood=3))
    after = _run_harvest(state, _fire_dentist_else_first)
    assert after.players[0].card_state.get(CARD_ID, 0) == 1

    # A later harvest banks a second wood (fresh window).
    from tests.factories import with_pending_stack
    again = with_pending_stack(after, [])
    again = with_phase(with_round(again, 7), Phase.HARVEST_FIELD)
    again = _run_harvest(again, _fire_dentist_else_first)
    assert again.players[0].card_state.get(CARD_ID, 0) == 2


# ---------------------------------------------------------------------------
# The payout (feeding auto)
# ---------------------------------------------------------------------------

def test_payout_one_food_per_wood_at_feeding():
    """A Dentist with 2 wood banked gets +2 food at the FEED entry."""
    state = _own(_harvest_state(food=10), 0)
    state = _set_wood_on_card(state, 0, 2)
    f0 = state.players[0].resources.food
    after = _run_harvest(state, _proceed_else_first)
    # +2 income, then feeding 2 adults costs 4.
    assert after.players[0].resources.food == f0 + 2 - 4


def test_payout_none_with_no_wood_banked():
    state = _own(_harvest_state(food=10), 0)
    f0 = state.players[0].resources.food
    after = _run_harvest(state, _proceed_else_first)
    assert after.players[0].resources.food == f0 - 4     # no income


def test_payout_is_payable_before_feeding_decision():
    """Payability: 3 food banked + 1 food in hand feeds 2 adults (4 food) with no
    begging — the income arrives BEFORE the payment decision."""
    state = _own(_harvest_state(food=1), 0)
    state = _set_wood_on_card(state, 0, 3)
    state = _edit_player(state, 1, resources=fast_replace(
        state.players[1].resources, food=10))
    after = _run_harvest(state)
    assert after.players[0].resources.food == 0          # 1 + 3 − 4
    assert after.players[0].begging_markers == 0


# ---------------------------------------------------------------------------
# Owner-gating and negatives
# ---------------------------------------------------------------------------

def test_non_owner_gets_nothing():
    """The opponent, who does not own Dentist, gets no bank frame and no payout."""
    state = _own(_harvest_state(food=10), 0)
    state = _set_wood_on_card(state, 0, 2)
    f1 = state.players[1].resources.food
    saw_p1_bank = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.player_idx == 1 \
                and top.window_id == "start_of_harvest":
            saw_p1_bank = True
        state = step(state, _proceed_else_first(legal_actions(state)))
    assert not saw_p1_bank
    assert state.players[1].resources.food == f1 - 4     # feeding only, no income


def test_payout_fires_only_in_feeding_not_field_or_breeding():
    """The payout is a feeding auto: it credits food exactly once (at FEED), never
    early in the field phase nor again in breeding. Track food across sub-phases:
    +1 appears only once the FEED sub-phase is reached, and no second +1 in BREED."""
    state = _own(_harvest_state(food=10), 0)
    state = _set_wood_on_card(state, 0, 1)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    f0 = state.players[0].resources.food
    state = _advance_until_decision(state)
    seen_income_in_field = False
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        # During the FIELD phase the +1 income must not yet have landed.
        if state.phase == Phase.HARVEST_FIELD \
                and state.players[0].resources.food > f0:
            seen_income_in_field = True
        state = step(state, _proceed_else_first(legal_actions(state)))
    assert not seen_income_in_field
    # +1 income exactly once, feeding 2 adults costs 4; grain does not feed.
    assert state.players[0].resources.food == f0 + 1 - 4
