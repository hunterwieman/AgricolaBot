import agricola.cards.remodeling  # noqa: F401

"""Tests for Remodeling (minor improvement, C5).

Card text: "You immediately get 1 clay for each clay room and for each major
improvement you have." Cost 1 food, no prereq, no VPs, PASSING (traveling minor).

The on-play gain = (clay rooms) + (majors owned), where clay rooms are only
counted when the house is currently CLAY (mirroring the scoring idiom). The
gain may be 0, which is legal.
"""
from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.constants import CellType, HouseMaterial
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_house, with_majors, with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("remodeling",) + tuple(f"m{i}" for i in range(20)),
)


def _on_play(state, idx):
    return MINORS["remodeling"].on_play(state, idx)


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_remodeling_registered_with_food_cost_passing():
    spec = MINORS["remodeling"]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.passing_left is True   # traveling minor (passing_left='X')
    assert spec.vps == 0
    assert spec.prereq is None
    assert spec.on_play is not None


# ---------------------------------------------------------------------------
# On-play effect — direct
# ---------------------------------------------------------------------------

def test_wood_house_no_majors_gains_zero():
    # Starting state: WOOD house with 2 rooms, no majors -> 0 clay rooms, 0 majors.
    s = setup(0)
    assert s.players[0].house_material is HouseMaterial.WOOD
    before = s.players[0].resources.clay
    s2 = _on_play(s, 0)
    assert s2.players[0].resources.clay == before  # gain 0
    assert s2 is s  # no-op short-circuit returns the same state object


def test_clay_house_counts_clay_rooms():
    # CLAY house with 2 rooms -> +2 clay (no majors).
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.CLAY)
    s = with_resources(s, 0, clay=0)
    n_rooms = sum(
        1 for r in range(3) for c in range(5)
        if s.players[0].farmyard.grid[r][c].cell_type == CellType.ROOM
    )
    assert n_rooms == 2
    s2 = _on_play(s, 0)
    assert s2.players[0].resources.clay == 2


def test_stone_house_counts_zero_clay_rooms():
    # A STONE house has the same rooms but they are NOT clay rooms.
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.STONE)
    s = with_resources(s, 0, clay=0)
    s2 = _on_play(s, 0)
    assert s2.players[0].resources.clay == 0


def test_counts_majors_owned():
    # WOOD house (0 clay rooms) but owns 3 majors -> +3 clay.
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.WOOD)
    s = with_resources(s, 0, clay=0)
    s = with_majors(s, owner_by_idx={0: 0, 4: 0, 6: 0})
    s2 = _on_play(s, 0)
    assert s2.players[0].resources.clay == 3


def test_clay_rooms_plus_majors_combined():
    # CLAY house (2 rooms) + 1 owned major -> +3 clay.
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.CLAY)
    s = with_resources(s, 0, clay=1)  # existing clay is preserved (added to)
    s = with_majors(s, owner_by_idx={0: 0})
    s2 = _on_play(s, 0)
    assert s2.players[0].resources.clay == 1 + 2 + 1  # existing + 2 rooms + 1 major


def test_opponent_majors_do_not_count():
    # A major owned by the OPPONENT must not count for the player.
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.WOOD)
    s = with_resources(s, 0, clay=0)
    s = with_majors(s, owner_by_idx={0: 1, 4: 0})  # idx0->opp, idx4->self
    s2 = _on_play(s, 0)
    assert s2.players[0].resources.clay == 1  # only the self-owned major


def test_does_not_touch_opponent_resources():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.CLAY)
    opp_clay_before = s.players[1].resources.clay
    s2 = _on_play(s, 0)
    assert s2.players[1].resources.clay == opp_clay_before


# ---------------------------------------------------------------------------
# Real flow — play through an in-game entry point (Major Improvement space)
# ---------------------------------------------------------------------------

def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def test_remodeling_played_via_major_improvement_passes_to_opponent():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    # Give a CLAY house (2 rooms) + the food cost; zero starting clay to read gain.
    cs = with_house(cs, cp, HouseMaterial.CLAY)
    cs = with_resources(cs, cp, clay=0, food=1)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"remodeling"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "remodeling"))

    # CLAY house, 2 rooms, no majors -> +2 clay; food paid (1 -> 0).
    assert cs.players[cp].resources.clay == 2
    assert cs.players[cp].resources.food == 0
    # Passing: never enters the tableau; circulates to the opponent's hand.
    assert "remodeling" not in cs.players[cp].minor_improvements
    assert "remodeling" in cs.players[1 - cp].hand_minors
