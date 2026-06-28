"""Cost-modifier card tests for the base-game cards Carpenter's Parlor, Lumber Mill,
and Master Bricklayer (COST_MODIFIER_DESIGN.md).

Each card is checked BOTH at the `effective_payments` chokepoint (with a hand-built
`CostCtx`) AND end-to-end through the real action that routes the cost through it:
  - Carpenter's Parlor — a build_room whole-cost FORMULA (2 wood + 2 reed), conditional on
    a WOOD house. End-to-end via Farm Expansion build-rooms.
  - Lumber Mill — a −1-wood REDUCTION on build_major AND play_minor only (NOT rooms /
    renovation / stables). End-to-end via Major Improvement (a wood-costing major) and via
    the play-minor flow (corn_scoop, a 1-wood minor).
  - Master Bricklayer — a build_major STONE reduction equal to the rooms built beyond the
    two starting rooms. Checked at the chokepoint (0 added rooms = no discount; 1 added
    room = −1 stone; floored on a stoneless major).

The chokepoint helpers mirror tests/test_cost_modifiers.py (`_state_owning`, etc.).
"""
from __future__ import annotations

import agricola.cards.carpenters_parlor  # noqa: F401  (registers its room formula)
import agricola.cards.corn_scoop         # noqa: F401  (a 1-wood minor, for the play_minor test)
import agricola.cards.lumber_mill        # noqa: F401  (registers its −1-wood reductions)
import agricola.cards.master_bricklayer  # noqa: F401  (registers its stone reduction)
from agricola.actions import (
    ChooseSubAction,
    CommitBuildMajor,
    CommitBuildRoom,
    CommitPlayMinor,
    PlaceWorker,
)
from agricola.constants import CellType, GameMode, HouseMaterial
from agricola.cost import CostCtx
from agricola.engine import step
from agricola.legality import effective_payments, legal_actions, playable_minors
from agricola.pending import PendingBuildRooms, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import (
    with_current_player,
    with_grid,
    with_house,
    with_pending_stack,
    with_resources,
    with_space,
)

_GENEROUS = Resources(wood=20, clay=20, reed=20, stone=20)


def _state_owning(*card_ids, resources: Resources = _GENEROUS):
    """A real setup state with player 0 owning `card_ids` and `resources` (player 1
    untouched). Ownership goes in `occupations` — all `_owns` checks (occupations OR
    minor_improvements), so this works for minor cards too."""
    state = setup(0)
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids), resources=resources)
    return fast_replace(state, players=(p0, state.players[1]))


def _as_set(frontier) -> set:
    return set(frontier)


# ===========================================================================
# Carpenter's Parlor (minor) — build_room formula, only in a wood house.
# ===========================================================================

def test_carpenters_parlor_wood_room_formula_dominates_printed_base():
    # Wood house (setup default): the formula 2 wood + 2 reed dominates the printed
    # 5 wood + 2 reed -> a singleton frontier of just the formula cost.
    state = _state_owning("carpenters_parlor")
    ctx = CostCtx("build_room", Resources(wood=5, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=2, reed=2)}


def test_carpenters_parlor_does_not_apply_in_clay_house():
    # "Wooden rooms only" — in a clay house the formula does not apply, so the printed
    # clay-room cost is unchanged.
    state = _state_owning("carpenters_parlor")
    p0 = fast_replace(state.players[0], house_material=HouseMaterial.CLAY)
    state = fast_replace(state, players=(p0, state.players[1]))
    ctx = CostCtx("build_room", Resources(clay=5, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=5, reed=2)}


def _fe_state_owning(*card_ids, material: HouseMaterial, resources: Resources,
                     minors=frozenset()):
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_house(state, 0, material)
    state = with_resources(
        state, 0,
        **{f: getattr(resources, f) for f in
           ("wood", "clay", "reed", "stone", "food", "grain", "veg")
           if getattr(resources, f)},
    )
    state = with_space(state, "farm_expansion", revealed=True)
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids),
                      minor_improvements=frozenset(minors))
    return fast_replace(state, players=(p0, state.players[1]))


def _drive_to_build_rooms(state):
    state = step(state, PlaceWorker(space="farm_expansion"))
    state = step(state, ChooseSubAction(name="build_rooms"))
    rooms = [a for a in legal_actions(state) if isinstance(a, CommitBuildRoom)]
    assert rooms, "expected a legal room cell"
    return state, rooms[0]


def test_carpenters_parlor_room_formula_end_to_end():
    # Wood house: printed room = 5 wood + 2 reed; Carpenter's Parlor -> 2 wood + 2 reed,
    # a singleton -> debited inline at the build (no PendingChooseCost two-step).
    state = _fe_state_owning(
        material=HouseMaterial.WOOD, resources=Resources(wood=5, reed=2),
        minors=frozenset({"carpenters_parlor"}))
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)   # singleton, no two-step
    assert state.players[0].resources == Resources(wood=3)          # paid 2 wood + 2 reed


# ===========================================================================
# Lumber Mill (minor) — −1 wood on build_major AND play_minor ONLY.
# ===========================================================================

def test_lumber_mill_reduces_major_wood_cost():
    # A wood-costing major (idx 7 = 2 wood + 2 stone) -> 1 wood + 2 stone.
    state = _state_owning("lumber_mill")
    ctx = CostCtx("build_major", Resources(wood=2, stone=2), major_idx=7)
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=1, stone=2)}


def test_lumber_mill_floors_wood_at_zero_on_one_wood_major():
    # A 1-wood major (idx 4 = 1 wood + 3 stone) -> wood floored to 0 -> 3 stone only.
    state = _state_owning("lumber_mill")
    ctx = CostCtx("build_major", Resources(wood=1, stone=3), major_idx=4)
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(stone=3)}


def test_lumber_mill_does_not_affect_room_renovate_or_stable():
    # "Every improvement" = major OR minor only, NOT rooms / renovation / stables.
    state = _state_owning("lumber_mill")
    room = CostCtx("build_room", Resources(wood=5, reed=2))
    reno = CostCtx("renovate", Resources(wood=2, reed=1))
    stable = CostCtx("build_stable", Resources(wood=1))
    assert _as_set(effective_payments(state, 0, room)) == {Resources(wood=5, reed=2)}
    assert _as_set(effective_payments(state, 0, reno)) == {Resources(wood=2, reed=1)}
    assert _as_set(effective_payments(state, 0, stable)) == {Resources(wood=1)}


def test_lumber_mill_reduces_minor_play_cost():
    # play_minor chokepoint: a 2-wood minor cost -> 1 wood.
    state = _state_owning("lumber_mill")
    ctx = CostCtx("play_minor", Resources(wood=2), card_id="dummy")
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=1)}


def test_lumber_mill_discounts_wood_major_end_to_end():
    # Drive the real Major Improvement flow: idx 7 (2 wood + 2 stone) -> pay 1 wood + 2 stone.
    state = setup(0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=10, stone=10, clay=10, reed=10)
    state = with_space(state, "major_improvement", revealed=True)
    p0 = fast_replace(state.players[0], minor_improvements=frozenset({"lumber_mill"}))
    state = fast_replace(state, players=(p0, state.players[1]))
    state = step(state, PlaceWorker(space="major_improvement"))
    state = step(state, ChooseSubAction(name="improvement"))
    state = step(state, ChooseSubAction(name="build_major"))
    opts = [a.payment for a in legal_actions(state)
            if isinstance(a, CommitBuildMajor) and a.major_idx == 7]
    assert opts == [Resources(wood=1, stone=2)]
    state = step(state, CommitBuildMajor(major_idx=7, payment=opts[0]))
    assert state.board.major_improvement_owners[7] == 0
    # Paid 1 wood + 2 stone of the 10/10 held.
    assert state.players[0].resources.wood == 9
    assert state.players[0].resources.stone == 8


def test_lumber_mill_makes_wood_minor_cheaper_end_to_end():
    # corn_scoop costs 1 wood; Lumber Mill's −1 wood makes it free, so it is playable with
    # ZERO resources and the play debits 0 wood.
    state = setup(0)
    state = fast_replace(state, mode=GameMode.CARDS)
    p0 = fast_replace(
        state.players[0],
        hand_minors=frozenset({"corn_scoop"}),
        minor_improvements=frozenset({"lumber_mill"}),
        resources=Resources(),   # broke: only the −1-wood discount makes corn_scoop free
    )
    state = fast_replace(state, players=(p0, state.players[1]), current_player=0)
    assert "corn_scoop" in playable_minors(state, 0)
    state = with_pending_stack(
        state, [PendingPlayMinor(player_idx=0, initiated_by_id="lessons")])
    play = CommitPlayMinor(card_id="corn_scoop", payment=Resources())
    assert play in legal_actions(state)
    state = step(state, play)
    assert "corn_scoop" in state.players[0].minor_improvements
    assert state.players[0].resources.wood == 0


def test_lumber_mill_does_not_make_clay_minor_free():
    # The reduction is wood-only: a clay-costing minor is unaffected, so it stays
    # unaffordable with no clay (proving the reduction is scoped to wood).
    state = setup(0)
    state = fast_replace(state, mode=GameMode.CARDS)
    p0 = fast_replace(
        state.players[0],
        hand_minors=frozenset({"junk_room"}),   # 1 wood + 1 clay
        minor_improvements=frozenset({"lumber_mill"}),
        resources=Resources(wood=5),             # plenty of wood, no clay
    )
    state = fast_replace(state, players=(p0, state.players[1]), current_player=0)
    # Lumber Mill drops the wood by 1 but the 1 clay remains -> unaffordable at 0 clay.
    assert "junk_room" not in playable_minors(state, 0)


# ===========================================================================
# Master Bricklayer (occupation) — build_major stone reduction = rooms built beyond
# the two starting rooms.
# ===========================================================================

def test_master_bricklayer_no_discount_with_initial_house():
    # Initial house (2 rooms, 0 built onto it) -> no stone discount.
    state = _state_owning("master_bricklayer")
    ctx = CostCtx("build_major", Resources(wood=2, stone=2), major_idx=7)
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=2, stone=2)}


def test_master_bricklayer_one_added_room_minus_one_stone():
    # Add a ROOM at (0,0) -> 1 room beyond the initial 2 -> stone cost −1.
    state = _state_owning("master_bricklayer")
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    ctx = CostCtx("build_major", Resources(wood=2, stone=2), major_idx=7)
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=2, stone=1)}


def test_master_bricklayer_two_added_rooms_minus_two_stone():
    # Two added rooms (0,0) and (0,1) -> stone cost −2 (floored if it would go negative).
    state = _state_owning("master_bricklayer")
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM),
                                 (0, 1): Cell(cell_type=CellType.ROOM)})
    ctx = CostCtx("build_major", Resources(wood=2, stone=2), major_idx=7)
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=2, stone=0)}


def test_master_bricklayer_floors_on_stoneless_major():
    # A major with no stone (idx 0 = 2 clay) is unaffected even with added rooms (floor).
    state = _state_owning("master_bricklayer")
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    ctx = CostCtx("build_major", Resources(clay=2), major_idx=0)
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=2)}


def test_master_bricklayer_does_not_affect_room_or_renovate():
    # build_major only — rooms and renovation are untouched.
    state = _state_owning("master_bricklayer")
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    room = CostCtx("build_room", Resources(wood=5, reed=2))
    reno = CostCtx("renovate", Resources(clay=3, reed=1))
    assert _as_set(effective_payments(state, 0, room)) == {Resources(wood=5, reed=2)}
    assert _as_set(effective_payments(state, 0, reno)) == {Resources(clay=3, reed=1)}


def test_master_bricklayer_discounts_major_end_to_end():
    # Drive the real Major flow with 1 added room: idx 7 (2 wood + 2 stone) -> 2 wood + 1 stone.
    state = setup(0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=10, stone=10, clay=10, reed=10)
    state = with_space(state, "major_improvement", revealed=True)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    p0 = fast_replace(state.players[0], occupations=frozenset({"master_bricklayer"}))
    state = fast_replace(state, players=(p0, state.players[1]))
    state = step(state, PlaceWorker(space="major_improvement"))
    state = step(state, ChooseSubAction(name="improvement"))
    state = step(state, ChooseSubAction(name="build_major"))
    opts = [a.payment for a in legal_actions(state)
            if isinstance(a, CommitBuildMajor) and a.major_idx == 7]
    assert opts == [Resources(wood=2, stone=1)]
    state = step(state, CommitBuildMajor(major_idx=7, payment=opts[0]))
    assert state.board.major_improvement_owners[7] == 0
    assert state.players[0].resources.stone == 9   # paid 1 stone of 10


# ===========================================================================
# Stacking sanity: Lumber Mill + Master Bricklayer both bite build_major (wood + stone).
# ===========================================================================

def test_lumber_mill_and_master_bricklayer_stack_on_major():
    # Own both, 1 added room: idx 7 (2 wood + 2 stone) -> Lumber Mill −1 wood AND
    # Master Bricklayer −1 stone -> 1 wood + 1 stone.
    state = _state_owning("lumber_mill", "master_bricklayer")
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    ctx = CostCtx("build_major", Resources(wood=2, stone=2), major_idx=7)
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=1, stone=1)}
