"""Tests for Resource Analyzer (occupation, deck C #157; Corbarius Expansion).

Card text: "Before the start of each round, if you have more building resources than
all other players of at least two types, you get 1 food."

A choiceless mandatory `start_of_round` auto-effect (register_auto) gated on the
owner holding STRICTLY MORE of at least two of the four building-resource types
{wood, clay, reed, stone} than the (single, 2-player) opponent. Mirrors the
Small-scale Farmer / Scullery auto-at-push tests in tests/test_cards_category7.py.
"""
import agricola.cards.resource_analyzer  # noqa: F401

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation
from agricola.legality import legal_actions
from agricola.pending import PendingPreparation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

CARD_ID = "resource_analyzer"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_resources(state, idx, **kw):
    p = state.players[idx]
    p = fast_replace(p, resources=Resources(**kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _prep(state, round_number=2):
    """A PREPARATION state ready for `_complete_preparation` to run the start-of-round."""
    return fast_replace(state, phase=Phase.PREPARATION, round_number=round_number)


def _food(state, idx):
    return state.players[idx].resources.food


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation():
    assert CARD_ID in OCCUPATIONS
    assert OCCUPATIONS[CARD_ID].on_play is not None


def test_registered_as_choiceless_start_of_round_auto():
    # Auto-effect (choiceless) -> lives in AUTO_EFFECTS, not the optional TRIGGERS list.
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("start_of_round", [])}
    assert CARD_ID in auto_ids
    opt_ids = {e.card_id for e in TRIGGERS.get("start_of_round", [])}
    assert CARD_ID not in opt_ids   # not an optional/mandatory FireTrigger


def test_on_play_is_noop():
    s = setup(0)
    before = s.players[0].resources
    s2 = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert s2.players[0].resources == before


# ---------------------------------------------------------------------------
# Real-flow effect — +1 food when ahead in >= 2 building-resource types
# ---------------------------------------------------------------------------

def test_income_when_ahead_in_two_types():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _set_resources(s, 0, wood=3, clay=3)          # ahead in wood and clay
    s = _set_resources(s, 1, wood=1, clay=1)
    s = _prep(s)
    before = _food(s, 0)
    after = _complete_preparation(s)
    assert _food(after, 0) == before + 1
    # The host frame is still pushed (owner has a start-of-round card).
    assert isinstance(after.pending_stack[-1], PendingPreparation)


def test_income_when_ahead_in_all_four_types():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _set_resources(s, 0, wood=2, clay=2, reed=2, stone=2)
    s = _set_resources(s, 1, wood=0, clay=0, reed=0, stone=0)
    s = _prep(s)
    before = _food(s, 0)
    after = _complete_preparation(s)
    assert _food(after, 0) == before + 1   # always exactly +1, regardless of count


def test_income_only_for_the_owner():
    # Owner is player 1; player 0 does not own the card and gets nothing.
    s = _own_occ(setup(0), 1, CARD_ID)
    s = _set_resources(s, 1, wood=5, clay=5, reed=5, stone=5)
    s = _set_resources(s, 0, wood=5, clay=5, reed=5, stone=5)   # ahead nowhere, but p1 owns
    s = _prep(s)
    f0, f1 = _food(s, 0), _food(s, 1)
    after = _complete_preparation(s)
    assert _food(after, 0) == f0           # non-owner unaffected
    assert _food(after, 1) == f1           # owner tied everywhere -> ineligible


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_no_income_when_ahead_in_only_one_type():
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _set_resources(s, 0, wood=5, clay=1, reed=1, stone=1)   # ahead only in wood
    s = _set_resources(s, 1, wood=1, clay=1, reed=1, stone=1)
    s = _prep(s)
    before = _food(s, 0)
    after = _complete_preparation(s)
    assert _food(after, 0) == before
    # Nothing left to do -> the only legal action is to Proceed (singleton).
    from agricola.actions import Proceed
    assert legal_actions(after) == [Proceed()]


def test_ties_do_not_count_strict_greater_required():
    # Equal counts in every type -> zero "surplus" types -> ineligible (">" not ">=").
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _set_resources(s, 0, wood=2, clay=2, reed=2, stone=2)
    s = _set_resources(s, 1, wood=2, clay=2, reed=2, stone=2)
    s = _prep(s)
    before = _food(s, 0)
    after = _complete_preparation(s)
    assert _food(after, 0) == before


def test_exactly_two_types_is_the_threshold():
    # Ahead in exactly two types (reed, stone); tied in wood; behind in clay -> eligible.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _set_resources(s, 0, wood=2, clay=1, reed=3, stone=3)
    s = _set_resources(s, 1, wood=2, clay=4, reed=1, stone=1)
    s = _prep(s)
    before = _food(s, 0)
    after = _complete_preparation(s)
    assert _food(after, 0) == before + 1


def test_only_building_resources_counted_not_food_grain_veg():
    # Owner is hugely ahead in food/grain/veg but tied in all building resources ->
    # ineligible (food/grain/veg are not "building resources").
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _set_resources(s, 0, wood=1, clay=1, reed=1, stone=1, food=9, grain=9, veg=9)
    s = _set_resources(s, 1, wood=1, clay=1, reed=1, stone=1)
    s = _prep(s)
    before = _food(s, 0)
    after = _complete_preparation(s)
    assert _food(after, 0) == before


# ---------------------------------------------------------------------------
# Scoping — re-checked each round
# ---------------------------------------------------------------------------

def test_eligibility_rechecked_each_round():
    # Ahead now -> income; drop behind -> no income next round.
    s = _own_occ(setup(0), 0, CARD_ID)
    s = _set_resources(s, 0, wood=3, clay=3)
    s = _set_resources(s, 1, wood=0, clay=0)
    after = _complete_preparation(_prep(s, round_number=2))
    assert _food(after, 0) == _food(s, 0) + 1

    # Now the opponent surges ahead; re-running the start-of-round yields nothing.
    s2 = _set_resources(after, 1, wood=9, clay=9, reed=9, stone=9)
    s2 = _set_resources(s2, 0, wood=0, clay=0, reed=0, stone=0)
    s2 = fast_replace(s2, pending_stack=())   # clear the prior host frame
    f0 = _food(s2, 0)
    after2 = _complete_preparation(_prep(s2, round_number=3))
    assert _food(after2, 0) == f0
