"""Tests for Clay Supports (minor improvement, D15).

Card text: "Each time you build a clay room, you can pay 2 clay, 1 wood, and 1 reed
instead of 5 clay and 2 reed."

A passive cost-FORMULA minor gated on a CLAY house (a "clay room" = a room built while
living in a clay house; printed `ROOM_COSTS[CLAY] = 5 clay + 2 reed`). The formula offers
the alternative 2 clay + 1 wood + 1 reed; `effective_payments` surfaces it beside the
printed base, Pareto-min keeps the cheaper, and the real Farm Expansion build-rooms flow
debits the chosen payment. The clause does NOT apply in a wood or stone house.

The first line imports the card module so its `register_*` calls fire (it is not in
`cards/__init__.py`).
"""
import agricola.cards.clay_supports  # noqa: F401  -- registers the card

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    CommitChooseCost,
    PlaceWorker,
)
from agricola.cards.clay_supports import CARD_ID
from agricola.cards.specs import MINORS
from agricola.constants import HouseMaterial
from agricola.cost import CostCtx
from agricola.engine import step
from agricola.legality import effective_payments, legal_actions
from agricola.pending import PendingBuildRooms, PendingChooseCost
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import with_house, with_resources, with_space

# The printed clay-room cost and the card's alternative.
_PRINTED = Resources(clay=5, reed=2)
_FORMULA = Resources(clay=2, wood=1, reed=1)


def _as_set(frontier) -> set:
    return set(frontier)


def _state_owning(*card_ids, resources: Resources = Resources(wood=20, clay=20, reed=20, stone=20),
                  material: HouseMaterial = HouseMaterial.CLAY):
    """A real setup state with player 0 owning `card_ids` (as played MINORS) and the given
    resources / house material; player 1 untouched."""
    state = setup(0)
    state = with_house(state, 0, material)
    p0 = fast_replace(state.players[0],
                      minor_improvements=frozenset(card_ids),
                      resources=resources)
    return fast_replace(state, players=(p0, state.players[1]))


def _fe_state_owning(*card_ids, material: HouseMaterial, resources: Resources):
    """`_state_owning` with Farm Expansion revealed and player 0 to move."""
    state = _state_owning(*card_ids, resources=resources, material=material)
    state = with_space(state, "farm_expansion", revealed=True)
    return fast_replace(state, current_player=0)


def _drive_to_build_rooms(state):
    """Place at Farm Expansion and choose build_rooms; return (state, first room cell)."""
    state = step(state, PlaceWorker(space="farm_expansion"))
    state = step(state, ChooseSubAction(name="build_rooms"))
    rooms = [a for a in legal_actions(state) if isinstance(a, CommitBuildRoom)]
    assert rooms, "expected a legal room cell"
    return state, rooms[0]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_clay_supports_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    # cost 2 wood, no prereq, no vps, no passing, no on-play effect.
    assert spec.cost.resources == Resources(wood=2)
    assert spec.vps == 0
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# The chokepoint surfaces the alternative formula and Pareto-min keeps it.
# ---------------------------------------------------------------------------

def test_formula_offered_beside_printed_base_in_clay_house():
    # Clay house: the card's 2 clay + 1 wood + 1 reed is offered BESIDE the printed
    # 5 clay + 2 reed. The two are Pareto-INCOMPARABLE over goods spent — the formula uses
    # less clay + reed but 1 more wood — so BOTH survive the frontier. This is exactly the
    # card's "you can pay ... INSTEAD": a genuine choice (cheaper unless you're wood-poor),
    # not a strict dominance.
    state = _state_owning(CARD_ID, material=HouseMaterial.CLAY)
    ctx = CostCtx("build_room", _PRINTED)
    assert _as_set(effective_payments(state, 0, ctx)) == {_PRINTED, _FORMULA}


def test_formula_only_in_clay_house():
    # In a WOOD house, a room is not a "clay room" -> the clause does NOT apply, so only
    # the printed base survives.
    state = _state_owning(CARD_ID, material=HouseMaterial.WOOD)
    ctx = CostCtx("build_room", Resources(wood=5, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=5, reed=2)}

    # And in a STONE house likewise (printed stone-room cost untouched).
    sstate = _state_owning(CARD_ID, material=HouseMaterial.STONE)
    sctx = CostCtx("build_room", Resources(stone=5, reed=2))
    assert _as_set(effective_payments(sstate, 0, sctx)) == {Resources(stone=5, reed=2)}


def test_inert_without_card():
    # No card -> the printed clay-room base is the only payment (control).
    state = _state_owning(material=HouseMaterial.CLAY)  # no minors owned
    ctx = CostCtx("build_room", _PRINTED)
    assert _as_set(effective_payments(state, 0, ctx)) == {_PRINTED}


# ---------------------------------------------------------------------------
# End-to-end through the real Farm Expansion build-rooms flow.
# ---------------------------------------------------------------------------

def test_clay_supports_room_formula_end_to_end():
    # Clay house, EXACTLY the formula resources (2 clay + 1 wood + 1 reed). The printed
    # 5 clay + 2 reed is unaffordable, so only the formula payment exists -> a singleton
    # frontier debited inline (no PendingChooseCost).
    state = _fe_state_owning(
        CARD_ID, material=HouseMaterial.CLAY, resources=Resources(clay=2, wood=1, reed=1))
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)   # no two-step frame
    # Paid 2 clay + 1 wood + 1 reed; nothing left over.
    assert state.players[0].resources == Resources()


def test_clay_supports_two_step_when_both_payments_affordable():
    # Holding enough for BOTH the printed base and the formula, both are affordable AND
    # Pareto-incomparable, so the build pauses on a PendingChooseCost offering the two
    # payments. Picking the formula debits 2 clay + 1 wood + 1 reed.
    state = _fe_state_owning(
        CARD_ID, material=HouseMaterial.CLAY,
        resources=Resources(clay=5, wood=1, reed=2))
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingChooseCost)
    options = {a.payment for a in legal_actions(state)
               if isinstance(a, CommitChooseCost)}
    assert options == {_PRINTED, _FORMULA}
    # Take the formula route; the frame pops back to the build host, resources debited.
    state = step(state, CommitChooseCost(payment=_FORMULA))
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    # Paid 2 clay + 1 wood + 1 reed out of (5 clay, 1 wood, 2 reed) -> 3 clay + 1 reed left.
    assert state.players[0].resources == Resources(clay=3, reed=1)


def test_clay_supports_does_not_help_in_wood_house_end_to_end():
    # Wood house: the formula does not apply, so a room costs the printed 5 wood + 2 reed.
    # With only formula-sized resources the build is impossible; with the printed amount
    # it goes through at the printed cost (the card is inert).
    state = _fe_state_owning(
        CARD_ID, material=HouseMaterial.WOOD, resources=Resources(wood=5, reed=2))
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    assert state.players[0].resources == Resources()   # paid the full printed 5 wood + 2 reed
