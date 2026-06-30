"""Tests for Feeding Dish (A66) — a minor improvement that grants 1 grain each
time you use an animal accumulation space while already owning an animal of that
type. The check is on the PRE-PURCHASE count (fires `before_action_space`, before
the bought animals are accommodated onto the player), per-space-type, threshold
>= 1 of that specific type.
"""
import agricola.cards.feeding_dish  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitAccommodate, PlaceWorker, Stop
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingCattleMarket,
    PendingPigMarket,
    PendingSheepMarket,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup

from tests.factories import with_animals, with_current_player, with_space


# space_id, pending type, the Animals field that space stocks
MARKETS = [
    ("sheep_market",  PendingSheepMarket,  "sheep"),
    ("pig_market",    PendingPigMarket,    "boar"),
    ("cattle_market", PendingCattleMarket, "cattle"),
]


def _give_feeding_dish(state, player_idx):
    p = state.players[player_idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {"feeding_dish"})
    return fast_replace(state, players=tuple(
        p if i == player_idx else state.players[i] for i in range(2)))


def _market_state(space_id, *, accumulated, owner_animals=None, owner=0):
    """P0 is active; the named market is revealed + stocked; P0 owns Feeding Dish
    and, optionally, some pre-existing animals (`owner_animals` = dict of fields)."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_space(state, space_id, revealed=True, accumulated_amount=accumulated)
    if owner_animals:
        state = with_animals(state, owner, **owner_animals)
    state = _give_feeding_dish(state, owner)
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert "feeding_dish" in MINORS
    spec = MINORS["feeding_dish"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# Fires on the matching market when already owning that animal type — and fires
# BEFORE the purchase (at PlaceWorker), on the pre-purchase count.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space_id, pending_type, field", MARKETS)
def test_fires_when_already_owning_that_type(space_id, pending_type, field):
    # Owner already has 1 of the relevant type before using the market.
    state = _market_state(space_id, accumulated=1, owner_animals={field: 1})
    g0 = state.players[0].resources.grain

    state = step(state, PlaceWorker(space=space_id))
    # before_action_space fires AT the push, before CommitAccommodate.
    assert isinstance(state.pending_stack[-1], pending_type)
    assert state.players[0].resources.grain == g0 + 1
    # The bought animal is still staged on `gained`, not yet on the player.
    assert getattr(state.players[0].animals, field) == 1  # only the pre-existing one


@pytest.mark.parametrize("space_id, pending_type, field", MARKETS)
def test_grain_awarded_only_once_per_use(space_id, pending_type, field):
    """A single market use grants exactly +1 grain across the whole flow."""
    state = _market_state(space_id, accumulated=1, owner_animals={field: 1})
    g0 = state.players[0].resources.grain
    state = step(state, PlaceWorker(space=space_id))
    # Commit the single bought animal (pick the legal CommitAccommodate keeping it).
    keep_one = next(
        a for a in legal_actions(state)
        if isinstance(a, CommitAccommodate) and getattr(a, field) >= 1
    )
    state = step(state, keep_one)
    # CommitAccommodate may flip to after-phase; drive the trailing Stop if present.
    if state.pending_stack and isinstance(state.pending_stack[-1], pending_type):
        assert legal_actions(state) == [Stop()]
        state = step(state, Stop())
    assert state.players[0].resources.grain == g0 + 1


# ---------------------------------------------------------------------------
# Eligibility boundaries: does NOT fire when not owning that type.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space_id, pending_type, field", MARKETS)
def test_no_fire_without_that_animal_type(space_id, pending_type, field):
    # Owner has NO animals at all.
    state = _market_state(space_id, accumulated=1)
    g0 = state.players[0].resources.grain
    state = step(state, PlaceWorker(space=space_id))
    assert state.players[0].resources.grain == g0  # no grain


def test_per_space_type_not_total_animals():
    """At Sheep Market, owning only cattle grants NOTHING (per-type, not any-animal)."""
    state = _market_state("sheep_market", accumulated=1, owner_animals={"cattle": 3})
    g0 = state.players[0].resources.grain
    state = step(state, PlaceWorker(space="sheep_market"))
    assert state.players[0].resources.grain == g0  # cattle does not count at Sheep Market


def test_matching_type_fires_even_with_other_types_present():
    """At Cattle Market, owning cattle (plus unrelated sheep) DOES fire."""
    state = _market_state("cattle_market", accumulated=1,
                          owner_animals={"cattle": 1, "sheep": 2})
    g0 = state.players[0].resources.grain
    state = step(state, PlaceWorker(space="cattle_market"))
    assert state.players[0].resources.grain == g0 + 1


# ---------------------------------------------------------------------------
# Owner-gating: does NOT fire for the non-owner's market use.
# ---------------------------------------------------------------------------

def test_does_not_fire_for_non_owner():
    """P1 owns Feeding Dish + cattle; P0 (active, no Feeding Dish) uses Cattle
    Market. P1 must NOT gain grain — the effect is owner-gated ("you")."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_space(state, "cattle_market", revealed=True, accumulated_amount=1)
    state = with_animals(state, 1, cattle=1)
    state = _give_feeding_dish(state, 1)
    g1 = state.players[1].resources.grain

    state = step(state, PlaceWorker(space="cattle_market"))
    assert state.players[1].resources.grain == g1  # P1 did not act -> no grain


def test_no_fire_on_non_market_space():
    """A non-animal-market space (e.g. forest) never triggers Feeding Dish."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_space(state, "forest", revealed=True, accumulated_amount=3)
    state = with_animals(state, 0, sheep=2)
    state = _give_feeding_dish(state, 0)
    g0 = state.players[0].resources.grain
    state = step(state, PlaceWorker(space="forest"))
    assert state.players[0].resources.grain == g0  # no grain from a wood space
