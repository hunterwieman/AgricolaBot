"""Tests for the one-shot conditional latch (CARD_IMPLEMENTATION_PLAN.md II.3 / §6)
and the two Category-8 cards that ride it: Manservant + Clay Hut Builder.

A one-shot conditional is a LEVEL-triggered, once-per-game effect — "Once you live
in a stone house, …" (Manservant), "Once you no longer live in a wooden house, …"
(Clay Hut Builder). The standing condition can become true two ways: via a renovate,
or already be true the instant the card is played (you renovated first, then played
the card). Both moments call `engine._fire_ready_one_shots`, which fires every owned
conditional whose condition holds and hasn't fired yet, latching it in the per-game
`fired_once` set. Family game → `CONDITIONAL_ONE_SHOTS` empty → the sweep is a no-op.

These tests exercise `_fire_ready_one_shots` directly (the exact function the three
hook sites — renovate + both play-card paths — call) plus one end-to-end through a
real clay→stone renovate, to prove the wiring.
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    CommitRenovate,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CONDITIONAL_ONE_SHOTS, register_conditional
from agricola.constants import HouseMaterial
from agricola.engine import _fire_ready_one_shots
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import GameState
from tests.factories import (
    with_current_player,
    with_house,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_house(state, idx, material):
    p = fast_replace(state.players[idx], house_material=material)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _base(seed=0):
    """A round-1 card-mode state, current player 0, hands dropped."""
    cs, _env = setup_env(seed, card_pool=CardPool(
        occupations=("manservant", "clay_hut_builder") + tuple(f"o{i}" for i in range(20)),
        minors=tuple(f"m{i}" for i in range(20)),
    ))
    cs = with_current_player(cs, 0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


# ---------------------------------------------------------------------------
# Latch infrastructure
# ---------------------------------------------------------------------------

def test_latch_cards_registered():
    assert "manservant" in CONDITIONAL_ONE_SHOTS
    assert "clay_hut_builder" in CONDITIONAL_ONE_SHOTS
    assert "manservant" in OCCUPATIONS and "clay_hut_builder" in OCCUPATIONS


def test_latch_fires_once_and_is_idempotent():
    fires = []

    def _cond(state, idx):
        return True

    def _apply(state, idx):
        fires.append(idx)
        p = fast_replace(state.players[idx],
                         resources=state.players[idx].resources + Resources(food=1))
        return fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))

    register_conditional("_test_latch", _cond, _apply)
    try:
        s = _own_occ(_base(), 0, "_test_latch")
        s = _fire_ready_one_shots(s, 0)
        assert fires == [0]
        assert "_test_latch" in s.players[0].fired_once
        food1 = s.players[0].resources.food
        # Second sweep is a no-op — already latched.
        s = _fire_ready_one_shots(s, 0)
        assert fires == [0]
        assert s.players[0].resources.food == food1
    finally:
        CONDITIONAL_ONE_SHOTS.pop("_test_latch", None)


def test_latch_no_fire_when_condition_false():
    def _apply(state, idx):
        raise AssertionError("apply must not run when condition is false")

    register_conditional("_test_latch_false", lambda s, i: False, _apply)
    try:
        s = _own_occ(_base(), 0, "_test_latch_false")
        out = _fire_ready_one_shots(s, 0)
        assert "_test_latch_false" not in out.players[0].fired_once
    finally:
        CONDITIONAL_ONE_SHOTS.pop("_test_latch_false", None)


def test_latch_noop_when_unowned():
    fires = []
    register_conditional("_test_latch_unowned",
                         lambda s, i: True,
                         lambda s, i: (fires.append(i) or s))
    try:
        s = _base()   # nobody owns the card
        out = _fire_ready_one_shots(s, 0)
        assert fires == []
        assert "_test_latch_unowned" not in out.players[0].fired_once
    finally:
        CONDITIONAL_ONE_SHOTS.pop("_test_latch_unowned", None)


def test_latch_family_game_is_noop():
    # No conditional is registered in a Family game; the sweep returns the same object.
    from agricola.setup import setup
    s = setup(0)
    assert _fire_ready_one_shots(s, 0) is s


# ---------------------------------------------------------------------------
# Manservant — once in a stone house, +3 food on every remaining round space
# ---------------------------------------------------------------------------

def test_manservant_stone_schedules_remaining_rounds():
    s = _own_occ(_base(), 0, "manservant")
    s = _set_house(s, 0, HouseMaterial.STONE)   # condition already true
    assert s.round_number == 1
    out = _fire_ready_one_shots(s, 0)
    fr = out.players[0].future_rewards  # untouched (goods ride future_resources)
    res = out.players[0].future_resources
    # Rounds 2..14 each gain 3 food (slots 1..13); round 1 (slot 0) is unchanged.
    assert res[0].food == s.players[0].future_resources[0].food
    for slot in range(1, 14):
        assert res[slot].food == s.players[0].future_resources[slot].food + 3
    assert "manservant" in out.players[0].fired_once
    assert all(not r for r in fr)


def test_manservant_no_fire_in_clay_house():
    s = _own_occ(_base(), 0, "manservant")
    s = _set_house(s, 0, HouseMaterial.CLAY)   # not stone
    out = _fire_ready_one_shots(s, 0)
    assert "manservant" not in out.players[0].fired_once
    assert all(r.food == 0 for r in out.players[0].future_resources)


def test_manservant_fires_via_real_renovate():
    # End-to-end: own Manservant in a clay house, renovate clay→stone; the renovate
    # hook fires the latch and schedules the food.
    cs, _env = setup_env(5, card_pool=CardPool(
        occupations=("manservant",) + tuple(f"o{i}" for i in range(20)),
        minors=tuple(f"m{i}" for i in range(20))))
    cs = with_current_player(cs, 0)
    cs = with_house(cs, 0, HouseMaterial.CLAY)
    cs = with_resources(cs, 0, stone=2, reed=1)   # clay→stone cost
    cs = with_space(cs, "house_redevelopment", revealed=True)
    cs = _own_occ(cs, 0, "manservant")
    before = cs.players[0].future_resources[1].food
    cs = run_actions(cs, [
        PlaceWorker(space="house_redevelopment"),
        ChooseSubAction(name="renovate"),
        CommitRenovate(),
        Stop(),
        Proceed(),
        Stop(),
    ])
    assert cs.players[0].house_material == HouseMaterial.STONE
    assert "manservant" in cs.players[0].fired_once
    assert cs.players[0].future_resources[1].food == before + 3


# ---------------------------------------------------------------------------
# Clay Hut Builder — once no longer wooden, +2 clay on the next 5 round spaces
# ---------------------------------------------------------------------------

def test_clay_hut_builder_schedules_next_5_when_clay():
    s = _own_occ(_base(), 0, "clay_hut_builder")
    s = _set_house(s, 0, HouseMaterial.CLAY)   # != WOOD → condition true
    out = _fire_ready_one_shots(s, 0)
    res = out.players[0].future_resources
    # Rounds 2..6 (slots 1..5) each gain 2 clay; round 1 unchanged, round 7+ unchanged.
    assert res[0].clay == 0
    for slot in range(1, 6):
        assert res[slot].clay == 2
    assert res[6].clay == 0
    assert "clay_hut_builder" in out.players[0].fired_once


def test_clay_hut_builder_no_fire_in_wooden_house():
    s = _own_occ(_base(), 0, "clay_hut_builder")   # default house is WOOD
    out = _fire_ready_one_shots(s, 0)
    assert "clay_hut_builder" not in out.players[0].fired_once
    assert all(r.clay == 0 for r in out.players[0].future_resources)
