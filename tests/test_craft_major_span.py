"""Tests for the craft majors' harvest-span window surfaces (ruling 74).

`agricola/cards/craft_major_span.py` gives the three built-in craft-major
conversions (Joinery 7: 1 wood -> 2 food; Pottery 8: 1 clay -> 2 food;
Basketmaker's Workshop 9: 1 reed -> 3 food) the CONVERTER-span WINDOW trigger
set — through the breed frame's pre-commit stretch and after_breeding (user
ruling 85, 2026-07-27: a converter's final standalone offer is the last
conversion opportunity of the breed phase, immediately before end_of_harvest;
the converters are closed after it, so these entries have NO end_of_harvest
surface) — in CARDS mode only, riding the ruling-74
`TriggerEntry.is_owned_fn` ownership override (craft ownership is the board's
major-owner array, not a tableau card) and sharing the built-in
once-per-harvest budget ids ("joinery" / "pottery" / "basketmaker" in
`harvest_conversions_used`) with the FEED offering and the payment-frontier
fire.

Coverage: registration shape (pseudo-ids on the trimmed CONVERTER_SPAN_EVENTS
list, per-entry is_owned_fn, never in the deal-pool specs, absent from
end_of_harvest); the Cards-mode fire on a post-feed wood gain at the span's
LAST surface, after_breeding — and the closure after it (a decline there is
final: no end_of_harvest offer exists); the shared budget in both directions
(feed fire blocks the windows, a window fire blocks the feed offer);
Pottery/Basketmaker amounts; the non-owner negative; and the REQUIRED Family
negative — a Family harvest with an OWNED Joinery walks byte-identically with
and without these registrations (the action sets at every decision are
unchanged, no window frame ever appears, and the Family FEED surface itself
is intact).
"""
from __future__ import annotations

import agricola.cards.craft_major_span  # noqa: F401  (register the surfaces)

import dataclasses

from agricola.actions import (
    CommitBreed,
    CommitConvert,
    CommitFieldTake,
    CommitHarvestConversion,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.cards.craft_major_span import CRAFT_SPAN_IDS
from agricola.cards.harvest_windows import (
    CONVERTER_SPAN_EVENTS,
    HARVEST_WINDOW_CARDS,
    SENTINEL_WINDOWS,
)
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.cards.triggers import CARDS, TRIGGERS
from agricola.constants import GameMode, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed, PendingHarvestWindow
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env

from tests.factories import with_majors, with_phase, with_resources

_HARVEST_PHASES = (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)

_PSEUDO_IDS = tuple(pid for pid, _cid in CRAFT_SPAN_IDS)
_BUDGET_IDS = tuple(cid for _pid, cid in CRAFT_SPAN_IDS)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _cards_harvest_state(*, owner_by_idx=None, wood=0, clay=0, reed=0, food=10):
    """A CARDS-mode HARVEST_FIELD-phase state at the fresh walk entry: P0 is
    starting player with the given goods; P1 is food-rich so its frames
    resolve trivially; craft majors owned per `owner_by_idx`."""
    cs, _env = setup_env(5, card_pool=_POOL)
    assert cs.mode is GameMode.CARDS
    cs = with_phase(cs, Phase.HARVEST_FIELD)
    cs = dataclasses.replace(
        cs, starting_player=0, pending_stack=(), harvest_cursor=None)
    if owner_by_idx:
        cs = with_majors(cs, owner_by_idx=owner_by_idx)
    cs = with_resources(cs, 0, food=food, wood=wood, clay=clay, reed=reed)
    cs = with_resources(cs, 1, food=99)
    return cs


def _neutral_action(state):
    """An action that advances the harvest walk WITHOUT firing any exchange:
    the mechanical commits first, then Proceed/Stop, never a FireTrigger or a
    CommitHarvestConversion."""
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


def _craft_offers(state):
    """Every surface currently offering a craft exchange: the span-window
    FireTriggers (pseudo-ids) and the feed-frame CommitHarvestConversions
    (built-in conversion ids)."""
    return [
        a for a in legal_actions(state)
        if (isinstance(a, FireTrigger) and a.card_id in _PSEUDO_IDS)
        or (isinstance(a, CommitHarvestConversion)
            and a.conversion_id in _BUDGET_IDS)
    ]


def _walk_until(state, stop_pred, *, max_steps=500):
    """Neutral-step the harvest walk until stop_pred(state) or the harvest
    ends. Returns (state, offers_seen): every craft offer observed at
    decisions stepped THROUGH (not the stop state itself)."""
    offers_seen = []
    state = _advance_until_decision(state)
    for _ in range(max_steps):
        if state.phase not in _HARVEST_PHASES:
            return state, offers_seen
        if stop_pred(state):
            return state, offers_seen
        offers_seen.extend(_craft_offers(state))
        state = step(state, _neutral_action(state))
    raise AssertionError("harvest walk did not terminate")


def _top_is_p0_feed(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return isinstance(top, PendingHarvestFeed) and top.player_idx == 0


def _top_is_p0_window(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return isinstance(top, PendingHarvestWindow) and top.player_idx == 0


def _top_is_p0_end_of_harvest(state):
    return _top_is_p0_window(state) and \
        state.pending_stack[-1].window_id == "end_of_harvest"


def _top_is_p0_after_breeding(state):
    return _top_is_p0_window(state) and \
        state.pending_stack[-1].window_id == "after_breeding"


def _add_resources_p0(state, **kwargs):
    p = state.players[0]
    p = dataclasses.replace(p, resources=p.resources + Resources(**kwargs))
    return dataclasses.replace(state, players=(p, state.players[1]))


# --- Registration -----------------------------------------------------------

def test_registered_on_every_span_event_with_owner_override():
    for pseudo_id in _PSEUDO_IDS:
        for event in CONVERTER_SPAN_EVENTS:
            entries = [e for e in TRIGGERS.get(event, ())
                       if e.card_id == pseudo_id]
            assert len(entries) == 1, (pseudo_id, event)
            # The ruling-74 ownership override is set (the owner-array check),
            # so the tableau gate never applies to these entries.
            assert entries[0].is_owned_fn is not None
            assert not entries[0].mandatory
        # Ruling 85: the converters are closed at end_of_harvest — no trigger
        # entry, no window hook there.
        assert not any(e.card_id == pseudo_id
                       for e in TRIGGERS.get("end_of_harvest", ()))
        assert pseudo_id not in HARVEST_WINDOW_CARDS.get("end_of_harvest",
                                                         set())
        # Dispatchable at the fire (CARDS is card-id-keyed).
        assert pseudo_id in CARDS
        # NOT a card: no spec row, so the pseudo-id is never dealt/played.
        assert pseudo_id not in OCCUPATIONS
        assert pseudo_id not in MINORS


def test_owner_predicate_reads_the_major_owner_array():
    state = _cards_harvest_state(owner_by_idx={7: 0, 8: 1})
    joinery = next(e for e in TRIGGERS["after_breeding"]
                   if e.card_id == "craft_span_joinery")
    pottery = next(e for e in TRIGGERS["after_breeding"]
                   if e.card_id == "craft_span_pottery")
    basket = next(e for e in TRIGGERS["after_breeding"]
                  if e.card_id == "craft_span_basketmaker")
    assert joinery.is_owned_fn(state, 0) and not joinery.is_owned_fn(state, 1)
    assert pottery.is_owned_fn(state, 1) and not pottery.is_owned_fn(state, 0)
    assert not basket.is_owned_fn(state, 0)   # unbuilt -> nobody owns it


# --- The Cards-mode late fire (post-feed wood gain; ruling 85: the span's ----
# --- last surface is after_breeding, and a decline there is final ------------

def test_joinery_fires_at_after_breeding_on_post_feed_wood_gain():
    """The late offering, re-timed by ruling 85 (2026-07-27): wood that
    arrives AFTER feeding can still be exchanged at the owner's
    after_breeding surface — the last conversion opportunity of the breed
    phase and the span's last window (the converters are closed at
    end_of_harvest, so no later surface exists)."""
    state = _cards_harvest_state(owner_by_idx={7: 0}, wood=0)
    # Woodless: nothing offered up to and at P0's feed frame.
    state, offers = _walk_until(state, _top_is_p0_feed)
    assert offers == []
    assert _craft_offers(state) == []
    # Resolve P0's feeding, then simulate a post-feed wood gain.
    state = step(state, _neutral_action(state))
    state = _add_resources_p0(state, wood=1)

    state, _ = _walk_until(state, _top_is_p0_after_breeding)
    assert _top_is_p0_after_breeding(state)
    assert FireTrigger(card_id="craft_span_joinery") in legal_actions(state)
    assert Proceed() in legal_actions(state)    # declining stays open

    res0 = state.players[0].resources
    state = step(state, FireTrigger(card_id="craft_span_joinery"))
    res1 = state.players[0].resources
    assert res1.wood == res0.wood - 1
    assert res1.food == res0.food + 2
    # The SHARED budget id — the same one the feed executor marks.
    assert "joinery" in state.players[0].harvest_conversions_used
    assert legal_actions(state) == [Proceed()]
    state, offers_after = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []


def test_decline_at_after_breeding_is_final_no_end_of_harvest_offer():
    """Ruling 85's closure, the discriminating leg: the owner holds the wood
    and DECLINES the exchange at their after_breeding surface. Before ruling
    85 the end_of_harvest window would have re-offered it; now the converters
    are closed after after_breeding, so no craft offer — and no end_of_harvest
    frame at all (nothing else is registered there for P0) — appears for the
    rest of the harvest."""
    state = _cards_harvest_state(owner_by_idx={7: 0}, wood=0)
    state, _ = _walk_until(state, _top_is_p0_feed)
    state = step(state, _neutral_action(state))       # resolve P0's feeding
    state = _add_resources_p0(state, wood=1)

    state, _ = _walk_until(state, _top_is_p0_after_breeding)
    assert FireTrigger(card_id="craft_span_joinery") in legal_actions(state)
    state = step(state, Proceed())                    # decline — final

    # If an end_of_harvest frame appeared, this walk would stop there;
    # instead the harvest completes with no further craft offer, the wood
    # unspent and the budget untouched.
    state, offers_after = _walk_until(state, _top_is_p0_end_of_harvest)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []
    assert state.players[0].resources.wood == 1
    assert "joinery" not in state.players[0].harvest_conversions_used


# --- The shared budget, both directions --------------------------------------

def test_feed_fire_blocks_every_later_window_surface():
    state = _cards_harvest_state(owner_by_idx={7: 0}, wood=2)
    state, _ = _walk_until(state, _top_is_p0_feed)
    assert CommitHarvestConversion(conversion_id="joinery") in legal_actions(state)
    res0 = state.players[0].resources
    state = step(state, CommitHarvestConversion(conversion_id="joinery"))
    res1 = state.players[0].resources
    assert res1.wood == res0.wood - 1 and res1.food == res0.food + 2
    assert "joinery" in state.players[0].harvest_conversions_used
    # The second wood remains, yet no window surface offers the exchange.
    state, offers_seen = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_seen == []


def test_window_fire_blocks_the_feed_offer():
    state = _cards_harvest_state(owner_by_idx={7: 0}, wood=1)
    state, _ = _walk_until(state, _top_is_p0_window)
    assert _top_is_p0_window(state)
    assert state.pending_stack[-1].window_id in CONVERTER_SPAN_EVENTS
    state = step(state, FireTrigger(card_id="craft_span_joinery"))
    assert "joinery" in state.players[0].harvest_conversions_used

    state, offers_before_feed = _walk_until(state, _top_is_p0_feed)
    assert _top_is_p0_feed(state)
    assert offers_before_feed == []
    assert CommitHarvestConversion(conversion_id="joinery") \
        not in legal_actions(state)
    state, offers_after = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []


# --- Pottery / Basketmaker's amounts -----------------------------------------

def test_pottery_window_fire_exchanges_one_clay_for_two_food():
    state = _cards_harvest_state(owner_by_idx={8: 0}, clay=1)
    state, _ = _walk_until(state, _top_is_p0_window)
    res0 = state.players[0].resources
    state = step(state, FireTrigger(card_id="craft_span_pottery"))
    res1 = state.players[0].resources
    assert res1.clay == res0.clay - 1
    assert res1.food == res0.food + 2
    assert "pottery" in state.players[0].harvest_conversions_used


def test_basketmaker_window_fire_exchanges_one_reed_for_three_food():
    state = _cards_harvest_state(owner_by_idx={9: 0}, reed=1)
    state, _ = _walk_until(state, _top_is_p0_window)
    res0 = state.players[0].resources
    state = step(state, FireTrigger(card_id="craft_span_basketmaker"))
    res1 = state.players[0].resources
    assert res1.reed == res0.reed - 1
    assert res1.food == res0.food + 3
    assert "basketmaker" in state.players[0].harvest_conversions_used


# --- Non-owner negative -------------------------------------------------------

def test_non_owner_sees_no_window_surface():
    """Craft majors unbuilt: goods on hand surface nothing anywhere on the
    walk, and no window frame is ever hosted."""
    state = _cards_harvest_state(wood=2, clay=2, reed=2)
    saw_window_frame = False
    state = _advance_until_decision(state)
    for _ in range(500):
        if state.phase not in _HARVEST_PHASES:
            break
        assert _craft_offers(state) == []
        if any(isinstance(f, PendingHarvestWindow) for f in state.pending_stack):
            saw_window_frame = True
        state = step(state, _neutral_action(state))
    else:
        raise AssertionError("harvest walk did not terminate")
    assert not saw_window_frame


# --- The REQUIRED Family negative ---------------------------------------------

def _strip_craft_span_entries():
    """Remove the craft-span TriggerEntry rows from the event-keyed registry,
    returning what is needed to restore them exactly (the Family-baseline
    comparison drives the same harvest with and without the registrations)."""
    saved = {ev: lst[:] for ev, lst in TRIGGERS.items()}
    for lst in TRIGGERS.values():
        lst[:] = [e for e in lst if e.card_id not in _PSEUDO_IDS]
    return saved


def _restore_trigger_entries(saved):
    for ev, lst in saved.items():
        TRIGGERS[ev][:] = lst


def _family_harvest_trace(state, *, max_steps=500):
    """Drive one Family harvest under the neutral policy, recording at every
    decision the top frame type and the FULL legal-action set."""
    trace = []
    state = _advance_until_decision(state)
    for _ in range(max_steps):
        if state.phase not in _HARVEST_PHASES:
            return trace
        top = state.pending_stack[-1] if state.pending_stack else None
        assert not isinstance(top, PendingHarvestWindow)   # never in Family
        trace.append((type(top).__name__ if top is not None else None,
                      sorted(repr(a) for a in legal_actions(state))))
        state = step(state, _neutral_action(state))
    raise AssertionError("harvest walk did not terminate")


def _family_state_with_owned_joinery():
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0})
    state = with_resources(state, 0, food=10, wood=2)
    state = with_resources(state, 1, food=99)
    return state


def test_family_mode_action_sets_unchanged():
    """The user-approved Cards-only lean: Family keeps its FEED-only surface —
    lossless there, since nothing can change between the feed offering and
    end_of_harvest in Family. Proof: a Family harvest with an OWNED Joinery
    and wood on hand walks IDENTICALLY (same frames, same full action set at
    every decision) with the craft-span registrations present and stripped,
    hosts no window frame, and still offers the Family FEED conversion."""
    assert _family_state_with_owned_joinery().mode is GameMode.FAMILY

    trace_with = _family_harvest_trace(_family_state_with_owned_joinery())
    saved = _strip_craft_span_entries()
    try:
        trace_without = _family_harvest_trace(_family_state_with_owned_joinery())
    finally:
        _restore_trigger_entries(saved)

    assert trace_with == trace_without
    # The Family FEED surface itself is intact: some decision on the walk
    # offered the built-in Joinery conversion.
    feed_offer = repr(CommitHarvestConversion(conversion_id="joinery"))
    assert any(feed_offer in acts for _frame, acts in trace_with)
    # And no craft-span pseudo-id ever surfaced anywhere.
    assert not any(
        any(pid in a for pid in _PSEUDO_IDS)
        for _frame, acts in trace_with for a in acts)
