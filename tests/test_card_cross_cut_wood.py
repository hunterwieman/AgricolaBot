"""Tests for Cross-Cut Wood (minor improvement, D4; Dulcinaria; kept).

Card text: "You immediately get a number of wood equal to the number of stone in
your supply." Cost 1 food; prereq "3 Occupations"; no VPs; kept (not passing).

The reward is read from the CURRENT supply at play time: wood gained = the owner's
stone count. The stone is not spent (only a multiplier); 0 stone -> nothing gained.
"""
import agricola.cards.cross_cut_wood  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "cross_cut_wood"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _state(
    seed=5,
    *,
    cp_minors=frozenset(),
    cp_res=None,
    cp_occ=frozenset(),
):
    """A 2-player card state with the current player's hand/occupations/resources set."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    changes = {
        "hand_minors": cp_minors,
        "occupations": cp_occ,
    }
    if cp_res is not None:
        changes["resources"] = cp_res
    p = fast_replace(p, **changes)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.passing_left is True   # traveling minor (passing_left='X')
    assert spec.min_occupations == 3
    assert spec.cost.resources == Resources(food=1)
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# Prerequisite: 3 occupations (a pure occupation-count have-check)
# ---------------------------------------------------------------------------

def test_prereq_needs_three_occupations():
    spec = MINORS[CARD_ID]
    # 2 occupations -> fails the occupation bound.
    cs, cp = _state(cp_occ=frozenset({"a", "b"}))
    assert not prereq_met(spec, cs, cp)
    # 3 occupations -> met.
    cs, cp = _state(cp_occ=frozenset({"a", "b", "c"}))
    assert prereq_met(spec, cs, cp)


def test_playable_only_when_prereq_and_cost_met():
    # Holds the card, has 1 food, 3 occupations -> playable.
    cs, cp = _state(
        cp_minors=frozenset({CARD_ID}),
        cp_res=Resources(food=1),
        cp_occ=frozenset({"a", "b", "c"}),
    )
    assert playable_minors(cs, cp) == [CARD_ID]
    # No food -> cost unaffordable.
    cs, cp = _state(
        cp_minors=frozenset({CARD_ID}),
        cp_res=Resources(food=0),
        cp_occ=frozenset({"a", "b", "c"}),
    )
    assert playable_minors(cs, cp) == []
    # Prereq unmet (only 2 occupations) -> not playable even with food.
    cs, cp = _state(
        cp_minors=frozenset({CARD_ID}),
        cp_res=Resources(food=1),
        cp_occ=frozenset({"a", "b"}),
    )
    assert playable_minors(cs, cp) == []


# ---------------------------------------------------------------------------
# On-play reward via a real engine flow: wood gained = current stone count
# ---------------------------------------------------------------------------

def _play_and_delta(stone):
    """Play Cross-Cut Wood through the engine from a state holding ``stone`` stone
    (plus 1 food to pay the cost), returning the (after - before) resource delta."""
    cs, cp = _state(
        cp_minors=frozenset({CARD_ID}),
        cp_res=Resources(food=1, stone=stone),
        cp_occ=frozenset({"a", "b", "c"}),
    )
    before = cs.players[cp].resources
    cs = _push_minor(cs, cp)
    assert legal_actions(cs) == [sole_play_minor(cs, CARD_ID)]
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    p = cs.players[cp]
    # Kept (not passing): it lands in the tableau, not the opponent's hand.
    assert CARD_ID not in p.minor_improvements   # passing -> not kept
    assert CARD_ID not in p.hand_minors
    assert CARD_ID in cs.players[1 - cp].hand_minors  # circulated to opponent
    # 1 food paid for the cost.
    assert p.resources.food == before.food - 1
    after = p.resources
    return Resources(
        wood=after.wood - before.wood,
        stone=after.stone - before.stone,
    )


def test_three_stone_grants_three_wood():
    # Stone is the multiplier and is NOT consumed.
    assert _play_and_delta(3) == Resources(wood=3, stone=0)


def test_one_stone_grants_one_wood():
    assert _play_and_delta(1) == Resources(wood=1, stone=0)


def test_zero_stone_grants_nothing():
    # No stone in supply -> no wood gained (and no stone change).
    assert _play_and_delta(0) == Resources(wood=0, stone=0)


def test_large_stone_count_scales():
    assert _play_and_delta(7) == Resources(wood=7, stone=0)


# ---------------------------------------------------------------------------
# Reward reads CURRENT supply: pre-existing wood is preserved, stone untouched
# ---------------------------------------------------------------------------

def test_preexisting_wood_preserved_and_stone_not_spent():
    cs, cp = _state(
        cp_minors=frozenset({CARD_ID}),
        cp_res=Resources(food=1, wood=2, stone=4),
        cp_occ=frozenset({"a", "b", "c"}),
    )
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    p = cs.players[cp]
    # Started with 2 wood + 4 stone -> gain 4 wood (= stone count); stone unchanged.
    assert p.resources.wood == 2 + 4
    assert p.resources.stone == 4
