"""Tests for Straw-Thatched Roof (minor C14): "You no longer need reed to renovate or
build a room." Free; prereq 3 Grain Fields; 1 VP.

Covered: registration (spec + the two reductions), the chokepoint effect on `renovate`
and `build_room` (the FULL reed component removed, incl. a 2-reed cost — not a fixed −1),
the floor-at-0 no-op on a reed-free cost, the 3-grain-fields prerequisite boundary
(2 vs 3; veg fields and unsown fields don't count), end-to-end through House
Redevelopment (renovate) and Farm Expansion (build_room), scoping (only the owner gets
the discount; build_major is untouched), and the printed VP.
"""
from __future__ import annotations

import agricola.cards.straw_thatched_roof  # noqa: F401  (registers spec + reductions)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    CommitRenovate,
    PlaceWorker,
)
from agricola.constants import CellType, HouseMaterial
from agricola.cards.cost_mods import REDUCTIONS
from agricola.cards.specs import MINORS, prereq_met
from agricola.cost import CostCtx
from agricola.engine import step
from agricola.legality import effective_payments, legal_actions
from agricola.pending import PendingBuildRooms
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from tests.factories import (
    with_current_player,
    with_house,
    with_resources,
    with_sown_fields,
    with_space,
)

CARD_ID = "straw_thatched_roof"
_GENEROUS = Resources(wood=20, clay=20, reed=20, stone=20)


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _state_owning(*card_ids, resources: Resources = _GENEROUS):
    """A real setup state with player 0 owning `card_ids` (ownership in occupations —
    `_owns` checks occupations OR minor_improvements, so this works for the minor) and
    the given resources; player 1 untouched."""
    state = setup(0)
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids), resources=resources)
    return fast_replace(state, players=(p0, state.players[1]))


def _as_set(frontier) -> set:
    return set(frontier)


# --------------------------------------------------------------------------- #
# Registration                                                                 #
# --------------------------------------------------------------------------- #

def test_registered_as_minor_with_vps_and_free_cost():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.vps == 1
    assert spec.cost == Cost()                 # free
    assert spec.passing_left is False          # kept, not traveling
    assert spec.prereq is not None


def test_reduction_registered_on_renovate_and_build_room_only():
    for kind in ("renovate", "build_room"):
        assert any(cid == CARD_ID for cid, _ in REDUCTIONS.get(kind, ()))
    # NOT on build_major / play_minor — the card names renovation + rooms only.
    for kind in ("build_major", "play_minor"):
        assert not any(cid == CARD_ID for cid, _ in REDUCTIONS.get(kind, ()))


# --------------------------------------------------------------------------- #
# Chokepoint effect — `effective_payments`                                     #
# --------------------------------------------------------------------------- #

def test_renovate_removes_single_reed():
    # 2-room wood house renovate = 2 clay + 1 reed -> the reed drops, leaving 2 clay.
    state = _state_owning(CARD_ID)
    ctx = CostCtx("renovate", Resources(clay=2, reed=1))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=2)}


def test_renovate_removes_full_reed_not_just_one():
    # A cost printing 2 reed loses BOTH (not a fixed -1, which would leave 1 reed).
    state = _state_owning(CARD_ID)
    ctx = CostCtx("renovate", Resources(clay=3, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=3)}


def test_build_room_removes_full_reed():
    # Clay-house room = 5 clay + 2 reed -> the 2 reed drop, leaving 5 clay.
    state = _state_owning(CARD_ID)
    ctx = CostCtx("build_room", Resources(clay=5, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=5)}


def test_reed_free_cost_is_unchanged_no_op():
    # A cost with no reed component is left exactly as printed (floor-at-0 no-op).
    state = _state_owning(CARD_ID)
    ctx = CostCtx("build_room", Resources(wood=5))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=5)}


def test_non_owner_pays_full_reed():
    # Without the card (Family game), the printed reed stays — byte-identical base.
    state = _state_owning()  # no cards
    ctx = CostCtx("renovate", Resources(clay=2, reed=1))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=2, reed=1)}


def test_build_major_untouched_by_card():
    # The card does NOT register on build_major, so a major's reed is unaffected.
    state = _state_owning(CARD_ID)
    ctx = CostCtx("build_major", Resources(clay=3, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=3, reed=2)}


# --------------------------------------------------------------------------- #
# Prerequisite — 3 Grain Fields                                                #
# --------------------------------------------------------------------------- #

def _with_grain_fields(n_grain=0, n_veg=0, n_unsown=0):
    """Player 0 with the given counts of grain / veg / unsown FIELD cells."""
    state = setup(0)
    grain_cells = [(0, c) for c in range(n_grain)]
    veg_cells = [(1, c) for c in range(n_veg)]
    state = with_sown_fields(state, 0, grain_fields=grain_cells, veg_fields=veg_cells)
    if n_unsown:
        from agricola.state import Cell
        from tests.factories import with_grid
        state = with_grid(
            state, 0,
            {(2, c): Cell(cell_type=CellType.FIELD) for c in range(n_unsown)},
        )
    return state


def test_prereq_met_with_three_grain_fields():
    state = _with_grain_fields(n_grain=3)
    assert prereq_met(MINORS[CARD_ID], state, 0) is True


def test_prereq_met_with_more_than_three():
    state = _with_grain_fields(n_grain=4)
    assert prereq_met(MINORS[CARD_ID], state, 0) is True


def test_prereq_unmet_with_two_grain_fields():
    state = _with_grain_fields(n_grain=2)
    assert prereq_met(MINORS[CARD_ID], state, 0) is False


def test_prereq_veg_and_unsown_fields_do_not_count():
    # 2 grain + plenty of veg + unsown fields -> still only 2 grain fields -> unmet.
    state = _with_grain_fields(n_grain=2, n_veg=3, n_unsown=2)
    assert prereq_met(MINORS[CARD_ID], state, 0) is False


def test_prereq_is_per_player():
    # Player 1 has the grain fields; player 0 does not -> player 0's prereq is unmet.
    state = _with_grain_fields(n_grain=0)
    state = with_sown_fields(state, 1, grain_fields=[(0, 0), (0, 1), (0, 2)])
    assert prereq_met(MINORS[CARD_ID], state, 0) is False
    assert prereq_met(MINORS[CARD_ID], state, 1) is True


# --------------------------------------------------------------------------- #
# End-to-end                                                                   #
# --------------------------------------------------------------------------- #

def _hr_state_owning(*card_ids, resources: Resources):
    """House-Redevelopment-ready: player 0 has a 2-room WOOD house, owns `card_ids`,
    holds `resources`, is the active player."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_house(state, 0, HouseMaterial.WOOD)
    state = with_resources(
        state, 0,
        **{f: getattr(resources, f) for f in
           ("wood", "clay", "reed", "stone", "food", "grain", "veg")
           if getattr(resources, f)},
    )
    state = with_space(state, "house_redevelopment", revealed=True)
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids))
    return fast_replace(state, players=(p0, state.players[1]))


def test_renovate_end_to_end_no_reed_needed():
    # 2-room wood house renovate to clay = 2 clay + 1 reed; the card drops the reed,
    # so a reed-LESS player can renovate paying only 2 clay.
    state = _hr_state_owning(CARD_ID, resources=Resources(clay=2))  # NO reed held
    state = step(state, PlaceWorker(space="house_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    payments = [a.payment for a in legal_actions(state) if isinstance(a, CommitRenovate)]
    assert payments == [Resources(clay=2)]   # discounted singleton, no reed
    state = step(state, CommitRenovate(payment=Resources(clay=2), to_material=HouseMaterial.CLAY))
    assert state.players[0].house_material == HouseMaterial.CLAY
    assert state.players[0].resources == Resources()   # spent the 2 clay, no reed needed


def test_build_room_end_to_end_no_reed_needed():
    # Clay-house room = 5 clay + 2 reed; the card drops both reed -> a singleton 5 clay
    # debited inline (no PendingChooseCost two-step), payable with zero reed held.
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_house(state, 0, HouseMaterial.CLAY)
    state = with_resources(state, 0, clay=5)   # NO reed
    state = with_space(state, "farm_expansion", revealed=True)
    p0 = fast_replace(state.players[0], occupations=frozenset({CARD_ID}))
    state = fast_replace(state, players=(p0, state.players[1]))

    state = step(state, PlaceWorker(space="farm_expansion"))
    state = step(state, ChooseSubAction(name="build_rooms"))
    rooms = [a for a in legal_actions(state) if isinstance(a, CommitBuildRoom)]
    assert rooms, "expected a legal room cell with the reed dropped"
    state = step(state, rooms[0])
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)   # singleton -> inline
    assert state.players[0].resources == Resources()   # spent 5 clay, no reed
