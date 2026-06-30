"""Tests for Cube Cutter (occupation, C98).

Card text: "When you play this card, you immediately get 1 wood. In the field
phase of each harvest, you can use this card to exchange exactly 1 wood and 1
food for 1 bonus point."

The exchange is surfaced as an optional once-per-harvest CommitHarvestConversion
during HARVEST_FEED (food_out=0, input_cost = 1 wood + 1 food); firing it banks a
bonus point in the per-card CardStore, read back at end-game by a scoring term.
These tests drive a REAL HARVEST_FEED resolution (via _initiate_harvest_feed +
step), not a poked frame. Cube Cutter has NO major/Joinery gate (unlike Furniture
Carpenter): owning the occupation is sufficient.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.cube_cutter  # noqa: F401  (register the card)

from agricola.actions import CommitConvert, CommitHarvestConversion, Stop
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestFeed
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup

from tests.factories import with_resources, with_phase

CARD_ID = "cube_cutter"


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


def _owner_state(*, owner_food=10, owner_wood=5, give_occ=True):
    """P0 owns Cube Cutter; P1 is food-rich so its feed resolves trivially.

    P0's people default (2 adults -> need 4 food). owner_food / owner_wood govern
    whether the 1-wood + 1-food exchange is affordable on top of feeding.
    """
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    state = with_resources(state, 0, food=owner_food, wood=owner_wood)
    state = with_resources(state, 1, food=99)
    return state


# --- Registration -----------------------------------------------------------

def test_registered_as_occupation_conversion_and_scoring():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in HARVEST_CONVERSIONS
    spec = HARVEST_CONVERSIONS[CARD_ID]
    # The exchange spends exactly 1 wood + 1 food and produces no food.
    assert spec.input_cost.wood == 1
    assert spec.input_cost.food == 1
    assert spec.food_out == 0
    assert spec.side_effect_fn is not None
    assert any(card_id == CARD_ID for card_id, _ in SCORING_TERMS)


# --- On-play: +1 wood -------------------------------------------------------

def test_on_play_grants_one_wood():
    state = setup(seed=0)
    wood0 = state.players[0].resources.wood
    on_play = OCCUPATIONS[CARD_ID].on_play
    state = on_play(state, 0)
    assert state.players[0].resources.wood == wood0 + 1
    # Opponent untouched.
    assert state.players[1].resources.wood == 0


# --- The exchange fires and banks a point -----------------------------------

def test_exchange_spends_wood_and_food_and_banks_one_point():
    state = _enter_feed(_owner_state(owner_food=10, owner_wood=5))
    assert _buy_actions(state) == [CommitHarvestConversion(conversion_id=CARD_ID)]

    food0 = state.players[0].resources.food
    wood0 = state.players[0].resources.wood
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))

    # 1 wood + 1 food spent, no food produced; one bonus point banked.
    assert state.players[0].resources.food == food0 - 1
    assert state.players[0].resources.wood == wood0 - 1
    assert state.players[0].card_state.get(CARD_ID, 0) == 1
    assert CARD_ID in state.players[0].harvest_conversions_used


def test_exchange_is_once_per_harvest():
    state = _enter_feed(_owner_state(owner_food=10, owner_wood=5))
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    # After one exchange this harvest, it is no longer offered (even with goods).
    assert _buy_actions(state) == []
    assert state.players[0].card_state.get(CARD_ID, 0) == 1


def test_exchange_is_optional_declinable():
    """Declining is implicit: commit the feed without firing the exchange."""
    state = _enter_feed(_owner_state(owner_food=10, owner_wood=5))
    # P0 has 10 food, needs 4 -> food_owed 0. CommitConvert resolves the feed
    # without ever firing the exchange.
    assert any(isinstance(a, CommitConvert) for a in legal_actions(state))
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert state.players[0].card_state.get(CARD_ID, 0) == 0


# --- Eligibility boundaries -------------------------------------------------

def test_not_offered_to_non_owner():
    """The conversion is global; only the occupation owner is offered it.

    Cube Cutter has no major gate, so this is the key ownership boundary: P0 owns
    it, P1 does not. Drive the whole two-player feed and assert only P0's frame
    offers the exchange.
    """
    state = _owner_state(owner_food=10, owner_wood=5)
    state = with_resources(state, 1, food=10, wood=5)  # P1 also goods-rich
    state = _enter_feed(state)

    saw_p0_buy = False
    saw_p1_buy = False
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
        actions = legal_actions(state)
        nxt = next(
            (a for a in actions if isinstance(a, CommitConvert)),
            next((a for a in actions if isinstance(a, Stop)), None),
        )
        assert nxt is not None
        state = step(state, nxt)

    assert saw_p0_buy       # the owner IS offered the exchange
    assert not saw_p1_buy   # the non-owner is NOT


def test_not_offered_when_wood_short():
    """Needs 1 wood; with 0 wood the exchange is unaffordable."""
    state = _enter_feed(_owner_state(owner_food=10, owner_wood=0))
    assert _buy_actions(state) == []


def test_not_offered_when_food_short():
    """Needs 1 food for the exchange itself; with 0 food it is unaffordable.

    The HARVEST_FEED enumerator gates the exchange on affordability of its OWN
    input cost (1 wood + 1 food) against current resources — feeding payment is
    deferred and settled separately, so the boundary is the exchange's own cost,
    not the player's feeding surplus.
    """
    state = _enter_feed(_owner_state(owner_food=0, owner_wood=5))
    assert _buy_actions(state) == []


# --- Accumulation + scoring -------------------------------------------------

def test_points_accumulate_across_harvests_and_score():
    base = _owner_state(owner_food=10, owner_wood=5)
    base_total, _ = score(base, 0)

    # Bank two points (simulating two harvests' exchanges) then score.
    p = base.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, 2))
    state = dataclasses.replace(base, players=(p, base.players[1]))

    # The owner's end-game score gains exactly the two banked points (owner-gated
    # by score()'s _owns(card_id) check).
    owner_total, _bd = score(state, 0)
    assert state.players[0].card_state.get(CARD_ID, 0) == 2
    assert owner_total == base_total + 2

    # The scoring fn reads the bank directly.
    fn = next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)
    assert fn(state, 0) == 2


def test_scoring_owner_gated_non_owner_reads_zero():
    """A non-owner with a stray card_state entry scores 0 (score() owner-gates)."""
    base = _owner_state(owner_food=10, owner_wood=5)
    # Give P1 (the non-owner) a stray banked count; score() must ignore it.
    p1 = base.players[1]
    p1 = dataclasses.replace(p1, card_state=p1.card_state.set(CARD_ID, 3))
    state = dataclasses.replace(base, players=(base.players[0], p1))
    p1_total, _ = score(state, 1)
    base_p1_total, _ = score(base, 1)
    assert p1_total == base_p1_total  # the stray bank contributes nothing
