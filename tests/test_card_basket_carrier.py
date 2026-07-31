"""Tests for Basket Carrier (occupation, C105).

Card text (verbatim): "Once each harvest, you can buy 1 wood, 1 reed, and 1
grain for 2 food total."

The buy rides TWO surfaces sharing one once-per-harvest budget (the id
"basket_carrier" in PlayerState.harvest_conversions_used):

1. A free-span optional trigger (ruling 36, 2026-07-12) on every in-span
   window/event — field band through after_breeding (user ruling 85,
   2026-07-27, as corrected: the span IS the harvest, whose last in-span
   window is after_breeding; no end_of_harvest surface) — via
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
    # Ruling 85 (2026-07-27, as corrected): the span IS the harvest, ending
    # after after_breeding, for EVERY span carrier — food-spending buys
    # included. No end_of_harvest surface.
    assert not any(e.card_id == CARD_ID
                   for e in TRIGGERS.get("end_of_harvest", ()))
    assert CARD_ID not in HARVEST_WINDOW_CARDS.get("end_of_harvest", set())


def test_no_frontier_fire():
    """Ruling 37 (2026-07-12): a goods-output buy is standalone — never folded
    into the payment frontier / raise frame."""
    assert HARVEST_CONVERSIONS[CARD_ID].frontier_fire is None


def test_no_scoring_term():
    """Wood/reed/grain are normal goods — no banked points, no scoring term."""
    assert not any(card_id == CARD_ID for card_id, _ in SCORING_TERMS)


# --- The feed-frame buy (surface 2), through the real walk -------------------

def test_feed_frame_fee_is_raisable_not_food_on_hand():
    """Ruling 82 / CARD_AUTHORING_GUIDE.md §0.4 at the FEED seam (brought onto
    the raise shape 2026-07-30, retiring ruling 84 item 4's on-hand carve-out).

    With 0 food but a cookable sheep the 2-food fee is reachable by a legal
    route, so the feed frame MUST offer the buy — the old plain `_can_afford`
    gate withheld it. Firing pushes the raise-only PendingFoodPayment; paying
    resumes into the card's own continuation, which grants the bundle and marks
    the shared once-per-harvest budget.
    """
    from agricola.actions import CommitFoodPayment
    from agricola.pending import PendingFoodPayment
    from tests.factories import with_animals, with_majors

    state = _harvest_state(owner_food=0)
    state = with_animals(state, 0, sheep=3)
    state = with_majors(state, owner_by_idx={0: 0})        # Fireplace(2c)
    state, _ = _walk_until(state, _top_is_p0_feed)
    assert _top_is_p0_feed(state)
    assert CommitHarvestConversion(conversion_id=CARD_ID) in legal_actions(state)

    res0 = state.players[0].resources
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    assert isinstance(state.pending_stack[-1], PendingFoodPayment)
    # Nothing is charged or granted until the fee is actually raised.
    assert CARD_ID not in state.players[0].harvest_conversions_used
    assert state.players[0].resources.wood == res0.wood

    bundle = next(a for a in legal_actions(state)
                  if isinstance(a, CommitFoodPayment))
    state = step(state, bundle)

    p = state.players[0]
    assert not isinstance(state.pending_stack[-1], PendingFoodPayment)
    assert p.animals.sheep == 2                  # one sheep cooked for the fee
    assert p.resources.food == res0.food         # the 2 raised food went to the fee
    assert p.resources.wood == res0.wood + 1
    assert p.resources.reed == res0.reed + 1
    assert p.resources.grain == res0.grain + 1
    assert CARD_ID in p.harvest_conversions_used
    assert CommitHarvestConversion(conversion_id=CARD_ID) not in legal_actions(state)


def test_feed_frame_offer_withheld_when_fee_unreachable():
    """The mirror of the rule above: liquidation-aware is not unconditional.
    With no food and nothing cookable the fee is reachable by no legal route,
    so the buy is correctly withheld (never a dead-end offer)."""
    state, _ = _walk_until(_harvest_state(owner_food=0), _top_is_p0_feed)
    assert _top_is_p0_feed(state)
    assert CommitHarvestConversion(conversion_id=CARD_ID) not in legal_actions(state)


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
    """UPDATED for ruling 82 (2026-07-27) — this previously pinned the old
    plain food-on-hand gate. The ruled span gate is liquidation-aware; here
    the owner holds 1 food and NOTHING convertible (no supply crops, no
    animals), so the 2-food fee is unraisable: no surface offers the buy
    across the whole harvest (window frames aren't even pushed; the feed
    enumerator's on-hand gate withholds the conversion). Boundary pin (b)."""
    state, offers_seen = _walk_until(_harvest_state(owner_food=1), lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_seen == []


def test_window_zero_food_buy_raises_via_food_payment():
    """Ruling 82 boundary pin (a): with 0 food and two cookable grain the span
    fire IS offered and completes through the raise-only PendingFoodPayment —
    the resume debits the 2 raised food, grants the wood+reed+grain bundle,
    and marks the SHARED once-per-harvest budget, identically to the
    food-on-hand path."""
    from agricola.actions import CommitFoodPayment
    from agricola.pending import PendingFoodPayment
    from agricola.resources import Resources as _R

    state = _harvest_state(owner_food=10)
    p = state.players[0]
    p = dataclasses.replace(p, resources=_R(food=0, grain=2))
    state = dataclasses.replace(state, players=(p, state.players[1]))

    state, _ = _walk_until(state, _top_is_p0_window)
    assert _top_is_p0_window(state)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    state = step(state, FireTrigger(card_id=CARD_ID))

    top = state.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 2 and top.resume_kind == CARD_ID

    commits = [a for a in legal_actions(state) if isinstance(a, CommitFoodPayment)]
    assert CommitFoodPayment(grain=2, veg=0, sheep=0, boar=0, cattle=0) in commits
    state = step(state, CommitFoodPayment(grain=2, veg=0, sheep=0, boar=0, cattle=0))

    # 2 grain cooked to 2 food; the resume debited them and granted the bundle.
    r = state.players[0].resources
    assert r.food == 0
    assert r.grain == 1          # 2 cooked, 1 granted back by the bundle
    assert r.wood == 1 and r.reed == 1
    assert CARD_ID in state.players[0].harvest_conversions_used

    # The shared budget withholds every surface for the rest of the harvest.
    state, offers_seen = _walk_until(state, lambda s: False)
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
    # Owner with 1 food and NOTHING convertible: the fee is unraisable (the
    # gate is liquidation-aware per ruling 82, 2026-07-27 — not food-on-hand).
    assert _span_eligible(with_resources(state, 0, food=1), 0, frozenset()) is False
    # With 1 food + 1 grain the fee IS raisable (grain cooks 1:1 at any time).
    assert _span_eligible(
        with_resources(state, 0, food=1, grain=1), 0, frozenset()) is True
    # Budget already spent this harvest.
    p = state.players[0]
    p = dataclasses.replace(
        p, harvest_conversions_used=p.harvest_conversions_used | {CARD_ID}
    )
    spent = dataclasses.replace(state, players=(p, state.players[1]))
    assert _span_eligible(spent, 0, frozenset()) is False
