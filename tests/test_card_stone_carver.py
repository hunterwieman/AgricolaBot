"""Tests for Stone Carver (occupation, D108; Consul Dirigens Expansion).

Card text (verbatim): "Each harvest, you can use this card to turn exactly
1 stone into 3 food."

Coverage: registration facts (occupation + HarvestConversionSpec row,
`frontier_fire` included, the free-span trigger set of ruling 75); the
feed-phase fire through the REAL harvest walk (1 stone -> 3 food, once per
harvest); ownership negatives (the conversion registry is global — the offer
must track the occupation per player); the generalized raise-frame reach
(rulings 34/37, 2026-07-12): an in-span PendingFoodPayment offers the fire,
and firing it debits the stone, raises the 3 food, and marks the shared
once-per-harvest budget so a feed-seam offer is withheld; and the harvest-SPAN
window surface (ruling 75, 2026-07-21 — "Stone Carver joins the harvest
span"): the end_of_harvest fire on a post-feed stone gain, the shared budget
in both directions (a feed fire withholds every later span surface; a window
fire withholds the feed offer), and the fresh next-harvest reset.
"""
from __future__ import annotations

import agricola.cards.stone_carver  # noqa: F401  (register the card)

import dataclasses

from agricola.actions import (
    CommitBreed,
    CommitConvert,
    CommitFieldTake,
    CommitFoodPayment,
    CommitHarvestConversion,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.harvest_windows import (
    FREE_SPAN_EVENTS,
    HARVEST_WINDOW_CARDS,
    SENTINEL_WINDOWS,
    available_span_converters,
    sentinel_position,
)
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, OCCUPATIONS
from agricola.cards.stone_carver import CARD_ID
from agricola.cards.triggers import TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingFoodPayment,
    PendingHarvestFeed,
    PendingHarvestWindow,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup

from tests.factories import with_phase, with_resources

_HARVEST_PHASES = (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, idx):
    p = state.players[idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == idx else state.players[i] for i in range(2)),
    )


def _harvest_state(*, stone=0, food=4, owners=(0,)):
    """A HARVEST_FIELD-phase state: P0 holds `stone`/`food` (no fields sown,
    so the field take is empty); the seats in `owners` own Stone Carver; P1
    food-rich so its frames resolve trivially."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in owners:
        state = _give_occupation(state, i)
    state = with_resources(state, 0, food=food, stone=stone)
    state = with_resources(state, 1, food=99)
    return state


def _neutral_action(state):
    """An action that advances the harvest walk WITHOUT firing the exchange:
    the mechanical commits first, then Proceed/Stop, never a FireTrigger or a
    CommitHarvestConversion (with the ruling-75 span registration, the walk
    now hosts window frames whose first action may be the fire)."""
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


def _exchange_offers(state):
    """Every surface currently offering the exchange: window/breed
    FireTriggers and feed-frame CommitHarvestConversions for this card."""
    return [
        a for a in legal_actions(state)
        if (isinstance(a, FireTrigger) and a.card_id == CARD_ID)
        or (isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID)
    ]


def _walk_until(state, stop_pred, *, max_steps=500):
    """Neutral-step the harvest walk until stop_pred(state) or the harvest
    ends. Returns (state, offers_seen): every exchange offer observed at
    decisions stepped THROUGH (not the stop state itself)."""
    offers_seen = []
    state = _advance_until_decision(state)
    for _ in range(max_steps):
        if state.phase not in _HARVEST_PHASES:
            return state, offers_seen
        if stop_pred(state):
            return state, offers_seen
        offers_seen.extend(_exchange_offers(state))
        state = step(state, _neutral_action(state))
    raise AssertionError("harvest walk did not terminate")


def _top_is_p0_undecided_feed(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return (isinstance(top, PendingHarvestFeed) and top.player_idx == 0
            and not top.conversion_done)


def _top_is_p0_window(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return isinstance(top, PendingHarvestWindow) and top.player_idx == 0


def _top_is_p0_end_of_harvest(state):
    return _top_is_p0_window(state) and \
        state.pending_stack[-1].window_id == "end_of_harvest"


def _walk_to_p0_feed(state):
    """Drive the REAL harvest walk (neutrally — Proceeding past the span's
    window frames) until P0's still-undecided feed frame is on top."""
    state, _ = _walk_until(state, _top_is_p0_undecided_feed)
    assert _top_is_p0_undecided_feed(state), "no P0 feed frame surfaced"
    return state


def _carver_actions(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitHarvestConversion)
            and a.conversion_id == CARD_ID]


# --- Registration -----------------------------------------------------------

def test_registration():
    # A no-op on-play occupation (pure recurring converter).
    assert CARD_ID in OCCUPATIONS
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) is state
    # The conversion row: exactly 1 stone -> 3 food, no riders, no variants,
    # frontier-eligible (a pure building-resource converter — ruling 37).
    spec = HARVEST_CONVERSIONS[CARD_ID]
    assert spec.input_cost == Resources(stone=1)
    assert spec.food_out == 3
    assert spec.side_effect_fn is None
    assert spec.variants_fn is None
    assert spec.frontier_fire == ((0, 0, 0, 1), 3)
    # The free span (ruling 75): a trigger on EVERY free-span event, with the
    # window hooks indexed for the non-sentinel windows.
    for event in FREE_SPAN_EVENTS:
        assert any(e.card_id == CARD_ID for e in TRIGGERS.get(event, ())), event
        if event not in SENTINEL_WINDOWS:
            assert CARD_ID in HARVEST_WINDOW_CARDS.get(event, set()), event


# --- The feed-phase fire (real walk) ----------------------------------------

def test_feed_offer_requires_ownership_and_stone():
    # Owned + 1 stone: offered.
    assert _carver_actions(_walk_to_p0_feed(_harvest_state(stone=1))) == [
        CommitHarvestConversion(conversion_id=CARD_ID)]
    # Unowned: withheld despite the stone.
    assert _carver_actions(
        _walk_to_p0_feed(_harvest_state(stone=1, owners=()))) == []
    # Owned, no stone: unaffordable, withheld.
    assert _carver_actions(_walk_to_p0_feed(_harvest_state(stone=0))) == []


def test_offer_tracks_ownership_per_player():
    # Registrations are global (the Furniture Carpenter caution): P1 owning
    # the occupation must not put the offer on P0's feed frame.
    state = _walk_to_p0_feed(_harvest_state(stone=1, owners=(1,)))
    assert _carver_actions(state) == []


def test_fire_turns_one_stone_into_three_food_once_per_harvest():
    state = _walk_to_p0_feed(_harvest_state(stone=2, food=4))
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    p = state.players[0]
    assert p.resources.stone == 1          # exactly 1 stone spent
    assert p.resources.food == 7           # +3 food, before the feed payment
    assert CARD_ID in p.harvest_conversions_used
    # Once per harvest: a second stone remains, but the offer is gone.
    assert _carver_actions(state) == []


# --- The span-window surface (ruling 75, 2026-07-21) -------------------------

def test_end_of_harvest_fire_on_a_post_feed_stone_gain():
    """Ruling 75's span classification: stone that arrives AFTER feeding can
    still be turned into food at end_of_harvest — the span's last window."""
    # Stoneless: no surface offers the exchange up to and at the feed.
    state, offers = _walk_until(_harvest_state(stone=0), _top_is_p0_undecided_feed)
    assert offers == []
    assert _carver_actions(state) == []
    # Resolve P0's feeding, then simulate a post-feed stone gain.
    state = step(state, _neutral_action(state))
    p = state.players[0]
    p = dataclasses.replace(p, resources=p.resources + Resources(stone=1))
    state = dataclasses.replace(state, players=(p, state.players[1]))

    # The walk now reaches an end_of_harvest window frame for P0.
    state, _ = _walk_until(state, _top_is_p0_end_of_harvest)
    assert _top_is_p0_end_of_harvest(state)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)   # declining stays open

    res0 = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID))
    res1 = state.players[0].resources
    assert res1.stone == res0.stone - 1
    assert res1.food == res0.food + 3
    assert CARD_ID in state.players[0].harvest_conversions_used
    # The frame offers only the decline now; the harvest then completes.
    assert legal_actions(state) == [Proceed()]
    state, offers_after = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []


def test_feed_fire_withholds_every_later_span_surface():
    """Shared budget, feed -> windows direction: after firing on the feed
    frame, no free-span surface offers the exchange for the rest of the
    harvest."""
    state = _walk_to_p0_feed(_harvest_state(stone=2))
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    state, offers_seen = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES  # the harvest ran to completion
    assert offers_seen == []                   # despite the second stone


def test_window_fire_spends_one_stone_and_withholds_the_feed_offer():
    """The exchange surfaces as a FireTrigger at the first in-span window of
    the owner's band; firing it applies -1 stone / +3 food, marks the budget,
    and withholds the feed-frame offer (window -> feed direction)."""
    state, _ = _walk_until(_harvest_state(stone=1), _top_is_p0_window)
    top = state.pending_stack[-1]
    assert top.window_id in FREE_SPAN_EVENTS
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)   # declining stays open

    res0 = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID))
    res1 = state.players[0].resources
    assert res1.stone == res0.stone - 1
    assert res1.food == res0.food + 3
    assert CARD_ID in state.players[0].harvest_conversions_used

    state, offers_before_feed = _walk_until(state, _top_is_p0_undecided_feed)
    assert _top_is_p0_undecided_feed(state)
    assert offers_before_feed == []
    assert _carver_actions(state) == []
    state, offers_after = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []


def test_next_harvest_offers_the_exchange_again():
    """The budget is per-harvest: after a fire in one harvest, a fresh harvest
    entry resets harvest_conversions_used and offers the exchange anew."""
    state = _walk_to_p0_feed(_harvest_state(stone=2))
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    state, _ = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert CARD_ID in state.players[0].harvest_conversions_used  # survives...
    assert state.players[0].resources.stone == 1                 # ...one stone left

    # Harvest 2: synthesize a fresh FIELD entry (the walk resets the budget at
    # a None-cursor HARVEST_FIELD entry).
    state = dataclasses.replace(
        state, phase=Phase.HARVEST_FIELD, pending_stack=(), harvest_cursor=None)
    state, _ = _walk_until(state, _top_is_p0_window)
    assert _top_is_p0_window(state)
    assert CARD_ID not in state.players[0].harvest_conversions_used
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)


# --- The raise-frame reach (rulings 34/37) ----------------------------------

# A synthetic resume so a hand-built frame can be stepped through the executor
# (registered once; only frames naming it ever reach it).
FOOD_PAYMENT_RESUMES["_test_stone_carver_resume"] = lambda state, idx: state


def _in_span_state(*, stone=0, grain=0, food=0, owe=2, owned=True):
    """A hand-built in-span PendingFoodPayment (the
    test_food_payment_generalized idiom, the occupation in place of a craft
    major): P0 mid-BREED phase, post-both-breed-passes, owing `owe` food."""
    state = setup(3)
    state = fast_replace(state, starting_player=0)
    p = state.players[0]
    if owned:
        p = fast_replace(p, occupations=p.occupations | frozenset({CARD_ID}))
    p = fast_replace(
        p,
        resources=Resources(stone=stone, grain=grain, food=food),
        animals=fast_replace(p.animals, sheep=0, boar=0, cattle=0),
    )
    frame = PendingFoodPayment(
        player_idx=0, food_needed=food + owe,
        resume_kind="_test_stone_carver_resume", reserved=Cost())
    cur = sentinel_position("after_breeding", 1)
    return fast_replace(
        state,
        players=tuple(p if i == 0 else state.players[i] for i in range(2)),
        phase=Phase.HARVEST_BREED, pending_stack=(frame,), harvest_cursor=cur)


def test_raise_frame_offers_the_fire():
    s = _in_span_state(stone=1, owe=2)
    assert available_span_converters(s, 0) == ((CARD_ID, (0, 0, 0, 1), 3, None),)
    assert legal_actions(s) == [CommitFoodPayment(
        grain=0, veg=0, sheep=0, boar=0, cattle=0, conversions=(CARD_ID,))]


def test_raise_frame_unowned_sees_no_converter():
    s = _in_span_state(stone=1, grain=2, owe=2, owned=False)
    assert available_span_converters(s, 0) == ()
    assert all(a.conversions == () for a in legal_actions(s))


def test_raise_frame_fire_debits_marks_budget_and_withholds_feed_offer():
    s = _in_span_state(stone=2, owe=2)
    nxt = step(s, legal_actions(s)[0])
    p = nxt.players[0]
    assert p.resources.stone == 1          # exactly 1 of the 2 stone debited
    assert p.resources.food == 3           # raise-only: 3 food, overshoot banked
    assert CARD_ID in p.harvest_conversions_used
    assert not any(isinstance(f, PendingFoodPayment) for f in nxt.pending_stack)
    # Ruling 34 — the budget is SHARED: a same-harvest feed frame carrying
    # that used-set withholds the offer despite the remaining stone.
    feed = _walk_to_p0_feed(_harvest_state(stone=1, food=4))
    assert _carver_actions(feed)           # offered while the budget is fresh
    q = feed.players[0]
    q = fast_replace(q, harvest_conversions_used=p.harvest_conversions_used)
    feed_used = fast_replace(
        feed, players=tuple(q if i == 0 else feed.players[i] for i in range(2)))
    assert _carver_actions(feed_used) == []   # withheld once the frame fired
