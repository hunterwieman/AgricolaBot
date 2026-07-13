"""Tests for Basket Carrier (occupation, C105).

Card text (verbatim): "Once each harvest, you can buy 1 wood, 1 reed, and 1
grain for 2 food total."

The buy rides TWO surfaces sharing one once-per-harvest budget (the id
"basket_carrier" in PlayerState.harvest_conversions_used):

1. A free-span optional trigger (ruling 36, 2026-07-12) on every in-span
   window/event — field band through end_of_harvest — via
   register_free_span_trigger.
2. A HarvestConversionSpec on the FEED payment frame (food_out=0, 2-food
   input, side effect grants the bundle) — the one in-span surface the window
   events don't cover. NO frontier_fire (ruling 37, 2026-07-12: goods-output
   buys stay standalone, never folded into the payment frontier).

These tests drive the REAL banded harvest walk (with_phase(HARVEST_FIELD) +
_advance_until_decision + step), using a neutral stepper that never fires the
buy by accident.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.basket_carrier  # noqa: F401  (register the card)

from agricola.actions import (
    CommitBreed,
    CommitConvert,
    CommitFieldTake,
    CommitHarvestConversion,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed, PendingHarvestWindow
from agricola.resources import Resources
from agricola.scoring import SCORING_TERMS
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.harvest_windows import (
    FREE_SPAN_EVENTS,
    HARVEST_WINDOW_CARDS,
    SENTINEL_WINDOWS,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.setup import setup

from tests.factories import with_phase, with_resources

CARD_ID = "basket_carrier"

_HARVEST_PHASES = (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, player_idx):
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _harvest_state(*, owner_food=10, give_occ=True):
    """A HARVEST_FIELD-phase state at the fresh walk entry. P0 owns Basket
    Carrier (unless give_occ is False) and holds owner_food food; P1 is
    food-rich so its feeding is trivial. P0 needs 4 food (2 adults)."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    state = with_resources(state, 0, food=owner_food)
    state = with_resources(state, 1, food=99)
    return state


def _neutral_action(state):
    """An action that advances the harvest walk WITHOUT firing the buy:
    the mechanical commits first, then Proceed/Stop, never a FireTrigger or
    a CommitHarvestConversion."""
    actions = legal_actions(state)
    for kind in (CommitFieldTake, CommitConvert, CommitBreed):
        for a in actions:
            if isinstance(a, kind):
                return a
    for a in actions:
        if isinstance(a, (Proceed, Stop)):
            return a
    for a in actions:
        if not isinstance(a, (FireTrigger, CommitHarvestConversion)):
            return a
    raise AssertionError(f"no neutral action among {actions}")


def _buy_offers(state):
    """Every surface currently offering the buy: window/breed FireTriggers and
    feed-frame CommitHarvestConversions for this card."""
    return [
        a for a in legal_actions(state)
        if (isinstance(a, FireTrigger) and a.card_id == CARD_ID)
        or (isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID)
    ]


def _walk_until(state, stop_pred, *, max_steps=500):
    """Neutral-step the harvest walk until stop_pred(state) or the harvest
    ends. Returns (state, offers_seen): every buy offer observed at decisions
    stepped THROUGH (not the stop state itself)."""
    offers_seen = []
    state = _advance_until_decision(state)
    for _ in range(max_steps):
        if state.phase not in _HARVEST_PHASES:
            return state, offers_seen
        if stop_pred(state):
            return state, offers_seen
        offers_seen.extend(_buy_offers(state))
        state = step(state, _neutral_action(state))
    raise AssertionError("harvest walk did not terminate")


def _top_is_p0_feed(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return isinstance(top, PendingHarvestFeed) and top.player_idx == 0


def _top_is_p0_window(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return isinstance(top, PendingHarvestWindow) and top.player_idx == 0


# --- Registration -----------------------------------------------------------

def test_registered_on_both_surfaces():
    assert CARD_ID in OCCUPATIONS

    # Surface 2: the feed-seam entry — 2 food in, no food out, goods via the
    # side effect.
    spec = HARVEST_CONVERSIONS[CARD_ID]
    assert spec.input_cost == Resources(food=2)
    assert spec.food_out == 0
    assert spec.side_effect_fn is not None
    assert spec.variants_fn is None

    # Surface 1: a trigger on EVERY free-span event, with the window hooks
    # indexed for the non-sentinel windows (the sentinels host via their own
    # frames, not PendingHarvestWindow).
    for event in FREE_SPAN_EVENTS:
        assert any(e.card_id == CARD_ID for e in TRIGGERS.get(event, ())), event
        if event not in SENTINEL_WINDOWS:
            assert CARD_ID in HARVEST_WINDOW_CARDS.get(event, set()), event


def test_no_frontier_fire():
    """Ruling 37 (2026-07-12): a goods-output buy is standalone — never folded
    into the payment frontier / raise frame."""
    assert HARVEST_CONVERSIONS[CARD_ID].frontier_fire is None


def test_no_scoring_term():
    """Wood/reed/grain are normal goods — no banked points, no scoring term."""
    assert not any(card_id == CARD_ID for card_id, _ in SCORING_TERMS)


# --- The feed-frame buy (surface 2), through the real walk -------------------

def test_feed_frame_buy_spends_two_food_and_grants_bundle():
    state, _ = _walk_until(_harvest_state(owner_food=10), _top_is_p0_feed)
    assert _top_is_p0_feed(state)
    assert CommitHarvestConversion(conversion_id=CARD_ID) in legal_actions(state)

    res0 = state.players[0].resources
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))

    res1 = state.players[0].resources
    assert res1.food == res0.food - 2
    assert res1.wood == res0.wood + 1
    assert res1.reed == res0.reed + 1
    assert res1.grain == res0.grain + 1
    assert CARD_ID in state.players[0].harvest_conversions_used
    # "Once each harvest": the frame no longer offers it.
    assert CommitHarvestConversion(conversion_id=CARD_ID) not in legal_actions(state)


def test_feed_frame_buy_withholds_every_later_span_surface():
    """Shared budget, feed -> windows direction: after buying on the feed
    frame, no free-span surface offers the buy for the rest of the harvest."""
    state, _ = _walk_until(_harvest_state(owner_food=10), _top_is_p0_feed)
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    state, offers_seen = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES  # the harvest ran to completion
    assert offers_seen == []


# --- The window-surface buy (surface 1), through the real walk ---------------

def test_window_fire_spends_two_food_and_grants_bundle():
    """The buy surfaces as a FireTrigger at the first in-span window of the
    owner's band; firing it applies -2 food / +bundle and marks the budget."""
    state, _ = _walk_until(_harvest_state(owner_food=10), _top_is_p0_window)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id in FREE_SPAN_EVENTS
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)  # declining stays open

    res0 = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID))

    res1 = state.players[0].resources
    assert res1.food == res0.food - 2
    assert res1.wood == res0.wood + 1
    assert res1.reed == res0.reed + 1
    assert res1.grain == res0.grain + 1
    assert CARD_ID in state.players[0].harvest_conversions_used
    # The window frame itself offers only Proceed now.
    assert legal_actions(state) == [Proceed()]


def test_window_fire_withholds_the_feed_frame_offer():
    """Shared budget, window -> feed direction: after firing at a window, the
    feed frame does NOT offer the conversion, nor does any later surface."""
    state, _ = _walk_until(_harvest_state(owner_food=10), _top_is_p0_window)
    state = step(state, FireTrigger(card_id=CARD_ID))

    state, offers_before_feed = _walk_until(state, _top_is_p0_feed)
    assert _top_is_p0_feed(state)
    assert offers_before_feed == []
    assert CommitHarvestConversion(conversion_id=CARD_ID) not in legal_actions(state)

    state, offers_after = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []


# --- Eligibility boundaries --------------------------------------------------

def test_not_offered_without_two_food():
    """With 1 food the 2-food buy is unaffordable: no surface offers it across
    the whole harvest (window frames aren't even pushed; the feed enumerator's
    affordability gate withholds the conversion)."""
    state, offers_seen = _walk_until(_harvest_state(owner_food=1), lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_seen == []


def test_not_offered_when_unowned():
    """No seat owns Basket Carrier: no surface ever offers the buy."""
    state, offers_seen = _walk_until(
        _harvest_state(owner_food=10, give_occ=False), lambda s: False
    )
    assert state.phase not in _HARVEST_PHASES
    assert offers_seen == []


def test_non_owner_seat_never_offered():
    """The registrations are global; only the occupation owner sees the buy.
    P1 is food-rich (99 food) yet must never be offered either surface."""
    saw_p1_offer = False
    state = _advance_until_decision(_harvest_state(owner_food=10))
    for _ in range(500):
        if state.phase not in _HARVEST_PHASES:
            break
        top = state.pending_stack[-1] if state.pending_stack else None
        if top is not None and getattr(top, "player_idx", None) == 1 and _buy_offers(state):
            saw_p1_offer = True
        state = step(state, _neutral_action(state))
    else:
        raise AssertionError("harvest walk did not terminate")
    assert not saw_p1_offer


# --- The next harvest offers it again ----------------------------------------

def test_next_harvest_offers_the_buy_again():
    """The budget is per-harvest: after buying in one harvest, a fresh harvest
    entry resets harvest_conversions_used and offers the buy anew."""
    # Harvest 1: buy on the feed frame, then run the harvest to completion.
    state, _ = _walk_until(_harvest_state(owner_food=10), _top_is_p0_feed)
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    state, _ = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    # The spent budget survives until the next harvest entry clears it.
    assert CARD_ID in state.players[0].harvest_conversions_used
    assert state.players[0].resources.food >= 2  # 10 - 2 (buy) - 4 (feed) = 4

    # Harvest 2: synthesize a fresh FIELD entry (the walk resets the budget
    # at a None-cursor HARVEST_FIELD entry).
    state = dataclasses.replace(
        state, phase=Phase.HARVEST_FIELD, pending_stack=(), harvest_cursor=None
    )
    state, _ = _walk_until(state, _top_is_p0_window)
    assert _top_is_p0_window(state)
    assert CARD_ID not in state.players[0].harvest_conversions_used
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)


# --- Eligibility unit check ---------------------------------------------------

def test_span_eligibility_gates_ownership_budget_and_food():
    from agricola.cards.basket_carrier import _span_eligible
    state = _harvest_state(owner_food=10)
    assert _span_eligible(state, 0, frozenset()) is True
    # Non-owner seat.
    assert _span_eligible(state, 1, frozenset()) is False
    # Owner with only 1 food cannot afford it.
    assert _span_eligible(with_resources(state, 0, food=1), 0, frozenset()) is False
    # Budget already spent this harvest.
    p = state.players[0]
    p = dataclasses.replace(
        p, harvest_conversions_used=p.harvest_conversions_used | {CARD_ID}
    )
    spent = dataclasses.replace(state, players=(p, state.players[1]))
    assert _span_eligible(spent, 0, frozenset()) is False
