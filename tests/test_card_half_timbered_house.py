"""Tests for Half-Timbered House (minor improvement, C30; Consul Dirigens).

Card text: "During scoring, you get 1 bonus point for each stone room you have.
You can only use one card to get bonus points for your stone house."
Cost 1 Wood / 1 Clay / 2 Stone / 1 Reed; no prereq; printed VPs: 0.

A "stone room" is a ROOM cell when the player's house is STONE — the house
material gates the bonus (wood/clay houses score 0). Mirrors
tests/test_cards_mantlepiece.py (a minor scoring card) for the play-via flow and
tests/test_card_fellow_grazer.py for the score-helper / owner-only structure.

Coverage:
  - registration (MINORS has the card; cost fields; in SCORING_TERMS)
  - the _score helper: STONE-house gate, ROOM-cell counting, wood/clay -> 0
  - owner-only scoring (opponent with a stone house scores nothing)
  - a real play-via-major_improvement engine flow, then scoring
"""
import agricola.cards.half_timbered_house  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.half_timbered_house import CARD_ID, _score
from agricola.cards.specs import MINORS
from agricola.constants import CellType, HouseMaterial
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.scoring import SCORING_GROUPS, SCORING_TERMS, score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_grid, with_house, with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _own_minor(state, idx, card_id):
    p = fast_replace(
        state.players[idx],
        minor_improvements=state.players[idx].minor_improvements | {card_id},
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_rooms(state, idx, room_cells):
    """Install ROOM cells at the given coordinates in player idx's grid."""
    return with_grid(
        state, idx, {(r, c): Cell(cell_type=CellType.ROOM) for (r, c) in room_cells}
    )


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _play_half_timbered(cs):
    """Drive playing Half-Timbered House via the major_improvement space (the standard
    minor-play entry point). Caller ensures the space is revealed + the card is in hand."""
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

GROUP_ID = "stone_house_bonus"


def test_registered_in_both_registries():
    assert CARD_ID in MINORS                                    # playable as a minor
    # Scores at end-game via the mutual-exclusion group (NOT the plain
    # SCORING_TERMS path — that would double-count with Luxurious Hostel).
    assert any(cid == CARD_ID for cid, _ in SCORING_GROUPS[GROUP_ID])
    assert not any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_registered_cost_fields():
    spec = MINORS[CARD_ID]
    res = spec.cost.resources
    assert (res.wood, res.clay, res.stone, res.reed) == (1, 1, 2, 1)
    assert spec.vps == 0  # bonus comes entirely from register_scoring


# ---------------------------------------------------------------------------
# The _score helper — STONE-house gate + ROOM-cell counting
# ---------------------------------------------------------------------------

def test_stone_house_scores_one_per_room():
    s = setup(0)  # default: 2 starting rooms, WOOD house
    s = with_house(s, 0, HouseMaterial.STONE)
    assert _score(s, 0) == 2  # the two starting rooms


def test_extra_rooms_counted():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.STONE)
    # Add a third room cell; now 3 stone rooms.
    s = _set_rooms(s, 0, [(0, 0)])
    assert _score(s, 0) == 3


def test_wood_house_scores_zero():
    s = setup(0)  # WOOD by default
    assert _score(s, 0) == 0


def test_clay_house_scores_zero():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.CLAY)
    # Rooms exist, but the house is clay -> not "stone rooms".
    assert _score(s, 0) == 0


def test_non_room_cells_not_counted():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.STONE)
    # A field cell is not a room, so it must not contribute.
    s = with_grid(s, 0, {(0, 3): Cell(cell_type=CellType.FIELD)})
    assert _score(s, 0) == 2  # still just the two starting rooms


# ---------------------------------------------------------------------------
# Scoring integration — owner-only, additive
# ---------------------------------------------------------------------------

def test_card_points_added_only_for_owner():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.STONE)  # 2 stone rooms
    s = with_house(s, 1, HouseMaterial.STONE)  # opponent also has a stone house

    # Not owned -> no card points from this card.
    base_total, bd = score(s, 0)
    assert bd.card_points == 0

    # Own Half-Timbered House -> +2 card points, total rises by exactly 2.
    s_owned = _own_minor(s, 0, CARD_ID)
    t2, bd2 = score(s_owned, 0)
    assert bd2.card_points == 2
    assert t2 == base_total + 2

    # The opponent (non-owner) gets nothing even with a stone house full of rooms.
    _t, bd3 = score(s_owned, 1)
    assert bd3.card_points == 0


# ---------------------------------------------------------------------------
# Played via the major_improvement space (no-op on play), then scores
# ---------------------------------------------------------------------------

def test_played_via_improvement_then_scores():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_house(cs, cp, HouseMaterial.STONE)  # 2 stone rooms
    # Affordability: cost is 1 wood / 1 clay / 2 stone / 1 reed.
    cs = with_resources(cs, cp, wood=1, clay=1, stone=2, reed=1)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    cs = _play_half_timbered(cs)
    assert CARD_ID in cs.players[cp].minor_improvements
    _t, bd = score(cs, cp)
    assert bd.card_points == 2  # two stone rooms after playing
