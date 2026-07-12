"""Tests for Field Clay (minor improvement, D5; Dulcinaria Expansion).

Card text: "You immediately get 1 clay for each planted field you have."
Cost: 1 Food. Prerequisite: 1 planted field. VPs: none. PASSING (traveling minor).

On-play one-shot resource provider: grants 1 clay per PLANTED field (a FIELD cell
holding a crop — grain or veg). A freshly-plowed-but-unsown FIELD does not count.
"""
from __future__ import annotations

import agricola.cards.field_clay  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.card_fields import stacks_to_store
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
    assert spec.passing_left is True   # traveling minor (passing_left='X')
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
# Card-fields (ruling 45, 2026-07-12): "planted field" is a field-count
# reader — a card-field holding ANYTHING is a planted field (1 per card,
# ruling 47; a wood-planted card counts — it IS planted).
# ---------------------------------------------------------------------------

def _own_card_field(state, idx, cid, stacks=None):
    """Give player `idx` the card-field `cid` in play, optionally with contents."""
    p = state.players[idx]
    store = (stacks_to_store(p.card_state, cid, stacks)
             if stacks is not None else p.card_state)
    p = fast_replace(p, minor_improvements=p.minor_improvements | {cid},
                     card_state=store)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def test_prereq_met_only_via_a_card_field():
    """Boundary the pre-ruling-45 code failed: no grid fields at all — a
    veg-holding Beanfield alone satisfies the 1-planted-field prerequisite
    and pays 1 clay."""
    spec = MINORS[CARD_ID]
    s = _own_card_field(setup(0), 0, "beanfield", [(0, 2, 0, 0)])
    assert prereq_met(spec, s, 0)
    before = _clay(s, 0)
    out = spec.on_play(s, 0)
    assert _clay(out, 0) == before + 1


def test_wood_planted_card_field_counts_as_planted():
    """A wood-planted Wood Field IS a planted field (its own text says "plant
    wood on this card") — it satisfies the prereq and pays 1 clay (once,
    however many stacks — ruling 47)."""
    spec = MINORS[CARD_ID]
    s = _own_card_field(setup(0), 0, "wood_field", [(0, 0, 3, 0), (0, 0, 3, 0)])
    assert prereq_met(spec, s, 0)
    before = _clay(s, 0)
    out = spec.on_play(s, 0)
    assert _clay(out, 0) == before + 1        # 1 field, not 2 (per-card count)


def test_unsown_card_field_is_not_planted():
    """A never-sown Beanfield holds nothing — not planted: the prereq stays
    unmet and the count stays 0."""
    spec = MINORS[CARD_ID]
    s = _own_card_field(setup(0), 0, "beanfield")
    assert not prereq_met(spec, s, 0)
    before = _clay(s, 0)
    out = spec.on_play(s, 0)
    assert _clay(out, 0) == before


def test_on_play_adds_card_fields_to_grid_planted_fields():
    s = setup(0)
    s = with_sown_fields(s, 0, grain_fields=[(0, 0), (0, 1)])
    s = _own_card_field(s, 0, "beanfield", [(0, 2, 0, 0)])
    before = _clay(s, 0)
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _clay(out, 0) == before + 3        # 2 grid + 1 card-field


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

    assert CARD_ID not in cs.players[cp].minor_improvements  # passing -> not kept
    assert CARD_ID in cs.players[1 - cp].hand_minors          # circulated to opponent
    assert _clay(cs, cp) == clay_before + 3    # 3 planted fields → +3 clay
    assert cs.players[cp].resources.food == food_before - 1   # 1-food cost paid
