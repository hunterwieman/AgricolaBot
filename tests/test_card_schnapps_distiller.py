"""Tests for Schnapps Distiller (occupation, C109).

Card text: "In the feeding phase of each harvest, you can use this card to turn
exactly 1 vegetable into 5 food."

The conversion is surfaced as an optional once-per-harvest CommitHarvestConversion
during HARVEST_FEED (input_cost=1 veg, food_out=5). These tests drive a REAL
HARVEST_FEED resolution (via _initiate_harvest_feed + step), not a poked frame.
"""
from __future__ import annotations

import agricola.cards.schnapps_distiller  # noqa: F401  (register the card)

import dataclasses

from agricola.actions import (
    CommitConvert,
    CommitFoodPayment,
    CommitHarvestConversion,
    Stop,
)
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment, PendingHarvestFeed
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.harvest_windows import (
    available_span_converters,
    sentinel_position,
)
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, OCCUPATIONS
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState
from agricola.setup import setup

from tests.factories import with_majors, with_resources, with_phase

CARD_ID = "schnapps_distiller"


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


def _convert_actions(state):
    return [
        a for a in legal_actions(state)
        if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID
    ]


def _owner_state(*, owner_food=10, owner_veg=1, give_occ=True):
    """P0 owns Schnapps Distiller and has `owner_veg` vegetables.

    P1 is given ample food so its feed frame resolves trivially. P0's people
    default (2 adults -> need 4 food); owner_food governs whether feeding leaves
    P0 able to decline / fire the conversion.
    """
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    state = with_resources(state, 0, food=owner_food, veg=owner_veg)
    state = with_resources(state, 1, food=99)
    return state


# --- Registration -----------------------------------------------------------

def test_registered_as_conversion_and_occupation():
    assert CARD_ID in HARVEST_CONVERSIONS
    spec = HARVEST_CONVERSIONS[CARD_ID]
    # Spend exactly 1 vegetable, produce 5 food, no points / side effect.
    assert spec.input_cost.veg == 1
    assert spec.food_out == 5
    assert spec.side_effect_fn is None
    # Registered as a (no-op on-play) occupation, played via Lessons.
    assert CARD_ID in OCCUPATIONS


def test_on_play_is_noop():
    state = _owner_state()
    spec = OCCUPATIONS[CARD_ID]
    assert spec.on_play(state, 0) is state


# --- The conversion fires ---------------------------------------------------

def test_convert_spends_one_veg_and_makes_five_food():
    state = _enter_feed(_owner_state(owner_food=10, owner_veg=2))
    assert _convert_actions(state) == [CommitHarvestConversion(conversion_id=CARD_ID)]

    food0 = state.players[0].resources.food
    veg0 = state.players[0].resources.veg
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))

    # 1 veg spent, 5 food produced.
    assert state.players[0].resources.veg == veg0 - 1
    assert state.players[0].resources.food == food0 + 5
    assert CARD_ID in state.players[0].harvest_conversions_used


def test_convert_is_once_per_harvest():
    state = _enter_feed(_owner_state(owner_food=10, owner_veg=3))
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    # After one use this harvest, it is no longer offered (even with veg left).
    assert _convert_actions(state) == []
    assert state.players[0].resources.veg == 2  # only one veg consumed


def test_convert_is_optional_declinable():
    """Declining is implicit: commit the feed without firing the conversion."""
    state = _enter_feed(_owner_state(owner_food=10, owner_veg=1))
    # P0 has 10 food, need 4 -> food_owed 0. CommitConvert resolves the feed
    # without ever firing the conversion; the veg stays.
    assert any(isinstance(a, CommitConvert) for a in legal_actions(state))
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert state.players[0].resources.veg == 1
    assert CARD_ID not in state.players[0].harvest_conversions_used


# --- Eligibility boundaries -------------------------------------------------

def test_not_offered_without_occupation():
    state = _enter_feed(_owner_state(owner_food=10, owner_veg=1, give_occ=False))
    assert _convert_actions(state) == []


def test_not_offered_without_vegetable():
    state = _enter_feed(_owner_state(owner_food=10, owner_veg=0))
    assert _convert_actions(state) == []


def test_not_offered_to_non_owner():
    """The conversion is global; the non-owner must NOT be offered it.

    P0 owns the occupation, P1 does not (but has a vegetable). Drive both feed
    frames and assert only P0's frame offers the conversion.
    """
    state = _owner_state(owner_food=10, owner_veg=1)
    state = with_resources(state, 1, food=10, veg=1)  # P1 has veg but no occ
    state = _enter_feed(state)

    saw_p0 = False
    saw_p1 = False
    while state.pending_stack and isinstance(
        state.pending_stack[-1], PendingHarvestFeed
    ):
        top = state.pending_stack[-1]
        convs = [
            a for a in legal_actions(state)
            if isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID
        ]
        if top.player_idx == 0 and convs:
            saw_p0 = True
        if top.player_idx == 1 and convs:
            saw_p1 = True
        actions = legal_actions(state)
        nxt = next(
            (a for a in actions if isinstance(a, CommitConvert)),
            next((a for a in actions if isinstance(a, Stop)), None),
        )
        assert nxt is not None
        state = step(state, nxt)

    assert saw_p0       # the owner IS offered the conversion
    assert not saw_p1   # the non-owner is NOT


# ---------------------------------------------------------------------------
# The payment-frontier surface (ruling 77 item 1, 2026-07-21): a crop-input
# converter joins any PendingFoodPayment frame resolved DURING the feeding
# phase, at its premium rate, the base rate cooking the rest (greedy tiering).
# ---------------------------------------------------------------------------

# A synthetic resume so hand-built raise frames step through the executor
# (mirrors test_food_payment_generalized / test_card_studio).
FOOD_PAYMENT_RESUMES["_test_schnapps_resume"] = lambda state, idx: state

FIREPLACE_IDX = 0   # a Fireplace gives veg the base cooking rate 2


def test_frontier_fire_registered():
    """Ruling 77 widened frontier_fire to the 6-tuple (grain,veg,wood,clay,
    reed,stone); Schnapps is 1 veg -> 5 food (a crop-input converter)."""
    assert HARVEST_CONVERSIONS[CARD_ID].frontier_fire == ((0, 1, 0, 0, 0, 0), 5)
    assert HARVEST_CONVERSIONS[CARD_ID].frontier_group is None


def _payment_state(*, owe, veg=0, grain=0, phase=Phase.HARVEST_FEED,
                   cursor=None, fireplace=False, used=frozenset()) -> GameState:
    """A hand-built harvest state with a raise-only PendingFoodPayment for P0
    (food 0, so the shortfall equals `owe`), P0 owning Schnapps Distiller and
    optionally a Fireplace (veg base rate 2). None cursor = the legacy bare
    mid-phase shape (in span for FEED/BREED)."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = _give_occupation(state, 0)
    if fireplace:
        state = with_majors(state, owner_by_idx={FIREPLACE_IDX: 0})
    p = state.players[0]
    p = fast_replace(p, resources=Resources(veg=veg, grain=grain),
                     harvest_conversions_used=used)
    frame = PendingFoodPayment(
        player_idx=0, food_needed=owe,
        resume_kind="_test_schnapps_resume", reserved=Cost())
    return dataclasses.replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2)),
        phase=phase, pending_stack=(frame,), harvest_cursor=cursor)


def test_feeding_frame_offers_schnapps_greedy_tiering():
    """The N>1 greedy tiering (ruling 77): owe 8, 5 veg, Fireplace (veg rate 2).
    Firing Schnapps (1 veg -> 5) then base-cooking 2 veg (-> 4) pays 9 keeping
    2 veg — dominating the all-base config (4 veg -> 8, keeping 1), which is
    therefore not offered. The offered CommitFoodPayment fires Schnapps and its
    `veg` field holds ONLY the base-cooked remainder (2), the premium veg being
    debited separately via the conversion."""
    s = _payment_state(owe=8, veg=5, fireplace=True)
    commits = [a for a in legal_actions(s) if isinstance(a, CommitFoodPayment)]
    assert commits and all(a.conversions == (CARD_ID,) for a in commits)
    target = commits[0]
    assert target.veg == 2                     # base-cooked remainder only
    nxt = step(s, target)
    p = nxt.players[0]
    assert p.resources.veg == 2                # 5 - (1 premium + 2 base)
    assert p.resources.food == 9               # 2*2 base + 5 premium (resume debits 0)
    assert CARD_ID in p.harvest_conversions_used


def test_feeding_frame_schnapps_single_veg():
    """The single-veg case (owe 5): Schnapps alone covers the owe, no base
    cooking — 1 veg -> 5 food, crops otherwise kept."""
    s = _payment_state(owe=5, veg=3)
    target = next(a for a in legal_actions(s)
                  if isinstance(a, CommitFoodPayment) and a.conversions == (CARD_ID,))
    assert target.veg == 0                      # no base cooking needed
    p = step(s, target).players[0]
    assert p.resources.veg == 2                 # only the 1 premium veg spent
    assert p.resources.food == 5
    assert CARD_ID in p.harvest_conversions_used


def test_field_and_breed_frames_do_not_offer_schnapps():
    """Phase scoping (the Studio pattern): an in-span FIELD/BREED raise frame is
    outside the feeding phase, so Schnapps (printed "in the feeding phase") is
    never offered — available_span_converters returns () and no commit fires it."""
    for phase, cursor in (
        (Phase.HARVEST_FIELD, sentinel_position("end_of_field_phase", 0)),
        (Phase.HARVEST_BREED, sentinel_position("after_breeding", 1)),
    ):
        s = _payment_state(owe=2, veg=3, phase=phase, cursor=cursor)
        assert available_span_converters(s, 0) == ()
        assert all(a.conversions == ()
                   for a in legal_actions(s) if isinstance(a, CommitFoodPayment))


def test_frontier_budget_shared_with_feed_seam_both_ways():
    """The once-per-harvest budget is shared across surfaces (the prefix guard):
    a recorded fire suppresses the payment frontier, and vice versa."""
    # Feed seam -> frontier: budget already spent this harvest.
    spent = _payment_state(owe=2, veg=3, used=frozenset({CARD_ID}))
    assert available_span_converters(spent, 0) == ()
    assert all(a.conversions == ()
               for a in legal_actions(spent) if isinstance(a, CommitFoodPayment))
    # Frontier -> feed seam: firing at the raise frame marks the shared id, so a
    # subsequent HARVEST_FEED frame offers no Schnapps conversion.
    s = _payment_state(owe=5, veg=3)
    nxt = step(s, next(a for a in legal_actions(s)
                       if isinstance(a, CommitFoodPayment)
                       and a.conversions == (CARD_ID,)))
    assert CARD_ID in nxt.players[0].harvest_conversions_used
