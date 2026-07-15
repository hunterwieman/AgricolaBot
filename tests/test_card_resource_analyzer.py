"""Tests for Resource Analyzer (occupation, C157; Corbarius Expansion).

Card text: "Before the start of each round, if you have more building resources
than all other players of at least two types, you get 1 food."

A choice-free automatic effect on the preparation ladder's before_round window
(the Small Animal Breeder rung). "Building resources" are wood/clay/reed/stone;
"more ... than all other players of at least two types" fires when the owner
strictly leads the (single) opponent in >= 2 of those four types. Exercised by
driving _complete_preparation (the compat seam that walks the whole ladder,
firing the before_round window's autos).
"""
from __future__ import annotations

import agricola.cards.resource_analyzer  # noqa: F401  (registers the card)

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import with_resources

CARD_ID = "resource_analyzer"


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _prep(state, round_number):
    return fast_replace(state, phase=Phase.PREPARATION, round_number=round_number - 1)


def _state(owner_res: dict, opp_res: dict, *, round_number=3):
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, **owner_res)
    s = with_resources(s, 1, **opp_res)
    return _prep(s, round_number)


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_round", ())}
    assert CARD_ID in auto_ids
    # Not on start_of_round — "before the start of each round" is the earlier rung.
    assert CARD_ID not in {e.card_id for e in AUTO_EFFECTS.get("start_of_round", ())}


# --- The condition: strictly leading in >= 2 building-resource types ---------

def test_income_when_ahead_in_two_types():
    s = _state({"wood": 3, "clay": 2}, {"wood": 1, "clay": 1})
    after = _complete_preparation(s)
    assert after.players[0].resources.food == 1     # 0 (with_resources) + 1


def test_no_income_when_ahead_in_only_one_type():
    s = _state({"wood": 3, "clay": 1}, {"wood": 1, "clay": 5})
    after = _complete_preparation(s)
    assert after.players[0].resources.food == 0


def test_income_when_ahead_in_three_types_still_just_one_food():
    s = _state({"wood": 3, "clay": 3, "reed": 3, "stone": 0},
               {"wood": 1, "clay": 1, "reed": 1, "stone": 9})
    after = _complete_preparation(s)
    assert after.players[0].resources.food == 1


def test_ties_do_not_count():
    # Equal in wood and clay (ties are not "more"), ahead only in reed → 1 type.
    s = _state({"wood": 2, "clay": 2, "reed": 5}, {"wood": 2, "clay": 2, "reed": 1})
    after = _complete_preparation(s)
    assert after.players[0].resources.food == 0


def test_food_and_grain_are_not_building_resources():
    # Leading in food and grain only (not building resources) → no income.
    s = _state({"food": 9, "grain": 9}, {"food": 0, "grain": 0})
    after = _complete_preparation(s)
    # Owner had 9 food; no +1 (the lead is in non-building goods).
    assert after.players[0].resources.food == 9


def test_only_owner_gets_income():
    # Both lead their opponent in 2 types, but only P0 owns the card.
    s = _own_occ(setup(0), 0)
    s = with_resources(s, 0, wood=5, clay=5)
    s = with_resources(s, 1, wood=1, clay=1)
    s = _prep(s, 4)
    after = _complete_preparation(s)
    assert after.players[0].resources.food == 1
    assert after.players[1].resources.food == 0     # non-owner unaffected
