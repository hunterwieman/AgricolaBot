"""Tests for Wooden Hut Extender (occupation, C #128).

Card text: "Wood rooms now cost you 1 reed, and additionally 5 wood through round 5,
4 wood in rounds 6 and 7, and 3 wood in round 8 and later."

A passive build_room cost-FORMULA, gated on a WOOD house, with a round-banded wood amount
and reed dropped to 1. Checked at the `effective_payments` chokepoint (round bands + the
wood-house gate + the no-op in a clay house) and end-to-end through Farm Expansion. Mirrors
tests/test_cards_cost_cards.py.
"""
from __future__ import annotations

import agricola.cards.wooden_hut_extender  # noqa: F401  (registers its room formula)
from agricola.actions import ChooseSubAction, CommitBuildRoom, PlaceWorker
from agricola.cards.cost_mods import FORMULA_MODS
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import HouseMaterial
from agricola.cost import CostCtx
from agricola.engine import step
from agricola.legality import effective_payments, legal_actions
from agricola.pending import PendingBuildRooms
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import (
    with_current_player,
    with_house,
    with_resources,
    with_space,
)

CARD_ID = "wooden_hut_extender"
_GENEROUS = Resources(wood=20, clay=20, reed=20, stone=20)
_PRINTED_WOOD_ROOM = Resources(wood=5, reed=2)


def _as_set(frontier) -> set:
    return set(frontier)


def _state_owning(*card_ids, resources: Resources = _GENEROUS, round_number: int = 1):
    state = setup(0)
    if round_number != state.round_number:
        state = fast_replace(state, round_number=round_number)
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids), resources=resources)
    return fast_replace(state, players=(p0, state.players[1]))


# ---------------------------------------------------------------------------
# Registration.
# ---------------------------------------------------------------------------

def test_registers_occupation_and_room_formula():
    assert CARD_ID in OCCUPATIONS
    assert any(cid == CARD_ID for cid, _, _ in FORMULA_MODS.get("build_room", ()))


# ---------------------------------------------------------------------------
# Round bands at the chokepoint (wood house). reed -> 1 always; wood by round.
# ---------------------------------------------------------------------------

def test_round_1_through_5_costs_5_wood_1_reed():
    for rnd in (1, 3, 5):
        state = _state_owning(CARD_ID, round_number=rnd)
        ctx = CostCtx("build_room", _PRINTED_WOOD_ROOM)
        assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=5, reed=1)}, rnd


def test_rounds_6_and_7_cost_4_wood_1_reed():
    for rnd in (6, 7):
        state = _state_owning(CARD_ID, round_number=rnd)
        ctx = CostCtx("build_room", _PRINTED_WOOD_ROOM)
        assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=4, reed=1)}, rnd


def test_round_8_and_later_cost_3_wood_1_reed():
    for rnd in (8, 11, 14):
        state = _state_owning(CARD_ID, round_number=rnd)
        ctx = CostCtx("build_room", _PRINTED_WOOD_ROOM)
        assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=3, reed=1)}, rnd


def test_formula_strictly_dominates_printed_base_through_round_5():
    # The printed 5 wood + 2 reed never survives Pareto-min when the formula applies —
    # the formula spends the same wood (r<=5) or less, and strictly less reed.
    state = _state_owning(CARD_ID, round_number=4)
    ctx = CostCtx("build_room", _PRINTED_WOOD_ROOM)
    payments = _as_set(effective_payments(state, 0, ctx))
    assert _PRINTED_WOOD_ROOM not in payments
    assert payments == {Resources(wood=5, reed=1)}


# ---------------------------------------------------------------------------
# Gating: "wood rooms" only — inert in a clay house; inert without the card.
# ---------------------------------------------------------------------------

def test_does_not_apply_in_clay_house():
    state = _state_owning(CARD_ID, round_number=1)
    p0 = fast_replace(state.players[0], house_material=HouseMaterial.CLAY)
    state = fast_replace(state, players=(p0, state.players[1]))
    ctx = CostCtx("build_room", Resources(clay=5, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=5, reed=2)}


def test_without_card_printed_base_unchanged():
    # An unowned card must not modify the cost — the Family-game path stays byte-identical.
    state = _state_owning(round_number=8)   # no card owned
    ctx = CostCtx("build_room", _PRINTED_WOOD_ROOM)
    assert _as_set(effective_payments(state, 0, ctx)) == {_PRINTED_WOOD_ROOM}


def test_opponent_ownership_does_not_help_player_0():
    # Card owned by P1; P0 builds -> P0 sees only the printed base (ownership is per-player).
    state = setup(0)
    p0 = fast_replace(state.players[0], resources=_GENEROUS)
    p1 = fast_replace(state.players[1], occupations=frozenset({CARD_ID}))
    state = fast_replace(state, players=(p0, p1))
    ctx = CostCtx("build_room", _PRINTED_WOOD_ROOM)
    assert _as_set(effective_payments(state, 0, ctx)) == {_PRINTED_WOOD_ROOM}


# ---------------------------------------------------------------------------
# End-to-end through Farm Expansion's build-rooms.
# ---------------------------------------------------------------------------

def _fe_state_owning(*, material: HouseMaterial, resources: Resources, round_number: int):
    state = setup(seed=0)
    if round_number != state.round_number:
        state = fast_replace(state, round_number=round_number)
    state = with_current_player(state, 0)
    state = with_house(state, 0, material)
    state = with_resources(
        state, 0,
        **{f: getattr(resources, f) for f in
           ("wood", "clay", "reed", "stone", "food", "grain", "veg")
           if getattr(resources, f)},
    )
    state = with_space(state, "farm_expansion", revealed=True)
    p0 = fast_replace(state.players[0], occupations=frozenset({CARD_ID}))
    return fast_replace(state, players=(p0, state.players[1]))


def _drive_to_build_rooms(state):
    state = step(state, PlaceWorker(space="farm_expansion"))
    state = step(state, ChooseSubAction(name="build_rooms"))
    rooms = [a for a in legal_actions(state) if isinstance(a, CommitBuildRoom)]
    assert rooms, "expected a legal room cell"
    return state, rooms[0]


def test_room_formula_end_to_end_round_1():
    # Round 1, wood house: printed 5 wood + 2 reed -> 5 wood + 1 reed (singleton, no
    # PendingChooseCost two-step). Give exactly the cost and assert the debit.
    state = _fe_state_owning(material=HouseMaterial.WOOD,
                             resources=Resources(wood=5, reed=1), round_number=1)
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)   # singleton, no two-step
    assert state.players[0].resources == Resources()               # paid 5 wood + 1 reed


def test_room_formula_end_to_end_round_8():
    # Round 8+, wood house: -> 3 wood + 1 reed.
    state = _fe_state_owning(material=HouseMaterial.WOOD,
                             resources=Resources(wood=3, reed=1), round_number=8)
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    assert state.players[0].resources == Resources()               # paid 3 wood + 1 reed
