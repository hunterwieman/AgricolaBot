import agricola.cards.brick_hammer  # noqa: F401

"""Tests for Brick Hammer (minor, D80): "Each time after you build an
improvement costing at least 2 clay, you get 1 stone."

USER RULING (2026-07-20): "costing at least 2 clay" reads the PRINTED cost,
never the payment made — an improvement with ANY printed alternative of >=2
clay qualifies even when paid via a non-clay alternative (headline case: a
Cooking Hearth bought by returning a Fireplace).

Every test drives the real engine flow (Major Improvement space builds and
minor plays through the improvement branch), mirroring the Junk Room tests
(tests/test_cards_category5.py) — the other after_build_improvement consumer.
"""
from agricola.actions import ChooseSubAction, PlaceWorker, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS, BUILD_MAJOR_IDENTITY_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import (
    with_current_player,
    with_majors,
    with_resources,
    with_space,
)
from tests.test_utils import build_major, play_minor, run_actions

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(22)),
    minors=("brick_hammer", "chophouse", "bee_statue")
    + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    # Drop both hands so deterministic plays come only from what a test grants.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give_hand_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, hand_minors=p.hand_minors | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _unwind(state):
    """Pop the remaining after-phase frames by declining everything: step Stop
    until the stack is empty (asserting Stop stays legal — the walk offers
    only optional continuations after the build/play commit)."""
    guard = 0
    while state.pending_stack:
        la = legal_actions(state)
        assert Stop() in la, f"expected Stop legal, got {la!r}"
        state = step(state, Stop())
        guard += 1
        assert guard < 12, "unwind did not terminate"
    return state


def _build_major_flow(state, major_idx, fireplace=None):
    """Drive a real Major Improvement space build of `major_idx`, then unwind."""
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="improvement"),
        ChooseSubAction(name="build_major"),
        build_major(major_idx, fireplace),
    ])
    return _unwind(state)


def _play_minor_flow(state, card_id):
    """Drive a real minor play via the Major Improvement space's play-minor
    branch, then unwind."""
    state = run_actions(state, [
        PlaceWorker(space="major_improvement"),
        ChooseSubAction(name="improvement"),
        ChooseSubAction(name="play_minor"),
        play_minor(card_id),
    ])
    return _unwind(state)


# ---------------------------------------------------------------------------
# Registration (subset checks, never exact-set)
# ---------------------------------------------------------------------------

def test_brick_hammer_registered():
    assert "brick_hammer" in MINORS
    spec = MINORS["brick_hammer"]
    # Printed cost "1 Wood / 1 Food" — an alternative cost, pay one.
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.alt_costs == (Cost(resources=Resources(food=1)),)
    assert spec.vps == 0
    assert not spec.passing_left
    assert "brick_hammer" in BUILD_MAJOR_IDENTITY_CARDS
    assert any(e.card_id == "brick_hammer"
               for e in AUTO_EFFECTS.get("after_build_improvement", ()))


# ---------------------------------------------------------------------------
# Major improvement builds
# ---------------------------------------------------------------------------

def test_clay_oven_build_grants_stone():
    # Clay Oven (major_idx 5): printed 3 clay + 1 stone -> qualifies.
    cs = _card_state()
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = _own_minor(cs, 0, "brick_hammer")
    cs = with_resources(cs, 0, clay=3, stone=1)
    cs = _build_major_flow(cs, 5)
    assert cs.board.major_improvement_owners[5] == 0
    # Paid the 1-stone cost, gained 1 stone from Brick Hammer.
    assert cs.players[0].resources.stone == 1


def test_stone_oven_build_grants_nothing():
    # Stone Oven (major_idx 6): printed 1 clay + 3 stone -> only 1 clay, no fire.
    cs = _card_state()
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = _own_minor(cs, 0, "brick_hammer")
    cs = with_resources(cs, 0, clay=1, stone=3)
    cs = _build_major_flow(cs, 6)
    assert cs.board.major_improvement_owners[6] == 0
    assert cs.players[0].resources.stone == 0    # paid all 3; no bonus


def test_cooking_hearth_via_returned_fireplace_grants_stone():
    # The ruling's headline case: build Cooking Hearth (major_idx 2, printed
    # 4 clay) by RETURNING a Fireplace — no clay paid, but the printed cost
    # qualifies -> +1 stone.
    cs = _card_state()
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = with_majors(cs, owner_by_idx={0: 0})    # P0 owns Fireplace (idx 0)
    cs = _own_minor(cs, 0, "brick_hammer")
    assert cs.players[0].resources.clay == 0     # cannot be paying clay
    cs = _build_major_flow(cs, 2, fireplace=0)
    assert cs.board.major_improvement_owners[2] == 0
    assert cs.board.major_improvement_owners[0] is None   # Fireplace returned
    assert cs.players[0].resources.stone == 1


# ---------------------------------------------------------------------------
# Minor improvement plays
# ---------------------------------------------------------------------------

def test_minor_with_2_clay_printed_cost_grants_stone():
    # Bee Statue's printed cost is 2 clay -> qualifies.
    cs = _card_state()
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = _own_minor(cs, 0, "brick_hammer")
    cs = _give_hand_minor(cs, 0, "bee_statue")
    cs = with_resources(cs, 0, clay=2)
    cs = _play_minor_flow(cs, "bee_statue")
    assert "bee_statue" in cs.players[0].minor_improvements
    assert cs.players[0].resources.stone == 1


def test_minor_paid_via_non_clay_alternative_grants_stone():
    # Chophouse is printed "2 Wood / 2 Clay". Pay the WOOD alternative (only
    # wood affordable -> the wood commit is the sole legal play): the 2-clay
    # printed ALTERNATIVE still qualifies per the 2026-07-20 ruling.
    cs = _card_state()
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = _own_minor(cs, 0, "brick_hammer")
    cs = _give_hand_minor(cs, 0, "chophouse")
    cs = with_resources(cs, 0, wood=2)           # clay stays 0
    cs = _play_minor_flow(cs, "chophouse")
    assert "chophouse" in cs.players[0].minor_improvements
    assert cs.players[0].resources.wood == 0     # paid the wood alternative
    assert cs.players[0].resources.stone == 1    # printed alternative qualified


# ---------------------------------------------------------------------------
# No-fire gates
# ---------------------------------------------------------------------------

def test_opponent_build_grants_nothing():
    # P1 builds a Fireplace (2 clay, qualifying) while P0 owns Brick Hammer:
    # "you build" is own builds only -> neither player gains a stone.
    cs = _card_state()
    cs = with_current_player(cs, 1)
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = _own_minor(cs, 0, "brick_hammer")
    cs = with_resources(cs, 1, clay=2)
    cs = _build_major_flow(cs, 0)
    assert cs.board.major_improvement_owners[0] == 1
    assert cs.players[0].resources.stone == 0
    assert cs.players[1].resources.stone == 0


def test_hand_card_does_not_fire():
    # Brick Hammer still in HAND (not played): a qualifying build grants nothing.
    cs = _card_state()
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = _give_hand_minor(cs, 0, "brick_hammer")
    cs = with_resources(cs, 0, clay=2)
    cs = _build_major_flow(cs, 0)                # Fireplace: printed 2 clay
    assert cs.board.major_improvement_owners[0] == 0
    assert cs.players[0].resources.stone == 0


# ---------------------------------------------------------------------------
# Brick Hammer's own play costs (1 Wood / 1 Food)
# ---------------------------------------------------------------------------

def test_play_brick_hammer_paying_wood():
    cs = _card_state()
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = _give_hand_minor(cs, 0, "brick_hammer")
    cs = with_resources(cs, 0, wood=1)           # food stays 0 -> wood is sole path
    cs = _play_minor_flow(cs, "brick_hammer")
    assert "brick_hammer" in cs.players[0].minor_improvements
    assert cs.players[0].resources.wood == 0     # paid 1 wood
    # Its own play fires after_build_improvement, but its printed cost
    # (1 wood / 1 food) has no clay -> no self-granted stone.
    assert cs.players[0].resources.stone == 0


def test_play_brick_hammer_paying_food():
    cs = _card_state()
    cs = with_space(cs, "major_improvement", revealed=True)
    cs = _give_hand_minor(cs, 0, "brick_hammer")
    cs = with_resources(cs, 0, food=1)           # wood stays 0 -> food is sole path
    food0 = cs.players[0].resources.food
    cs = _play_minor_flow(cs, "brick_hammer")
    assert "brick_hammer" in cs.players[0].minor_improvements
    assert cs.players[0].resources.food == food0 - 1   # paid 1 food
    assert cs.players[0].resources.stone == 0
