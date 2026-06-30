"""Tests for Gift Basket (minor improvement, B73; Bubulcus; kept).

Card text: "When you play this card, if you have exactly 2/3/4/5 rooms, you
immediately get 1 vegetable/food/grain/vegetable." Cost 1 reed; prereq
"3 Occupations"; 1 VP; kept (not passing).

Banded reward by exact room count: 2 -> veg, 3 -> food, 4 -> grain, 5 -> veg;
any other count (1, or 6+) grants nothing.
"""
import agricola.cards.gift_basket  # noqa: F401  (registers the card)

import pytest

from agricola.constants import CellType
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import with_grid, with_pending_stack
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("gift_basket",) + tuple(f"m{i}" for i in range(20)),
)


def _state(
    seed=5,
    *,
    cp_minors=frozenset(),
    cp_res=None,
    cp_occ=frozenset(),
    room_cells=(),
):
    """A 2-player card state with the current player's hand/occupations/resources
    set. ``room_cells`` adds ROOM cells (the starting house already has 2 rooms at
    (1,0) and (2,0)), so pass cells beyond those to raise the room count."""
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
    if room_cells:
        cs = with_grid(
            cs, cp, {rc: Cell(cell_type=CellType.ROOM) for rc in room_cells}
        )
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "gift_basket" in MINORS
    spec = MINORS["gift_basket"]
    assert spec.passing_left is False
    assert spec.min_occupations == 3
    assert spec.cost.resources == Resources(reed=1)
    assert spec.vps == 1


# ---------------------------------------------------------------------------
# Prerequisite: 3 occupations (a pure occupation-count have-check)
# ---------------------------------------------------------------------------

def test_prereq_needs_three_occupations():
    spec = MINORS["gift_basket"]
    # 2 occupations -> fails the occupation bound.
    cs, cp = _state(cp_occ=frozenset({"a", "b"}))
    assert not prereq_met(spec, cs, cp)
    # 3 occupations -> met.
    cs, cp = _state(cp_occ=frozenset({"a", "b", "c"}))
    assert prereq_met(spec, cs, cp)


def test_playable_only_when_prereq_and_cost_met():
    # Holds the card, has reed, 3 occupations -> playable.
    cs, cp = _state(
        cp_minors=frozenset({"gift_basket"}),
        cp_res=Resources(reed=1),
        cp_occ=frozenset({"a", "b", "c"}),
    )
    assert playable_minors(cs, cp) == ["gift_basket"]
    # No reed -> cost unaffordable.
    cs, cp = _state(
        cp_minors=frozenset({"gift_basket"}),
        cp_res=Resources(reed=0),
        cp_occ=frozenset({"a", "b", "c"}),
    )
    assert playable_minors(cs, cp) == []
    # Prereq unmet (only 2 occupations) -> not playable even with reed.
    cs, cp = _state(
        cp_minors=frozenset({"gift_basket"}),
        cp_res=Resources(reed=1),
        cp_occ=frozenset({"a", "b"}),
    )
    assert playable_minors(cs, cp) == []


# ---------------------------------------------------------------------------
# On-play banded reward via a real engine flow
# ---------------------------------------------------------------------------

def _play_and_count(room_cells):
    """Play Gift Basket through the engine from a state with the given EXTRA room
    cells, returning the resource delta (after - before) for the player."""
    cs, cp = _state(
        cp_minors=frozenset({"gift_basket"}),
        cp_res=Resources(reed=2),
        cp_occ=frozenset({"a", "b", "c"}),
        room_cells=room_cells,
    )
    before = cs.players[cp].resources
    cs = _push_minor(cs, cp)
    assert legal_actions(cs) == [sole_play_minor(cs, "gift_basket")]
    cs = step(cs, sole_play_minor(cs, "gift_basket"))
    p = cs.players[cp]
    # Kept (not passing): it lands in the tableau, not the opponent's hand.
    assert "gift_basket" in p.minor_improvements
    assert "gift_basket" not in p.hand_minors
    assert "gift_basket" not in cs.players[1 - cp].hand_minors
    # 1 reed paid out of the 2 we held.
    assert p.resources.reed == before.reed - 1
    after = p.resources
    return Resources(
        veg=after.veg - before.veg,
        food=after.food - before.food,
        grain=after.grain - before.grain,
    )


def test_two_rooms_grants_veg():
    # Starting house = exactly 2 rooms.
    assert _play_and_count(()) == Resources(veg=1)


def test_three_rooms_grants_food():
    assert _play_and_count(((0, 0),)) == Resources(food=1)


def test_four_rooms_grants_grain():
    assert _play_and_count(((0, 0), (0, 1))) == Resources(grain=1)


def test_five_rooms_grants_veg():
    assert _play_and_count(((0, 0), (0, 1), (0, 2))) == Resources(veg=1)


def test_six_rooms_grants_nothing():
    # 6 rooms is outside the {2,3,4,5} table -> no reward.
    assert _play_and_count(((0, 0), (0, 1), (0, 2), (0, 3))) == Resources()
