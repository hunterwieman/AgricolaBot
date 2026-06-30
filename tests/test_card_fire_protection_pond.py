"""Tests for Fire Protection Pond (minor improvement, A45; Artifex).

Card text: "Once you no longer live in a wooden house, place 1 food on each of the
next 6 round spaces. At the start of these rounds, you get the food."
cost: 1 Food. prereq: "Still in Wooden House" (== WOOD). No VPs, not passing.

A one-shot conditional latch (CARD_IMPLEMENTATION_PLAN.md II.3 / §6): the standing
condition `house_material != WOOD` is FALSE the instant the card is played (the
prereq pins play to a wooden house), so the latch only fires LATER, the first time
the owner renovates out of wood. `_fire_ready_one_shots` fires it once per game and
schedules +1 food on rounds R+1..R+6 (the fixed 6-round window), clamped to round 14.
"""
import agricola.cards.fire_protection_pond  # noqa: F401  (registers the card)

import pytest

from agricola.actions import ChooseSubAction, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CONDITIONAL_ONE_SHOTS
from agricola.constants import HouseMaterial
from agricola.engine import _fire_ready_one_shots
from agricola.legality import playable_minors
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_house, with_resources, with_space
from tests.test_utils import run_actions, sole_renovate

CARD_ID = "fire_protection_pond"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_house(state, idx, material):
    p = fast_replace(state.players[idx], house_material=material)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _base(seed=0):
    """A round-1 card-mode state, current player 0, hands dropped."""
    cs, _env = setup_env(seed, card_pool=CardPool(
        occupations=tuple(f"o{i}" for i in range(20)),
        minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
    ))
    cs = with_current_player(cs, 0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_and_conditional():
    assert CARD_ID in MINORS
    assert CARD_ID in CONDITIONAL_ONE_SHOTS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(food=1)
    assert spec.passing_left is False
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# Prerequisite — "Still in Wooden House"
# ---------------------------------------------------------------------------

def test_playable_only_while_wooden():
    # Wooden house + 1 food in hand -> playable.
    s = _base()
    s = _own_minor(s, 0, CARD_ID)   # also put it in hand for playability check
    p0 = fast_replace(s.players[0],
                      minor_improvements=frozenset(),
                      hand_minors=frozenset({CARD_ID}),
                      resources=Resources(food=1))
    s = fast_replace(s, players=(p0, s.players[1]))
    assert s.players[0].house_material == HouseMaterial.WOOD
    assert playable_minors(s, 0) == [CARD_ID]

    # Same hand/food but no longer wooden -> prereq fails -> not playable.
    s_clay = _set_house(s, 0, HouseMaterial.CLAY)
    assert playable_minors(s_clay, 0) == []


def test_not_playable_without_food():
    s = _base()
    p0 = fast_replace(s.players[0],
                      hand_minors=frozenset({CARD_ID}),
                      resources=Resources(food=0))
    s = fast_replace(s, players=(p0, s.players[1]))
    assert playable_minors(s, 0) == []


# ---------------------------------------------------------------------------
# The latch — fires once you no longer live in a wooden house
# ---------------------------------------------------------------------------

def test_no_fire_while_wooden():
    # Default house is WOOD -> condition false -> latch must not fire.
    s = _own_minor(_base(), 0, CARD_ID)
    assert s.players[0].house_material == HouseMaterial.WOOD
    out = _fire_ready_one_shots(s, 0)
    assert CARD_ID not in out.players[0].fired_once
    assert all(r.food == 0 for r in out.players[0].future_resources)


def test_fires_when_clay_and_schedules_next_6_rounds():
    s = _own_minor(_base(), 0, CARD_ID)
    s = _set_house(s, 0, HouseMaterial.CLAY)   # != WOOD -> condition true
    assert s.round_number == 1
    out = _fire_ready_one_shots(s, 0)
    res = out.players[0].future_resources
    # "next 6 round spaces" = rounds 2..7 (slots 1..6) each gain 1 food.
    assert res[0].food == 0                    # round 1 (current) untouched
    for slot in range(1, 7):
        assert res[slot].food == 1
    assert res[7].food == 0                     # round 8+ untouched (window is 6)
    assert CARD_ID in out.players[0].fired_once


def test_window_clamped_to_round_14():
    # Renovate out of wood late (round 12) -> only rounds 13,14 receive food;
    # the would-be slots past 14 are silently dropped.
    s = _own_minor(_base(), 0, CARD_ID)
    s = fast_replace(s, round_number=12)
    s = _set_house(s, 0, HouseMaterial.STONE)   # != WOOD
    out = _fire_ready_one_shots(s, 0)
    res = out.players[0].future_resources
    assert len(res) == 14
    assert res[12].food == 1   # round 13
    assert res[13].food == 1   # round 14
    # rounds 1..12 untouched
    assert all(res[i].food == 0 for i in range(12))


def test_fires_once_and_is_idempotent():
    s = _own_minor(_base(), 0, CARD_ID)
    s = _set_house(s, 0, HouseMaterial.CLAY)
    out = _fire_ready_one_shots(s, 0)
    food_after_first = [r.food for r in out.players[0].future_resources]
    # A second sweep must not double-schedule.
    out2 = _fire_ready_one_shots(out, 0)
    assert [r.food for r in out2.players[0].future_resources] == food_after_first


def test_noop_when_unowned():
    s = _set_house(_base(), 0, HouseMaterial.CLAY)   # condition true, but nobody owns it
    out = _fire_ready_one_shots(s, 0)
    assert CARD_ID not in out.players[0].fired_once
    assert all(r.food == 0 for r in out.players[0].future_resources)


# ---------------------------------------------------------------------------
# End-to-end: a real wood->clay renovate fires the latch
# ---------------------------------------------------------------------------

def test_fires_via_real_renovate():
    cs, _env = setup_env(5, card_pool=CardPool(
        occupations=tuple(f"o{i}" for i in range(20)),
        minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20))))
    cs = with_current_player(cs, 0)
    assert cs.players[0].house_material == HouseMaterial.WOOD
    # wood->clay cost = 1 clay per room (2 rooms) + 1 reed.
    cs = with_resources(cs, 0, clay=2, reed=1)
    cs = with_space(cs, "house_redevelopment", revealed=True)
    cs = _own_minor(cs, 0, CARD_ID)
    cs = fast_replace(cs, players=(
        fast_replace(cs.players[0], hand_minors=frozenset(), hand_occupations=frozenset()),
        fast_replace(cs.players[1], hand_minors=frozenset(), hand_occupations=frozenset()),
    ))
    before = [r.food for r in cs.players[0].future_resources]
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        sole_renovate,
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].house_material == HouseMaterial.CLAY
    assert CARD_ID in cs.players[0].fired_once
    res = cs.players[0].future_resources
    R = 1  # renovate happened in round 1
    for slot in range(R, R + 6):   # rounds 2..7 (slots 1..6)
        assert res[slot].food == before[slot] + 1
