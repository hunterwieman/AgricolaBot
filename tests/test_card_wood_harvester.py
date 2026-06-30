"""Tests for Wood Harvester (occupation, A104; Artifex; harvest-field hook).

Card text: "In the field phase of each harvest, you get 1 wood/1 food for each wood
accumulation space with exactly 2 wood/at least 3 wood."

On the 2-player board the only wood accumulation space is the Forest, so the
effect reduces to a single read of `forest.accumulated.wood`:
  exactly 2  -> +1 wood
  at least 3 -> +1 food
  fewer than 2 -> nothing.

The income rides the field-phase card hook (Category 6): `_resolve_harvest_field`
fires the `harvest_field` automatic effects for each owner BEFORE the mechanical
crop take, but ONLY when some player owns a harvest-field card
(`should_host_harvest_field`). Most tests drive `_resolve_harvest_field` directly
(mirroring `tests/test_cards_category6.py`).
"""
from __future__ import annotations

import agricola.cards.wood_harvester  # noqa: F401  (registers the card)

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import HARVEST_FIELD_CARDS, should_host_harvest_field
from agricola.constants import Phase
from agricola.engine import _resolve_harvest_field
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import with_phase, with_space


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _field_state(seed=0):
    """A HARVEST_FIELD-phase state (no card owned yet)."""
    return with_phase(setup(seed), Phase.HARVEST_FIELD)


def _set_forest_wood(state, wood):
    return with_space(state, "forest", accumulated=Resources(wood=wood))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_wood_harvester_registered():
    assert "wood_harvester" in OCCUPATIONS
    assert "wood_harvester" in HARVEST_FIELD_CARDS
    # Occupation: no cost/prereq/vps/passing overrides — it isn't a minor.
    assert "wood_harvester" not in __import__(
        "agricola.cards.specs", fromlist=["MINORS"]
    ).MINORS


def test_on_play_is_noop():
    state = setup(0)
    before = state.players[0].resources
    after = OCCUPATIONS["wood_harvester"].on_play(state, 0)
    assert after.players[0].resources == before
    # Whole game state untouched by on-play (it's a pure no-op).
    assert after == state


# ---------------------------------------------------------------------------
# should_host_harvest_field — the card-dependent push gate
# ---------------------------------------------------------------------------

def test_no_host_without_card():
    assert should_host_harvest_field(setup(0)) is False


def test_host_when_owned():
    state = _own_occ(setup(0), 0, "wood_harvester")
    assert should_host_harvest_field(state) is True


def test_no_host_when_only_in_hand():
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {"wood_harvester"})
    state = fast_replace(state, players=(p, state.players[1]))
    assert should_host_harvest_field(state) is False


# ---------------------------------------------------------------------------
# The income table: ==2 -> +1 wood, >=3 -> +1 food, <2 -> nothing
# ---------------------------------------------------------------------------

def test_exactly_two_wood_grants_one_wood():
    state = _set_forest_wood(_own_occ(_field_state(), 0, "wood_harvester"), 2)
    w0 = state.players[0].resources.wood
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.wood == w0 + 1
    assert after.players[0].resources.food == f0       # NOT both clauses


def test_three_wood_grants_one_food():
    state = _set_forest_wood(_own_occ(_field_state(), 0, "wood_harvester"), 3)
    w0 = state.players[0].resources.wood
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 1
    assert after.players[0].resources.wood == w0       # NOT +1 wood too


def test_more_than_three_wood_still_only_one_food():
    state = _set_forest_wood(_own_occ(_field_state(), 0, "wood_harvester"), 5)
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 1


def test_one_wood_grants_nothing():
    state = _set_forest_wood(_own_occ(_field_state(), 0, "wood_harvester"), 1)
    w0 = state.players[0].resources.wood
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.wood == w0
    assert after.players[0].resources.food == f0


def test_zero_wood_grants_nothing():
    state = _set_forest_wood(_own_occ(_field_state(), 0, "wood_harvester"), 0)
    w0 = state.players[0].resources.wood
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.wood == w0
    assert after.players[0].resources.food == f0


# ---------------------------------------------------------------------------
# Owner-gating: fires only for the owner
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _set_forest_wood(_own_occ(_field_state(), 0, "wood_harvester"), 2)
    w0 = state.players[0].resources.wood
    w1 = state.players[1].resources.wood
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.wood == w0 + 1   # owner gains
    assert after.players[1].resources.wood == w1       # non-owner unchanged
