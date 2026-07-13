"""Tests for Furniture Carpenter (occupation, B101).

Card text: "Each harvest, if any player (including you) owns the Joinery or an
upgrade thereof, you can buy exactly 1 bonus point for 2 food."

The buy has TWO surfaces sharing ONE once-per-harvest budget (the
"furniture_carpenter" entry in harvest_conversions_used):

1. An optional CommitHarvestConversion on the FEED payment frame (food_out=0,
   input_cost=2 food) — the original seam, still the budget home.
2. A free-span FireTrigger on every free-span harvest window (ruling 36,
   2026-07-12: the anytime food→points buys are available throughout the
   harvest span, field phase through end_of_harvest).

Firing either banks a bonus point in the per-card CardStore, read back at
end-game by a scoring term, and marks the shared budget so the other surface is
withheld for the rest of that harvest. The FEED-surface tests drive a REAL
HARVEST_FEED resolution (via _initiate_harvest_feed + step); the window-surface
tests drive the REAL harvest walk (_advance_until_decision + step) from
HARVEST_FIELD, declining every offer except the one under test.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.furniture_carpenter  # noqa: F401  (register the card)

from agricola.actions import (
    CommitConvert,
    CommitHarvestConversion,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed, PendingHarvestWindow
from agricola.scoring import SCORING_TERMS, score
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.harvest_windows import (
    FREE_SPAN_EVENTS,
    HARVEST_WINDOW_CARDS,
    SENTINEL_WINDOWS,
)
from agricola.cards.triggers import TRIGGERS
from agricola.setup import setup

from tests.factories import with_majors, with_resources, with_phase

CARD_ID = "furniture_carpenter"


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, player_idx):
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _enter_feed(state):
    """Put `state` into HARVEST_FEED and push the per-player feed frames."""
    state = with_phase(state, Phase.HARVEST_FEED)
    return _initiate_harvest_feed(state)


def _buy_actions(state):
    return [
        a for a in legal_actions(state)
        if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID
    ]


def _owner_state(*, owner_food=10, joinery_owner=0, give_occ=True):
    """P0 owns Furniture Carpenter; `joinery_owner` owns the Joinery (or None).

    P1 is given ample food so its feed frame resolves trivially. P0's people
    default (2 adults → need 4 food); owner_food governs whether the buy is
    affordable on top of feeding.
    """
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    if joinery_owner is not None:
        state = with_majors(state, owner_by_idx={7: joinery_owner})
    state = with_resources(state, 0, food=owner_food)
    state = with_resources(state, 1, food=99)
    return state


# --- Registration -----------------------------------------------------------

def test_registered_as_conversion_and_scoring():
    assert CARD_ID in HARVEST_CONVERSIONS
    spec = HARVEST_CONVERSIONS[CARD_ID]
    # The buy is the inverse of a craft: spend 2 food, produce none.
    assert spec.input_cost.food == 2
    assert spec.food_out == 0
    assert spec.side_effect_fn is not None
    assert any(card_id == CARD_ID for card_id, _ in SCORING_TERMS)


# --- The buy fires and banks a point ---------------------------------------

def test_buy_spends_two_food_and_banks_one_point():
    state = _enter_feed(_owner_state(owner_food=10))
    assert _buy_actions(state) == [CommitHarvestConversion(conversion_id=CARD_ID)]

    food0 = state.players[0].resources.food
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))

    # 2 food spent, no food produced; one bonus point banked.
    assert state.players[0].resources.food == food0 - 2
    assert state.players[0].card_state.get(CARD_ID, 0) == 1
    assert CARD_ID in state.players[0].harvest_conversions_used


def test_buy_is_once_per_harvest():
    state = _enter_feed(_owner_state(owner_food=10))
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    # After one buy this harvest, it is no longer offered.
    assert _buy_actions(state) == []
    assert state.players[0].card_state.get(CARD_ID, 0) == 1


def test_buy_is_optional_declinable():
    """Declining is implicit: commit the feed without firing the buy."""
    state = _enter_feed(_owner_state(owner_food=10))
    # P0 has 10 food, need 4 → food_owed 0. CommitConvert resolves the feed
    # without ever firing the buy.
    assert any(isinstance(a, CommitConvert) for a in legal_actions(state))
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert state.players[0].card_state.get(CARD_ID, 0) == 0


# --- Eligibility boundaries -------------------------------------------------

def test_not_offered_when_no_joinery_owned():
    state = _enter_feed(_owner_state(owner_food=10, joinery_owner=None))
    assert _buy_actions(state) == []


def test_offered_when_opponent_owns_joinery():
    """'if any player (including you) owns the Joinery' — opponent's counts."""
    state = _enter_feed(_owner_state(owner_food=10, joinery_owner=1))
    assert _buy_actions(state) == [CommitHarvestConversion(conversion_id=CARD_ID)]


def test_not_offered_to_non_owner():
    """The conversion is global; the non-owner must NOT be offered the buy.

    P1 owns the Joinery but NOT the occupation; P0 owns the occupation. We drive
    the whole two-player feed and assert P1's frame never offers the buy, while
    P0's frame does (the registration is owner-gated by is_owned_fn, not global).
    """
    state = _owner_state(owner_food=10, joinery_owner=1)
    state = with_resources(state, 1, food=10)  # P1 food-rich too
    state = _enter_feed(state)

    saw_p0_buy = False
    saw_p1_buy = False
    # Resolve both feed frames in stack order, inspecting each for the buy.
    # Stop once the feed frames are gone (the engine then pushes BREED frames).
    while state.pending_stack and isinstance(
        state.pending_stack[-1], PendingHarvestFeed
    ):
        top = state.pending_stack[-1]
        buys = [
            a for a in legal_actions(state)
            if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID
        ]
        if top.player_idx == 0 and buys:
            saw_p0_buy = True
        if top.player_idx == 1 and buys:
            saw_p1_buy = True
        # Advance: commit feed (then Stop) without ever firing the buy.
        actions = legal_actions(state)
        nxt = next(
            (a for a in actions if isinstance(a, CommitConvert)),
            next((a for a in actions if isinstance(a, Stop)), None),
        )
        assert nxt is not None
        state = step(state, nxt)

    assert saw_p0_buy   # the owner IS offered the buy
    assert not saw_p1_buy  # the non-owner is NOT


def test_not_offered_when_food_short():
    """Needs 2 food to buy; with exactly 1 food (and after feeding) it's gone."""
    # 1 food, need 4 → can't even feed; the 2-food buy is unaffordable.
    state = _enter_feed(_owner_state(owner_food=1))
    assert _buy_actions(state) == []


# --- Accumulation + scoring -------------------------------------------------

def test_points_accumulate_across_harvests_and_score():
    base = _owner_state(owner_food=10)
    base_total, _ = score(base, 0)

    # Bank two points (simulating two harvests' buys) then score.
    p = base.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, 2))
    state = dataclasses.replace(base, players=(p, base.players[1]))

    # The owner's end-game score gains exactly the two banked points (owner-gated
    # by score()'s _owns(card_id) check, so a non-owner reads 0 from this term).
    owner_total, _bd = score(state, 0)
    assert state.players[0].card_state.get(CARD_ID, 0) == 2
    assert owner_total == base_total + 2

    # Score the scoring fn directly: owner reads its bank.
    fn = next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)
    assert fn(state, 0) == 2


# --- The free-span window surface (rulings 36/37, 2026-07-12) ----------------

_HARVEST_PHASES = (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)


def _harvest_state(*, owner_food=10, joinery_owner=0, give_occ=True):
    """`_owner_state`, but parked at HARVEST_FIELD with no cursor — the real
    walk's fresh entry (which also resets the once-per-harvest budget)."""
    state = _owner_state(
        owner_food=owner_food, joinery_owner=joinery_owner, give_occ=give_occ
    )
    return with_phase(state, Phase.HARVEST_FIELD)


def _neutral(actions):
    """A decision-advancing action that never uses Furniture Carpenter: prefer
    the frame's decline (Proceed), else the first action that is neither the
    card's FireTrigger nor its feed-seam CommitHarvestConversion."""
    safe = [
        a for a in actions
        if not (isinstance(a, FireTrigger) and a.card_id == CARD_ID)
        and not (isinstance(a, CommitHarvestConversion)
                 and a.conversion_id == CARD_ID)
    ]
    proceed = next((a for a in safe if isinstance(a, Proceed)), None)
    return proceed if proceed is not None else safe[0]


def _run_harvest(state, *, stop_when=None):
    """Drive the real harvest walk, stepping `_neutral` at every decision.
    Records every offer of the card on the way: ("window", window_id) for a
    FireTrigger on a PendingHarvestWindow / other host, ("feed", player_idx)
    for the feed-seam CommitHarvestConversion. Returns (state, offers) —
    paused where `stop_when(state, top)` first matched (before stepping), or
    advanced clean out of the harvest."""
    offers = []
    state = _advance_until_decision(state)
    while state.phase in _HARVEST_PHASES:
        top = state.pending_stack[-1] if state.pending_stack else None
        actions = legal_actions(state)
        if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
               for a in actions):
            offers.append(
                ("window", getattr(top, "window_id", type(top).__name__)))
        if any(isinstance(a, CommitHarvestConversion)
               and a.conversion_id == CARD_ID for a in actions):
            offers.append(("feed", top.player_idx))
        if stop_when is not None and stop_when(state, top):
            return state, offers
        state = step(state, _neutral(actions))
    return state, offers


def _at_window(window_id, player_idx=0):
    def stop_when(state, top):
        return (isinstance(top, PendingHarvestWindow)
                and top.window_id == window_id
                and top.player_idx == player_idx)
    return stop_when


def test_registered_on_every_free_span_surface():
    """Ruling 36: the buy is a trigger on EVERY free-span event (plus the
    window-hook index for the simple windows); ruling 37: it is a standalone
    trigger, never a payment-frontier row (frontier_fire stays None)."""
    for event in FREE_SPAN_EVENTS:
        assert any(e.card_id == CARD_ID for e in TRIGGERS.get(event, ())), event
        if event not in SENTINEL_WINDOWS:
            assert CARD_ID in HARVEST_WINDOW_CARDS.get(event, set()), event
    assert HARVEST_CONVERSIONS[CARD_ID].frontier_fire is None


def test_window_buy_at_end_of_harvest():
    """A window-surface fire through the real walk: -2 food, +1 banked point,
    and the SHARED budget marked."""
    state, _ = _run_harvest(
        _harvest_state(owner_food=10), stop_when=_at_window("end_of_harvest"))
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)

    food0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))

    assert state.players[0].resources.food == food0 - 2
    assert state.players[0].card_state.get(CARD_ID, 0) == 1
    assert CARD_ID in state.players[0].harvest_conversions_used
    # Once-per-window on top of once-per-harvest: only Proceed remains.
    assert legal_actions(state) == [Proceed()]


def test_window_buy_withholds_feed_offer():
    """Shared budget, window-first: buying at the first free-span window
    (before_field_phase) withholds the feed-seam CommitHarvestConversion for
    the rest of the harvest — one buy per harvest TOTAL."""
    state, _ = _run_harvest(
        _harvest_state(owner_food=10),
        stop_when=_at_window("before_field_phase"))
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].card_state.get(CARD_ID, 0) == 1

    state, offers = _run_harvest(state)
    assert state.phase not in _HARVEST_PHASES  # the harvest completed
    assert offers == []  # neither surface offered the buy again
    assert state.players[0].card_state.get(CARD_ID, 0) == 1


def test_feed_buy_withholds_window_offers():
    """Shared budget, feed-first: the feed-seam buy withholds the FireTrigger
    at every later free-span window (after_feeding, breeding, after_breeding,
    end_of_harvest, ...)."""
    def at_p0_feed(state, top):
        return isinstance(top, PendingHarvestFeed) and top.player_idx == 0

    state, _ = _run_harvest(_harvest_state(owner_food=10), stop_when=at_p0_feed)
    assert CommitHarvestConversion(conversion_id=CARD_ID) in legal_actions(state)
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    assert state.players[0].card_state.get(CARD_ID, 0) == 1

    state, offers = _run_harvest(state)
    assert state.phase not in _HARVEST_PHASES
    assert offers == []  # no window ever re-offered the buy
    assert state.players[0].card_state.get(CARD_ID, 0) == 1


def test_window_surface_offered_before_feed_and_declinable():
    """Declining every offer: the buy surfaces on windows across the whole
    span (the feed offer included, once), and a fully-declined harvest banks
    nothing."""
    state, offers = _run_harvest(_harvest_state(owner_food=10))
    assert ("window", "before_field_phase") in offers  # pre-feed availability
    assert ("window", "end_of_harvest") in offers      # post-breed availability
    assert ("feed", 0) in offers                       # the feed-seam surface
    assert state.players[0].card_state.get(CARD_ID, 0) == 0


def test_window_not_offered_without_joinery():
    """The window offer respects the Joinery condition: nobody owns the
    Joinery, so neither surface ever offers the buy."""
    state, offers = _run_harvest(
        _harvest_state(owner_food=10, joinery_owner=None))
    assert offers == []
    assert state.players[0].card_state.get(CARD_ID, 0) == 0


def test_window_offered_when_opponent_owns_joinery():
    """'if any player (including you) owns the Joinery' — the opponent's
    Joinery satisfies the window surface too."""
    state, _ = _run_harvest(
        _harvest_state(owner_food=10, joinery_owner=1),
        stop_when=_at_window("before_field_phase"))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)


def test_window_not_offered_when_food_short():
    """The 2-food gate holds on the window surface: with 1 food the trigger is
    never offered at any window."""
    state, offers = _run_harvest(_harvest_state(owner_food=1))
    assert offers == []
    assert state.players[0].card_state.get(CARD_ID, 0) == 0
