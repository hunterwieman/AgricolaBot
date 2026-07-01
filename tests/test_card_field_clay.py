"""Tests for Field Clay (minor improvement, D5; Dulcinaria Expansion).

Card text: "You immediately get 1 clay for each planted field you have."
Cost: 1 Food. Prerequisite: 1 planted field. VPs: none. Not passing.

On-play one-shot resource provider: grants 1 clay per PLANTED field (a FIELD cell
holding a crop — grain or veg). A freshly-plowed-but-unsown FIELD does not count.
"""
from __future__ import annotations

import agricola.cards.field_clay  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState, get_space, with_space
from tests.factories import with_fields, with_resources, with_sown_fields
from tests.test_utils import sole_play_minor

CARD_ID = "field_clay"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _clay(state: GameState, idx: int) -> int:
    return state.players[idx].resources.clay


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_field_clay_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.min_occupations == 0           # the prereq is the custom predicate only
    assert spec.prereq is not None


# ---------------------------------------------------------------------------
# Prerequisite: 1 planted field — empty/plowed fields don't satisfy it
# ---------------------------------------------------------------------------

def test_prereq_requires_a_planted_field():
    spec = MINORS[CARD_ID]
    s = setup(0)
    # No fields at all → prereq not met.
    assert not prereq_met(spec, s, 0)
    # A plowed-but-unsown FIELD does NOT count as planted.
    s_plowed = with_fields(s, 0, [(0, 0)])
    assert not prereq_met(spec, s_plowed, 0)
    # A FIELD with grain on it IS planted → prereq met.
    s_grain = with_sown_fields(s, 0, grain_fields=[(0, 0)])
    assert prereq_met(spec, s_grain, 0)
    # A FIELD with veg on it IS planted → prereq met.
    s_veg = with_sown_fields(s, 0, veg_fields=[(0, 0)])
    assert prereq_met(spec, s_veg, 0)


# ---------------------------------------------------------------------------
# on_play counting — 1 clay per planted field; unsown fields excluded
# ---------------------------------------------------------------------------

def test_on_play_grants_one_clay_per_planted_field():
    s = setup(0)
    s = with_sown_fields(s, 0, grain_fields=[(0, 0), (0, 1)], veg_fields=[(0, 2)])
    before = _clay(s, 0)
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _clay(out, 0) == before + 3        # 3 planted fields → +3 clay


def test_on_play_excludes_unsown_fields():
    s = setup(0)
    # Two planted (grain) + two plowed-but-unsown fields. Only the planted ones count.
    s = with_sown_fields(s, 0, grain_fields=[(0, 0), (0, 1)])
    s = with_fields(s, 0, [(0, 2), (0, 3)])
    before = _clay(s, 0)
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _clay(out, 0) == before + 2        # only the 2 planted fields grant clay


def test_on_play_single_planted_field_grants_one():
    s = setup(0)
    s = with_sown_fields(s, 0, veg_fields=[(1, 1)])
    before = _clay(s, 0)
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _clay(out, 0) == before + 1


def test_on_play_only_owner_gains_clay():
    # The grant counts the OWNER's planted fields and credits only the owner.
    s = setup(0)
    s = with_sown_fields(s, 0, grain_fields=[(0, 0), (0, 1)])
    # Give the opponent planted fields too — they must not affect the owner's grant.
    s = with_sown_fields(s, 1, grain_fields=[(0, 0), (0, 1), (0, 2)])
    opp_before = _clay(s, 1)
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _clay(out, 0) == _clay(s, 0) + 2   # owner's 2 fields
    assert _clay(out, 1) == opp_before         # opponent untouched


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_field_clay_played_via_engine_grants_clay():
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, food=1)        # afford the 1-food cost
    cs = with_sown_fields(cs, cp, grain_fields=[(0, 0)], veg_fields=[(0, 1), (0, 2)])
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    food_before = cs.players[cp].resources.food
    clay_before = _clay(cs, cp)

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    assert CARD_ID in cs.players[cp].minor_improvements
    assert _clay(cs, cp) == clay_before + 3    # 3 planted fields → +3 clay
    assert cs.players[cp].resources.food == food_before - 1   # 1-food cost paid
