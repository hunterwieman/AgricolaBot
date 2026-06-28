"""Cost-modifier chokepoint tests (COST_MODIFIER_DESIGN.md §8 prototype, step 1).

Validates `effective_payments` / `can_pay` (the cost-resolution chokepoint) directly,
with a hand-built `CostCtx` — no engine wiring yet (renovate routes through it in a
later step). Importing the two prototype card modules below populates the cost-mod
registries; the test states own the cards by putting their ids in `occupations`
(which is all `_owns` checks). The worked traces mirror COST_MODIFIER_DESIGN.md §4.
"""
from __future__ import annotations

import agricola.cards.bricklayer      # noqa: F401  (registers its reductions)
import agricola.cards.carpenter       # noqa: F401  (registers its room formula)
import agricola.cards.clay_plasterer  # noqa: F401  (registers its renovate/room formulas)
import agricola.cards.frame_builder   # noqa: F401  (registers its conversion)
import agricola.cards.millwright      # noqa: F401  (registers the conversion sink)
from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    CommitBuildStable,
    CommitChooseCost,
    CommitPlayMinor,
    CommitRenovate,
    PlaceWorker,
    Stop,
)
from agricola.constants import GameMode, HouseMaterial
from agricola.cost import CostCtx
from agricola.engine import step
from agricola.legality import can_pay, effective_payments, legal_actions, playable_minors
from agricola.pending import (
    PendingBuildRooms,
    PendingBuildStables,
    PendingChooseCost,
    PendingPlayMinor,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import (
    with_current_player,
    with_house,
    with_pending_stack,
    with_resources,
    with_space,
)

_GENEROUS = Resources(wood=20, clay=20, reed=20, stone=20)


def _state_owning(*card_ids, resources: Resources = _GENEROUS):
    """A real setup state with player 0 owning `card_ids` (as played occupations) and
    the given resources; player 1 untouched."""
    state = setup(0)
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids), resources=resources)
    return fast_replace(state, players=(p0, state.players[1]))


def _renovate_ctx(base: Resources, **kw) -> CostCtx:
    return CostCtx("renovate", base, **kw)


def _as_set(frontier) -> set:
    return set(frontier)


# --- §4.1: Family / no cost cards -> singleton [base] ---

def test_no_cards_returns_singleton_base():
    state = _state_owning()  # no cards
    ctx = _renovate_ctx(Resources(clay=3, reed=1))
    assert effective_payments(state, 0, ctx) == [Resources(clay=3, reed=1)]
    assert can_pay(state, 0, ctx) is True


def test_no_cards_unaffordable_empty_frontier_but_canpay_false():
    state = _state_owning(resources=Resources())  # broke
    ctx = _renovate_ctx(Resources(clay=3, reed=1))
    assert effective_payments(state, 0, ctx) == []
    assert can_pay(state, 0, ctx) is False


# --- a pure reduction (Bricklayer) ---

def test_reduction_only():
    state = _state_owning("bricklayer")
    ctx = _renovate_ctx(Resources(clay=3, reed=1))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(clay=2, reed=1)}


# --- a pure conversion (Frame Builder) ---

def test_conversion_only_two_incomparable_options():
    state = _state_owning("frame_builder")
    ctx = _renovate_ctx(Resources(clay=2, reed=1))
    assert _as_set(effective_payments(state, 0, ctx)) == {
        Resources(clay=2, reed=1),          # decline the conversion
        Resources(wood=1, reed=1),          # replace 2 clay -> 1 wood
    }


# --- §4.3: Frame Builder + Bricklayer, 2-room wood->clay renovate ---

def test_trace_4_3_conversion_then_reduction():
    state = _state_owning("frame_builder", "bricklayer")
    ctx = _renovate_ctx(Resources(clay=2, reed=1))
    # convert-first then reduce: {2clay+1reed, 0clay+1wood+1reed} -1clay-> {1clay+1reed, 1wood+1reed}
    assert _as_set(effective_payments(state, 0, ctx)) == {
        Resources(clay=1, reed=1),
        Resources(wood=1, reed=1),
    }


def test_reductions_floor_at_zero():
    # The 1-wood candidate has 0 clay; Bricklayer's -1 clay must floor, not go negative.
    state = _state_owning("frame_builder", "bricklayer")
    ctx = _renovate_ctx(Resources(clay=2, reed=1))
    fields = ("wood", "clay", "reed", "stone", "food", "grain", "veg")
    for pay in effective_payments(state, 0, ctx):
        assert all(getattr(pay, f) >= 0 for f in fields)


# --- can_pay short-circuit + conversion route ---

def test_can_pay_via_conversion_when_base_unaffordable():
    # base = 2 clay; player holds no clay but 1 wood -> Frame Builder's wood route pays.
    state = _state_owning("frame_builder", resources=Resources(wood=1))
    ctx = _renovate_ctx(Resources(clay=2))
    assert can_pay(state, 0, ctx) is True
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=1)}


# --- guard: "once per action" — a conversion is applied at most once ---

def test_frame_builder_not_double_applied():
    # 4-clay renovate: Frame Builder may replace ONE pair of clay (-> 2clay+1wood), never
    # two pairs (-> 2wood). The double-application payment must NOT appear.
    state = _state_owning("frame_builder")
    ctx = _renovate_ctx(Resources(clay=4, reed=2))
    frontier = _as_set(effective_payments(state, 0, ctx))
    assert Resources(clay=4, reed=2) in frontier
    assert Resources(clay=2, reed=2, wood=1) in frontier
    assert Resources(reed=2, wood=2) not in frontier   # the illegal double-application


# ===========================================================================
# End-to-end: the cards drive the REAL renovate flow through House Redevelopment
# (not just the chokepoint helper). Proves the enumerator goes wide over
# `effective_payments` and `_execute_renovate` debits `CommitRenovate.payment`.
# ===========================================================================

def _hr_state_owning(*card_ids, resources: Resources):
    """A House-Redevelopment-ready state: player 0 has a 2-room WOOD house, owns
    `card_ids` (played occupations), holds `resources`, and is the active player."""
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


def _drive_to_renovate(state):
    """Place at House Redevelopment and choose renovate; return (state, payments)."""
    state = step(state, PlaceWorker(space="house_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    payments = [a.payment for a in legal_actions(state)
                if isinstance(a, CommitRenovate)]
    return state, payments


def test_bricklayer_discounts_renovate_end_to_end():
    # 2-room wood house: base = 2 clay + 1 reed; Bricklayer (-1 clay) -> 1 clay + 1 reed.
    state = _hr_state_owning("bricklayer", resources=Resources(clay=2, reed=1))
    state, payments = _drive_to_renovate(state)
    assert payments == [Resources(clay=1, reed=1)]   # the discounted singleton
    state = step(state, CommitRenovate(payment=payments[0], to_material=HouseMaterial.CLAY))
    assert state.players[0].house_material == HouseMaterial.CLAY
    assert state.players[0].resources == Resources(clay=1)   # paid 1 clay + 1 reed of 2c1r


def test_frame_builder_offers_conversion_route_end_to_end():
    # 2-room wood house: base = 2 clay + 1 reed. Frame Builder also offers replacing the
    # 2 clay with 1 wood. Hold clay=2, reed=1, wood=1 so BOTH options are affordable.
    state = _hr_state_owning("frame_builder", resources=Resources(clay=2, reed=1, wood=1))
    state, payments = _drive_to_renovate(state)
    assert set(payments) == {
        Resources(clay=2, reed=1),           # decline the conversion
        Resources(wood=1, reed=1),           # 2 clay -> 1 wood
    }
    # Take the conversion route and confirm the debit lands on wood, not clay.
    state = step(state, CommitRenovate(
        payment=Resources(wood=1, reed=1), to_material=HouseMaterial.CLAY))
    assert state.players[0].house_material == HouseMaterial.CLAY
    assert state.players[0].resources == Resources(clay=2)   # wood + reed spent, clay kept


def test_family_renovate_singleton_unaffected_end_to_end():
    # No cost cards -> exactly the printed cost, one option (Family byte-identity).
    state = _hr_state_owning(resources=Resources(clay=2, reed=1))
    state, payments = _drive_to_renovate(state)
    assert payments == [Resources(clay=2, reed=1)]


# ===========================================================================
# End-to-end: cost cards on BUILD ROOM through Farm Expansion. A reduction keeps a
# singleton frontier (debited inline at the build); a conversion makes >1 payment,
# so the build pauses on the PendingChooseCost two-step (COST_MODIFIER_DESIGN.md §3.7).
# A clay house (room cost = 5 clay + 2 reed) lets the clay-targeting cards bite.
# ===========================================================================

def _fe_state_owning(*card_ids, material: HouseMaterial, resources: Resources):
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
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids))
    return fast_replace(state, players=(p0, state.players[1]))


def _drive_to_build_rooms(state):
    """Place at Farm Expansion and choose build_rooms; return (state, first room cell)."""
    state = step(state, PlaceWorker(space="farm_expansion"))
    state = step(state, ChooseSubAction(name="build_rooms"))
    rooms = [a for a in legal_actions(state) if isinstance(a, CommitBuildRoom)]
    assert rooms, "expected a legal room cell"
    return state, rooms[0]


def test_bricklayer_room_reduction_singleton_inline_debit():
    # Clay house room = 5 clay + 2 reed; Bricklayer (-2 clay) -> 3 clay + 2 reed,
    # a singleton -> debited inline, NO PendingChooseCost.
    state = _fe_state_owning(
        "bricklayer", material=HouseMaterial.CLAY, resources=Resources(clay=5, reed=2))
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)   # no two-step frame
    assert state.players[0].resources == Resources(clay=2)          # paid 3 clay + 2 reed


def test_frame_builder_room_conversion_two_step():
    # Clay house room = 5 clay + 2 reed. Frame Builder offers replacing 2 clay with
    # 1 wood -> two affordable payments -> the build pauses on PendingChooseCost.
    state = _fe_state_owning(
        "frame_builder", material=HouseMaterial.CLAY,
        resources=Resources(clay=5, reed=2, wood=1))
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingChooseCost)
    options = {a.payment for a in legal_actions(state)
               if isinstance(a, CommitChooseCost)}
    assert options == {
        Resources(clay=5, reed=2),                  # decline the conversion
        Resources(clay=3, reed=2, wood=1),          # 2 clay -> 1 wood
    }
    # Take the conversion route; the frame pops back to the build host, wood debited.
    state = step(state, CommitChooseCost(payment=Resources(clay=3, reed=2, wood=1)))
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    assert state.players[0].resources == Resources(clay=2)   # 5-3 clay, 2-2 reed, 1-1 wood


def test_pending_breadcrumb_renders_with_costless_frames():
    """Regression (seed-47088 'Cottager: build a room → nothing happens'): the
    cost-modifier refactor removed `cost` from PendingBuildRooms and PendingRenovate
    (cost is resolved via `effective_payments` now). The shared pending-stack
    breadcrumb renderer (`play._pending_detail`, used by the web UI's `state_to_json`)
    must not assume `.cost` — otherwise building the snapshot raises AttributeError
    while such a frame is on the stack, 500-ing `/api/action` so the client never
    updates ('nothing happens')."""
    from play import render_pending

    # Build Rooms host (no `cost` field) on the stack — and the PendingChooseCost
    # two-step it pushes when a card offers >1 payment.
    state = _fe_state_owning(
        "frame_builder", material=HouseMaterial.CLAY,
        resources=Resources(clay=5, reed=2, wood=1))
    state, room = _drive_to_build_rooms(state)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    assert isinstance(render_pending(state), str)          # no AttributeError
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingChooseCost)
    assert isinstance(render_pending(state), str)

    # Renovate host (also no `cost` field).
    rstate = _hr_state_owning("frame_builder", resources=Resources(clay=2, reed=1, wood=1))
    rstate, _ = _drive_to_renovate(rstate)
    from agricola.pending import PendingRenovate
    assert isinstance(rstate.pending_stack[-1], PendingRenovate)
    assert isinstance(render_pending(rstate), str)


# ===========================================================================
# End-to-end: a cost reduction on PLAY MINOR (Bricklayer's play_minor -1 clay).
# Junk Room costs 1 wood + 1 clay; Bricklayer reduces the clay to 0, so it routes
# through the chokepoint both in the legality gate (playable_minors) and the debit.
# Minors carry only reductions today -> singleton frontier, no two-step.
# ===========================================================================

def _minor_state(*card_ids, resources: Resources):
    """A CARDS state with player 0 owning `card_ids`, Junk Room in hand, `resources`."""
    state = setup(0)
    state = fast_replace(state, mode=GameMode.CARDS)
    p0 = fast_replace(
        state.players[0],
        hand_minors=frozenset({"junk_room"}),
        occupations=frozenset(card_ids),
        resources=resources,
    )
    return fast_replace(state, players=(p0, state.players[1]), current_player=0)


def test_bricklayer_makes_clay_minor_playable_via_chokepoint():
    # 1 wood, 0 clay: Junk Room (1 wood + 1 clay) is unaffordable as printed, but
    # Bricklayer's -1 clay makes it playable — proving playable_minors uses can_pay.
    owned = _minor_state("bricklayer", resources=Resources(wood=1))
    assert "junk_room" in playable_minors(owned, 0)
    bare = _minor_state(resources=Resources(wood=1))   # same hand, no Bricklayer
    assert "junk_room" not in playable_minors(bare, 0)


def test_bricklayer_reduces_minor_clay_debit_end_to_end():
    state = _minor_state("bricklayer", resources=Resources(wood=1))
    state = with_pending_stack(
        state, [PendingPlayMinor(player_idx=0, initiated_by_id="lessons")])
    # Bricklayer reduces Junk Room's clay to 0, so the wide commit's payment is just 1 wood.
    play = CommitPlayMinor(card_id="junk_room", payment=Resources(wood=1))
    assert play in legal_actions(state)
    state = step(state, play)
    # Paid 1 wood + 0 clay (clay reduced away); the card is now in the tableau.
    assert state.players[0].resources.wood == 0
    assert state.players[0].resources.clay == 0
    assert "junk_room" in state.players[0].minor_improvements


# ===========================================================================
# FORMULA cards (the third modifier kind): Carpenter (room) + Clay Plasterer
# (renovate-to-clay + clay room). A formula offers a whole alternative cost; the
# chokepoint surfaces it beside the printed base, lets reductions stack, and
# Pareto-min keeps the cheaper. Clay Plasterer + Bricklayer is the §4.2 example.
# ===========================================================================

def test_carpenter_room_formula_dominates_printed_base():
    # Wood house (setup default): Carpenter's formula (3 wood + 2 reed) dominates the
    # printed 5 wood + 2 reed -> a singleton frontier of just the formula cost.
    state = _state_owning("carpenter")
    ctx = CostCtx("build_room", Resources(wood=5, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=3, reed=2)}


def test_carpenter_room_formula_end_to_end():
    # Clay house: printed room = 5 clay + 2 reed; Carpenter -> 3 clay + 2 reed.
    state = _fe_state_owning(
        "carpenter", material=HouseMaterial.CLAY, resources=Resources(clay=5, reed=2))
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    assert state.players[0].resources == Resources(clay=2)      # paid 3 clay + 2 reed


def test_carpenter_formula_then_bricklayer_reduction_stack():
    # Formula (3 clay + 2 reed) THEN reduction (Bricklayer room -2 clay) -> 1 clay + 2 reed.
    state = _fe_state_owning(
        "carpenter", "bricklayer", material=HouseMaterial.CLAY,
        resources=Resources(clay=5, reed=2))
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)   # still a singleton
    assert state.players[0].resources == Resources(clay=4)         # paid 1 clay + 2 reed


def test_clay_plasterer_room_formula_only_in_clay_house():
    # Conditional formula: in a WOOD house, the clay-room clause does NOT apply.
    state = _state_owning("clay_plasterer")   # wood house default
    ctx = CostCtx("build_room", Resources(wood=5, reed=2))
    assert _as_set(effective_payments(state, 0, ctx)) == {Resources(wood=5, reed=2)}


def test_clay_plasterer_plus_bricklayer_renovate_is_section_4_2():
    # The §4.2 worked example as real cards: wood->clay renovate (2 rooms) with Clay
    # Plasterer (formula 1 clay + 1 reed) + Bricklayer (-1 clay) collapses to [1 reed].
    state = _hr_state_owning(
        "clay_plasterer", "bricklayer", resources=Resources(clay=2, reed=1))
    state, payments = _drive_to_renovate(state)
    assert payments == [Resources(reed=1)]
    state = step(state, CommitRenovate(payment=Resources(reed=1), to_material=HouseMaterial.CLAY))
    assert state.players[0].house_material == HouseMaterial.CLAY
    assert state.players[0].resources == Resources(clay=2)        # paid only 1 reed


# ===========================================================================
# Millwright — the conversion SINK + chaining (COST_MODIFIER_DESIGN.md §4.4 / §4.7).
# ===========================================================================

def test_millwright_on_play_grants_grain():
    from agricola.cards.specs import OCCUPATIONS
    state = setup(0)
    before = state.players[0].resources.grain
    after = OCCUPATIONS["millwright"].on_play(state, 0)
    assert after.players[0].resources.grain == before + 1


def test_millwright_sink_replaces_up_to_two_building_resources():
    # Clay room (5 clay + 2 reed). Millwright may turn up to 2 building-resource units
    # into grain (1 each): the unchanged cost + the 1- and 2-unit replacements survive.
    # The player must HOLD grain to pay it (that's the trade Millwright offers).
    state = _state_owning("millwright", resources=Resources(clay=20, reed=20, grain=20))
    ctx = CostCtx("build_room", Resources(clay=5, reed=2))
    frontier = _as_set(effective_payments(state, 0, ctx))
    assert Resources(clay=5, reed=2) in frontier               # decline (replace 0)
    assert Resources(clay=4, reed=2, grain=1) in frontier      # 1 clay -> 1 grain
    assert Resources(clay=3, reed=2, grain=2) in frontier      # 2 clay -> 2 grain
    assert Resources(clay=5, reed=1, grain=1) in frontier      # 1 reed -> 1 grain (reed is a building resource)
    # "up to 2": never three replacements.
    assert Resources(clay=2, reed=2, grain=3) not in frontier


def test_frame_builder_millwright_chain_on_clay_room():
    # The owner's worked example: Frame Builder (2 clay -> 1 wood) FEEDS Millwright
    # (that wood -> 1 grain), so a clay room (5 clay + 2 reed) is payable as
    # 3 clay + 2 reed + 1 grain — strictly cheaper than Millwright alone could reach
    # (which would be 3 clay + 2 reed + 2 grain), so the chained option Pareto-survives.
    state = _state_owning(
        "frame_builder", "millwright",
        resources=Resources(wood=20, clay=20, reed=20, stone=20, grain=20))
    ctx = CostCtx("build_room", Resources(clay=5, reed=2))
    frontier = _as_set(effective_payments(state, 0, ctx))
    assert Resources(clay=3, reed=2, grain=1) in frontier
    # Apply-each-once, sink-last: Frame Builder fires at most once, so no payment ever
    # holds 2 wood (it would require two clay->wood conversions in one build). §4.7.
    assert all(pay.wood <= 1 for pay in frontier)


def test_frame_builder_millwright_chain_room_end_to_end():
    # The same chain, driven through the REAL Farm Expansion build-rooms flow (not just
    # the chokepoint): a clay room (5 clay + 2 reed) is payable as 3 clay + 2 reed + 1
    # grain — Frame Builder turns 2 clay into 1 wood, Millwright turns that wood into 1
    # grain — surfaced via the two-step PendingChooseCost and committed.
    state = _fe_state_owning(
        "frame_builder", "millwright", material=HouseMaterial.CLAY,
        resources=Resources(clay=10, reed=5, grain=5, wood=5))
    state, room = _drive_to_build_rooms(state)
    state = step(state, room)
    assert isinstance(state.pending_stack[-1], PendingChooseCost)
    options = {a.payment for a in legal_actions(state)
               if isinstance(a, CommitChooseCost)}
    assert Resources(clay=3, reed=2, grain=1) in options
    state = step(state, CommitChooseCost(payment=Resources(clay=3, reed=2, grain=1)))
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)   # back at the build host
    # Paid 3 clay + 2 reed + 1 grain (wood untouched — it was only a conversion intermediate).
    assert state.players[0].resources == Resources(clay=7, reed=3, grain=4, wood=5)


def test_millwright_grain_budget_is_per_action_not_per_room():
    # Millwright's "up to 2 grain" is shared across ALL rooms built in one Farm Expansion
    # action (in Agricola the rooms build at once; the engine just resolves them one at a
    # time). Spend the full 2 on room 1; room 2 must then offer NO grain conversion.
    state = _fe_state_owning(
        "millwright", material=HouseMaterial.CLAY,
        resources=Resources(clay=20, reed=20, grain=20))
    state = step(state, PlaceWorker(space="farm_expansion"))
    state = step(state, ChooseSubAction(name="build_rooms"))
    grain0 = state.players[0].resources.grain

    # Room 1: take the maximum-grain payment (the full 2-unit budget).
    rooms = [a for a in legal_actions(state) if isinstance(a, CommitBuildRoom)]
    state = step(state, rooms[0])
    opts = [a.payment for a in legal_actions(state) if isinstance(a, CommitChooseCost)]
    best = max(opts, key=lambda r: r.grain)
    assert best.grain == 2
    state = step(state, CommitChooseCost(payment=best))

    # Room 2: budget exhausted -> no grain option survives -> a singleton (no two-step),
    # so the build commits inline and the action's total grain stays capped at 2.
    rooms = [a for a in legal_actions(state) if isinstance(a, CommitBuildRoom)]
    assert rooms, "expected a second legal room cell"
    state = step(state, rooms[0])
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)   # NOT a PendingChooseCost
    assert grain0 - state.players[0].resources.grain == 2


def test_millwright_grain_budget_resets_between_actions():
    # The budget resets at the build-action boundary: a fresh Farm Expansion gives a new 2.
    # (Two separate build-rooms decisions in the same constructed state, via num_built reset.)
    base = _fe_state_owning(
        "millwright", material=HouseMaterial.CLAY,
        resources=Resources(clay=20, reed=20, grain=20))
    # First action: build one room spending 2 grain, then Proceed (fires after_build_rooms reset).
    s = step(base, PlaceWorker(space="farm_expansion"))
    s = step(s, ChooseSubAction(name="build_rooms"))
    rooms = [a for a in legal_actions(s) if isinstance(a, CommitBuildRoom)]
    s = step(s, rooms[0])
    best = max((a.payment for a in legal_actions(s) if isinstance(a, CommitChooseCost)),
               key=lambda r: r.grain)
    s = step(s, CommitChooseCost(payment=best))
    from agricola.actions import Proceed, Stop
    s = step(s, Proceed())   # flips PendingBuildRooms to after -> _reset fires
    s = step(s, Stop())      # pop the build host
    # The CardStore counter is reset (canonical 0), so a later build action gets a fresh budget.
    assert s.players[0].card_state.get("millwright", 0) == 0


# ===========================================================================
# End-to-end: cost cards on BUILD STABLE through Farm Expansion (the action wired
# last). PendingBuildStables KEEPS its caller-supplied cost; the chokepoint resolves
# it with that base. Millwright (wood -> grain) is the live stable cost card.
# ===========================================================================

def _drive_to_build_stables(state):
    """Place at Farm Expansion and choose build_stables; return (state, first stable cell)."""
    state = step(state, PlaceWorker(space="farm_expansion"))
    state = step(state, ChooseSubAction(name="build_stables"))
    stables = [a for a in legal_actions(state) if isinstance(a, CommitBuildStable)]
    assert stables, "expected a legal stable cell"
    return state, stables[0]


def test_millwright_on_stable_two_step():
    # Farm Expansion stable = 2 wood. Millwright offers turning wood into grain, so the
    # stable surfaces a two-step choice {2 wood, 1 wood+1 grain, 2 grain}.
    state = _fe_state_owning(
        "millwright", material=HouseMaterial.WOOD, resources=Resources(wood=10, grain=10))
    state, stable = _drive_to_build_stables(state)
    state = step(state, stable)
    assert isinstance(state.pending_stack[-1], PendingChooseCost)
    options = {a.payment for a in legal_actions(state) if isinstance(a, CommitChooseCost)}
    assert options == {
        Resources(wood=2),               # decline
        Resources(wood=1, grain=1),      # one wood -> grain
        Resources(grain=2),              # both wood -> grain
    }
    state = step(state, CommitChooseCost(payment=Resources(grain=2)))
    assert isinstance(state.pending_stack[-1], PendingBuildStables)
    assert state.players[0].resources == Resources(wood=10, grain=8)   # paid 2 grain


def test_millwright_stable_budget_is_per_action():
    # The 2-grain budget is shared across all stables in one Build-Stables action: spend
    # it on stable 1, and stable 2 has no grain option left (a singleton inline debit).
    state = _fe_state_owning(
        "millwright", material=HouseMaterial.WOOD, resources=Resources(wood=20, grain=20))
    state, stable = _drive_to_build_stables(state)
    grain0 = state.players[0].resources.grain
    state = step(state, stable)
    best = max((a.payment for a in legal_actions(state) if isinstance(a, CommitChooseCost)),
               key=lambda r: r.grain)
    assert best.grain == 2
    state = step(state, CommitChooseCost(payment=best))
    stables = [a for a in legal_actions(state) if isinstance(a, CommitBuildStable)]
    assert stables, "expected a second legal stable cell"
    state = step(state, stables[0])
    assert isinstance(state.pending_stack[-1], PendingBuildStables)   # NOT PendingChooseCost
    assert grain0 - state.players[0].resources.grain == 2


# ===========================================================================
# Conservator (occupation) — the renovate-TARGET model: a wood house may renovate
# directly to STONE (skipping clay); the stone-tier cost flows through the chokepoint.
# ===========================================================================

def test_conservator_offers_wood_to_stone_target():
    # With Conservator, the renovate decision offers BOTH wood->clay (2 clay + 1 reed)
    # and wood->stone (2 stone + 1 reed); each commit carries its target.
    state = _hr_state_owning("conservator", resources=Resources(clay=2, reed=1, stone=2))
    state = step(state, PlaceWorker(space="house_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    opts = {(a.to_material, a.payment) for a in legal_actions(state)
            if isinstance(a, CommitRenovate)}
    assert opts == {
        (HouseMaterial.CLAY, Resources(clay=2, reed=1)),
        (HouseMaterial.STONE, Resources(stone=2, reed=1)),
    }
    # Take the direct-to-stone option: house goes straight to stone, stone+reed debited.
    cr = next(a for a in legal_actions(state)
              if isinstance(a, CommitRenovate) and a.to_material is HouseMaterial.STONE)
    state = step(state, cr)
    assert state.players[0].house_material is HouseMaterial.STONE
    assert state.players[0].resources == Resources(clay=2)   # paid 2 stone + 1 reed


def test_without_conservator_only_clay_target():
    state = _hr_state_owning(resources=Resources(clay=2, reed=1, stone=2))
    state = step(state, PlaceWorker(space="house_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    targets = {a.to_material for a in legal_actions(state)
               if isinstance(a, CommitRenovate)}
    assert targets == {HouseMaterial.CLAY}


def test_conservator_stone_target_unaffected_by_clay_reduction():
    # Bricklayer (-1 clay on renovate) discounts the CLAY target but not the STONE one.
    state = _hr_state_owning(
        "conservator", "bricklayer", resources=Resources(clay=2, reed=1, stone=2))
    state = step(state, PlaceWorker(space="house_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    opts = {(a.to_material, a.payment) for a in legal_actions(state)
            if isinstance(a, CommitRenovate)}
    assert opts == {
        (HouseMaterial.CLAY, Resources(clay=1, reed=1)),    # 2 clay - 1 (Bricklayer)
        (HouseMaterial.STONE, Resources(stone=2, reed=1)),  # stone tier, untouched
    }
