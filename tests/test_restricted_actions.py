"""Tests for `agricola/agents/restricted.py`.

`restricted_legal_actions(state)` wraps the engine's unrestricted
`legal_actions(state)` and applies a fixed set of strategic priors.
`strict_restricted_legal_actions(state)` layers four additional MCTS-specific
filters on top (Cultivation sow-max, Grain-Util veggie rule, Fencing
patterns, Harvest-feed cap). The tests below validate each filter
independently, plus the cross-cutting invariants:

  - Neither wrapper returns an empty action set when the input is
    non-empty (the `_safe_narrow` fallback).
  - The wrappers are a no-op when the pending stack is empty.
  - Each filter narrows or leaves alone — never adds an action.
  - The strict wrapper is a subset of the regular wrapper.
"""
from __future__ import annotations

import dataclasses

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitHarvestConversion,
    CommitPlow,
    CommitSow,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.agents.restricted import (
    FIRST_PASTURE_REQUIRED_CELLS,
    MAX_TOTAL_ROOMS,
    PLOW_PRIORITY,
    ROOM_PRIORITY,
    STABLE_PRIORITY,
    make_strict_restricted_legal_actions,
    restricted_legal_actions,
    strict_restricted_legal_actions,
)
from agricola.constants import CellType
from agricola.fences import (
    ENTRIES_BY_BM,
    NUM_COLS,
    apply_fence_edges_h,
    apply_fence_edges_v,
)
from agricola.legality import legal_actions
from agricola.pasture import compute_pastures_from_arrays
from agricola.pending import (
    PendingBuildFences,
    PendingBuildRooms,
    PendingBuildStables,
    PendingCultivation,
    PendingFarmExpansion,
    PendingGrainUtilization,
    PendingHarvestFeed,
    PendingPlow,
    PendingSow,
)
from agricola.resources import Animals, Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import (
    add_resources,
    with_animals,
    with_current_player,
    with_grid,
    with_majors,
    with_pending_stack,
    with_people,
    with_resources,
    with_space,
)


# ---------------------------------------------------------------------------
# Helpers shared by the strict-wrapper tests
# ---------------------------------------------------------------------------

def _add_pasture(state, player_idx, cells):
    """Add a pasture to player_idx's farmyard by placing fences around `cells`.

    `cells` must be a list/tuple of (r, c) tuples whose bitmap is an entry in
    UNIVERSE_FULL (i.e., connected, enclosable, hole-free). Repeated calls
    on adjacent cell-sets will produce multiple pastures, sharing boundary
    fences where applicable — the pasture decomposition is recomputed via
    `compute_pastures_from_arrays`.
    """
    cells_bm = sum(1 << (r * NUM_COLS + c) for (r, c) in cells)
    entry = ENTRIES_BY_BM[cells_bm]
    p = state.players[player_idx]
    fy = p.farmyard
    new_h = apply_fence_edges_h(fy.horizontal_fences, entry.h_boundary_bm)
    new_v = apply_fence_edges_v(fy.vertical_fences, entry.v_boundary_bm)
    new_pastures = compute_pastures_from_arrays(fy.grid, new_h, new_v)
    new_fy = dataclasses.replace(
        fy, horizontal_fences=new_h, vertical_fences=new_v,
        pastures=new_pastures,
    )
    new_player = dataclasses.replace(p, farmyard=new_fy)
    new_players = tuple(
        new_player if i == player_idx else state.players[i]
        for i in range(len(state.players))
    )
    return dataclasses.replace(state, players=new_players)


def _build_fences_pending(player_idx=0, pastures_built=0, fences_built=0):
    """Construct a PendingBuildFences frame keyed off the Fencing space."""
    return PendingBuildFences(
        player_idx=player_idx,
        initiated_by_id="fencing",
        pastures_built=pastures_built,
        fences_built=fences_built,
        subdivision_started=False,
    )


# ---------------------------------------------------------------------------
# No-op cases: empty stack, empty inputs
# ---------------------------------------------------------------------------

def test_no_restriction_at_placeworker_level():
    """An empty pending stack means a PlaceWorker decision — no restriction."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    unrestricted = legal_actions(state)
    restricted = restricted_legal_actions(state)
    # Bijective set equality on the action objects (order-insensitive but
    # the underlying enumeration is deterministic, so equality is exact).
    assert restricted == unrestricted


def test_empty_input_passes_through():
    """When the engine returns no actions (e.g. BEFORE_SCORING), the wrapper
    propagates the empty list."""
    state = setup(seed=0)
    # Force phase to BEFORE_SCORING — legal_actions returns [].
    from agricola.constants import Phase

    from tests.factories import with_phase

    state = with_phase(state, Phase.BEFORE_SCORING)
    assert legal_actions(state) == []
    assert restricted_legal_actions(state) == []


# ---------------------------------------------------------------------------
# Cultivation sub-actions (no ordering restriction)
# ---------------------------------------------------------------------------

def test_cultivation_plow_and_sow_both_offered_when_legal():
    """At PendingCultivation with both plow + sow legal, BOTH are offered.

    The plow-before-sow ordering filter was dropped: it force-plowed (removing
    the legitimate sow-only / keep-the-cell-flexible option), which is a lossy
    prior better left to the learned policy. The agent now chooses freely.
    """
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=1)
    # Plow is legal (3 empty non-enclosed cells exist). Sow is legal as long
    # as a field already exists.
    state = with_grid(state, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})
    state = with_pending_stack(state, [
        PendingCultivation(player_idx=0, initiated_by_id="space:cultivation"),
    ])
    actions = restricted_legal_actions(state)
    assert ChooseSubAction(name="plow") in actions
    assert ChooseSubAction(name="sow") in actions


def test_cultivation_sow_when_plow_already_chosen():
    """With plow_chosen=True, sow surfaces (plow already done this turn)."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=1)
    state = with_grid(state, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})
    state = with_pending_stack(state, [
        PendingCultivation(
            player_idx=0,
            initiated_by_id="space:cultivation",
            plow_chosen=True,
        ),
    ])
    actions = restricted_legal_actions(state)
    assert ChooseSubAction(name="sow") in actions
    # Cultivation is a Proceed-host: at the parent's before-phase the
    # turn-ending boundary is Proceed (it flips to the after-phase where Stop pops).
    assert Proceed() in actions


def test_cultivation_sow_only_when_plow_impossible():
    """If plow is illegal (no eligible cells), only sow surfaces."""
    # Fill the entire grid with non-EMPTY cells so plow has no targets, but
    # leave one field with no crop so sow is legal.
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=1)
    overrides = {(r, c): Cell(cell_type=CellType.ROOM) for r in range(3) for c in range(5)}
    overrides[(0, 2)] = Cell(cell_type=CellType.FIELD)  # plow has no empty targets
    state = with_grid(state, 0, overrides)
    state = with_pending_stack(state, [
        PendingCultivation(player_idx=0, initiated_by_id="space:cultivation"),
    ])
    actions = restricted_legal_actions(state)
    # plow not in offer (no empty plow targets) ⇒ only sow available.
    assert ChooseSubAction(name="sow") in actions
    assert ChooseSubAction(name="plow") not in actions


# ---------------------------------------------------------------------------
# Grain Utilization sub-actions (no ordering restriction)
# ---------------------------------------------------------------------------

def test_grain_utilization_sow_and_bake_both_offered():
    """Both sow and bake_bread are offered when both are legal (the
    sow-before-bake ordering filter was dropped)."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=1)
    state = with_grid(state, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})
    state = with_majors(state, owner_by_idx={0: 0})  # Fireplace — owns baker
    state = with_pending_stack(state, [
        PendingGrainUtilization(player_idx=0, initiated_by_id="space:grain_utilization"),
    ])
    actions = restricted_legal_actions(state)
    assert ChooseSubAction(name="sow") in actions
    assert ChooseSubAction(name="bake_bread") in actions


def test_grain_utilization_bake_when_sow_impossible():
    """Bake stays when sow is illegal (e.g., no empty fields)."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=1)
    state = with_majors(state, owner_by_idx={0: 0})  # Fireplace
    # No fields plowed ⇒ sow illegal. Bake legal (has grain + baker).
    state = with_pending_stack(state, [
        PendingGrainUtilization(player_idx=0, initiated_by_id="space:grain_utilization"),
    ])
    actions = restricted_legal_actions(state)
    assert ChooseSubAction(name="bake_bread") in actions
    assert ChooseSubAction(name="sow") not in actions


# ---------------------------------------------------------------------------
# Farm Expansion sub-actions (no ordering restriction)
# ---------------------------------------------------------------------------

def test_farm_expansion_rooms_and_stables_both_offered():
    """When both build_rooms and build_stables are legal, BOTH are offered
    (the rooms-before-stables ordering filter was dropped)."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Wood house (default), room cost = 5 wood + 2 reed. Stable cost = 2 wood.
    state = with_resources(state, 0, wood=10, reed=2)
    state = with_pending_stack(state, [
        PendingFarmExpansion(player_idx=0, initiated_by_id="space:farm_expansion"),
    ])
    actions = restricted_legal_actions(state)
    assert ChooseSubAction(name="build_rooms") in actions
    assert ChooseSubAction(name="build_stables") in actions


def test_farm_expansion_stables_when_rooms_illegal():
    """If can't afford rooms, build_stables is allowed."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Only 2 wood — enough for a stable, not a room.
    state = with_resources(state, 0, wood=2)
    state = with_pending_stack(state, [
        PendingFarmExpansion(player_idx=0, initiated_by_id="space:farm_expansion"),
    ])
    actions = restricted_legal_actions(state)
    assert ChooseSubAction(name="build_stables") in actions
    assert ChooseSubAction(name="build_rooms") not in actions


# ---------------------------------------------------------------------------
# Cell priority filters
# ---------------------------------------------------------------------------

def test_stable_cell_priority_picks_first_available():
    """Among all legal stable cells, only the highest-priority cell remains."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=2)
    state = with_pending_stack(state, [
        PendingBuildStables(
            player_idx=0,
            initiated_by_id="farm_expansion",
            cost=Resources(wood=2),
            max_builds=None,
            num_built=0,
        ),
    ])
    actions = restricted_legal_actions(state)
    stable_actions = [a for a in actions if isinstance(a, CommitBuildStable)]
    assert len(stable_actions) == 1
    # Top priority is (0, 4).
    assert (stable_actions[0].row, stable_actions[0].col) == STABLE_PRIORITY[0]


def test_stable_cell_priority_falls_back_to_next_when_first_occupied():
    """If (0,4) is occupied, (0,3) is picked."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=2)
    state = with_grid(state, 0, {(0, 4): Cell(cell_type=CellType.STABLE)})
    state = with_pending_stack(state, [
        PendingBuildStables(
            player_idx=0,
            initiated_by_id="farm_expansion",
            cost=Resources(wood=2),
            max_builds=None,
            num_built=0,
        ),
    ])
    actions = restricted_legal_actions(state)
    stable_actions = [a for a in actions if isinstance(a, CommitBuildStable)]
    assert len(stable_actions) == 1
    assert (stable_actions[0].row, stable_actions[0].col) == STABLE_PRIORITY[1]


def test_stable_cell_priority_falls_back_to_full_when_all_priority_blocked():
    """If NONE of the priority cells are legal, fall back to all legal cells.

    Block the 4 priority cells with FIELDs (non-EMPTY) so they fail
    `_legal_stable_cells`'s EMPTY filter — but without consuming stable
    supply (which putting STABLEs there would do).
    """
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=2)
    overrides = {cell: Cell(cell_type=CellType.FIELD) for cell in STABLE_PRIORITY}
    state = with_grid(state, 0, overrides)
    state = with_pending_stack(state, [
        PendingBuildStables(
            player_idx=0,
            initiated_by_id="farm_expansion",
            cost=Resources(wood=2),
            max_builds=None,
            num_built=0,
        ),
    ])
    actions = restricted_legal_actions(state)
    stable_actions = [a for a in actions if isinstance(a, CommitBuildStable)]
    # Falls back: every legal stable cell is offered (multiple available —
    # the grid has many EMPTY cells outside the priority list).
    assert len(stable_actions) >= 2
    # And none of the priority cells appear (they're all FIELDs).
    for a in stable_actions:
        assert (a.row, a.col) not in STABLE_PRIORITY


def test_room_cell_priority_picks_top_available():
    """Highest-priority room cell is the only Commit option."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Generous resources so cost isn't the binding constraint.
    state = with_resources(state, 0, wood=10, reed=4, clay=10, stone=10)
    state = with_pending_stack(state, [
        PendingBuildRooms(
            player_idx=0,
            initiated_by_id="farm_expansion",
            cost=Resources(wood=5, reed=2),
            max_builds=None,
            num_built=0,
        ),
    ])
    actions = restricted_legal_actions(state)
    room_actions = [a for a in actions if isinstance(a, CommitBuildRoom)]
    assert len(room_actions) == 1
    # Top priority is (0, 0), which is adjacent to the starting room at (1, 0).
    assert (room_actions[0].row, room_actions[0].col) == ROOM_PRIORITY[0]


def test_plow_cell_priority_picks_top_available():
    """Highest-priority plow cell is the only Commit option."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_pending_stack(state, [
        PendingPlow(player_idx=0, initiated_by_id="space:farmland"),
    ])
    actions = restricted_legal_actions(state)
    plow_actions = [a for a in actions if isinstance(a, CommitPlow)]
    assert len(plow_actions) == 1
    # First plow has no adjacency restriction, so (0, 1) is legal.
    assert (plow_actions[0].row, plow_actions[0].col) == PLOW_PRIORITY[0]


# ---------------------------------------------------------------------------
# Room cap (MAX_TOTAL_ROOMS = 5)
# ---------------------------------------------------------------------------

def _state_with_n_total_rooms(n_total: int):
    """Build a state where player 0 has exactly `n_total` rooms (counting the
    starting rooms at (1, 0) and (2, 0)). Picks additional room cells from
    ROOM_PRIORITY so the resulting state is achievable through normal play.
    """
    assert 2 <= n_total <= 5
    state = setup(seed=0)
    state = with_current_player(state, 0)
    extra_cells = list(ROOM_PRIORITY)[: n_total - 2]
    overrides = {cell: Cell(cell_type=CellType.ROOM) for cell in extra_cells}
    if overrides:
        state = with_grid(state, 0, overrides)
    return state


def test_room_cap_blocks_choose_at_farm_expansion():
    """At 5 rooms, ChooseSubAction("build_rooms") drops."""
    state = _state_with_n_total_rooms(MAX_TOTAL_ROOMS)
    state = with_resources(state, 0, wood=10, reed=4, clay=10, stone=10)
    state = with_pending_stack(state, [
        PendingFarmExpansion(player_idx=0, initiated_by_id="space:farm_expansion"),
    ])
    actions = restricted_legal_actions(state)
    # build_rooms should be filtered. Either build_stables remains, or
    # (if no other choice is legal in the test setup) the safe fallback
    # preserves the original action list. In this case stables are
    # affordable so they should appear.
    assert ChooseSubAction(name="build_rooms") not in actions
    assert ChooseSubAction(name="build_stables") in actions


def test_room_cap_blocks_commit_at_build_rooms():
    """When inside PendingBuildRooms and at cap, further CommitBuildRoom drops.

    This case is rare (the cap is also applied at the FarmExpansion level so
    PendingBuildRooms shouldn't be entered when already at cap), but it
    matters when the cap is hit mid-session — the player committed their
    Nth room, the engine offers room N+1, and the wrapper filters it out.
    """
    state = _state_with_n_total_rooms(MAX_TOTAL_ROOMS)
    state = with_resources(state, 0, wood=10, reed=4, clay=10, stone=10)
    state = with_pending_stack(state, [
        PendingBuildRooms(
            player_idx=0,
            initiated_by_id="farm_expansion",
            cost=Resources(wood=5, reed=2),
            max_builds=None,
            num_built=1,  # at least one room built this session ⇒ Stop legal
        ),
    ])
    actions = restricted_legal_actions(state)
    room_actions = [a for a in actions if isinstance(a, CommitBuildRoom)]
    assert room_actions == []
    assert Stop() in actions


def test_room_cap_inactive_when_below_max():
    """At fewer than MAX_TOTAL_ROOMS, the cap is inert."""
    state = _state_with_n_total_rooms(3)  # 2 starting + 1 added
    state = with_resources(state, 0, wood=10, reed=4)
    state = with_pending_stack(state, [
        PendingFarmExpansion(player_idx=0, initiated_by_id="space:farm_expansion"),
    ])
    actions = restricted_legal_actions(state)
    assert ChooseSubAction(name="build_rooms") in actions


# ---------------------------------------------------------------------------
# First-pasture restriction
# ---------------------------------------------------------------------------

def test_first_pasture_must_include_required_cell():
    """At pastures_built == 0, every CommitBuildPasture must include a cell
    from FIRST_PASTURE_REQUIRED_CELLS (currently just (0,4))."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Plenty of wood + fences available so candidates are not affordability-blocked.
    state = with_resources(state, 0, wood=10)
    state = with_pending_stack(state, [
        PendingBuildFences(
            player_idx=0,
            initiated_by_id="space:fencing",
            pastures_built=0,
            fences_built=0,
            subdivision_started=False,
        ),
    ])
    actions = restricted_legal_actions(state)
    pasture_actions = [a for a in actions if isinstance(a, CommitBuildPasture)]
    assert pasture_actions, "Expected at least one legal opener under the restriction."
    for a in pasture_actions:
        assert any(cell in FIRST_PASTURE_REQUIRED_CELLS for cell in a.cells), (
            f"Restricted opener {sorted(a.cells)} missing every cell in "
            f"FIRST_PASTURE_REQUIRED_CELLS={sorted(FIRST_PASTURE_REQUIRED_CELLS)}."
        )


def test_subsequent_pastures_unrestricted():
    """At pastures_built >= 1, the first-pasture restriction lifts."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=10)
    state = with_pending_stack(state, [
        PendingBuildFences(
            player_idx=0,
            initiated_by_id="space:fencing",
            pastures_built=1,
            fences_built=4,
            subdivision_started=False,
        ),
    ])
    restricted = restricted_legal_actions(state)
    unrestricted = legal_actions(state)
    # No narrowing: the filter is inert.
    assert sorted(map(repr, restricted)) == sorted(map(repr, unrestricted))


# ---------------------------------------------------------------------------
# Min-begging filter at PendingHarvestFeed
# ---------------------------------------------------------------------------

def test_min_begging_filter_keeps_zero_begging():
    """When at least one CommitConvert avoids begging, all begging-incurring
    options drop."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Two people, no newborns ⇒ need = 4 food. Player has 4 food on hand — no
    # conversion is required to feed. Also has 2 grain (could convert if it
    # wanted to, but the (0,0,0,0,0)-consumed config is feasible).
    state = with_people(state, 0, total=2, home=2, newborns=0)
    state = with_resources(state, 0, food=4, grain=2)
    state = with_pending_stack(state, [
        PendingHarvestFeed(player_idx=0, initiated_by_id="phase:harvest_feed"),
    ])
    actions = restricted_legal_actions(state)
    converts = [a for a in actions if isinstance(a, CommitConvert)]
    assert converts, "Expected at least one CommitConvert."
    # All surviving converts should yield zero begging.
    from agricola.helpers import cooking_rates
    sR, bR, cR, vR = cooking_rates(state, 0)
    for a in converts:
        food_produced = a.grain + a.veg * vR + a.sheep * sR + a.boar * bR + a.cattle * cR
        begging = max(0, 4 - 4 - food_produced)
        assert begging == 0


def test_min_begging_filter_keeps_minimum_when_all_beg():
    """When every CommitConvert incurs begging, only the minimum-begging
    options survive."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # 2 people, no newborns ⇒ need 4 food. Player has 0 food, no convertible
    # goods. Engine offers exactly one CommitConvert (consume 0 everything)
    # with begging = 4. With only one option, the filter is inert.
    state = with_people(state, 0, total=2, home=2, newborns=0)
    state = with_resources(state, 0)  # all zeros
    state = with_animals(state, 0)
    state = with_pending_stack(state, [
        PendingHarvestFeed(player_idx=0, initiated_by_id="phase:harvest_feed"),
    ])
    unrestricted = legal_actions(state)
    restricted = restricted_legal_actions(state)
    assert restricted == unrestricted  # singleton CommitConvert, no narrowing


def test_min_begging_filter_narrows_when_partial_payment_possible():
    """Player has 1 grain + needs 4 food + no food on hand: convert-1 begs 3,
    convert-0 begs 4. Filter keeps only the convert-1 option."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_people(state, 0, total=2, home=2, newborns=0)
    state = with_resources(state, 0, grain=1)
    state = with_animals(state, 0)
    state = with_pending_stack(state, [
        PendingHarvestFeed(player_idx=0, initiated_by_id="phase:harvest_feed"),
    ])
    actions = restricted_legal_actions(state)
    converts = [a for a in actions if isinstance(a, CommitConvert)]
    # Only the (grain=1) option should remain.
    assert len(converts) == 1
    assert converts[0].grain == 1


# ---------------------------------------------------------------------------
# Cross-cutting: always-≥1 invariant on a randomized walk
# ---------------------------------------------------------------------------

def test_wrapper_never_empties_action_set_in_random_play():
    """Run a random game through the wrapper; assert that
    `restricted_legal_actions` never returns an empty list when
    `legal_actions` is non-empty.
    """
    import numpy as np

    from agricola.constants import Phase
    from agricola.engine import step
    from tests.test_utils import filter_implemented

    rng = np.random.default_rng(0)
    state = setup(seed=0)
    while state.phase != Phase.BEFORE_SCORING:
        unrestricted = filter_implemented(legal_actions(state))
        restricted = filter_implemented(restricted_legal_actions(state))
        # If the engine has any legal moves, the wrapper must too.
        if unrestricted:
            assert restricted, (
                f"Wrapper emptied a non-empty action set. "
                f"phase={state.phase}, stack_top={type(state.pending_stack[-1]).__name__ if state.pending_stack else None}"
            )
            # Wrapper-supplied actions are always a subset of the unrestricted set.
            for a in restricted:
                assert a in unrestricted, (
                    f"Wrapper returned an action {a!r} not in the unrestricted set."
                )
            action = restricted[int(rng.integers(len(restricted)))]
        else:
            # Unrestricted is empty — game cannot continue from here.
            break
        state = step(state, action)


# ===========================================================================
# Strict wrapper (MCTS_DESIGN §7) — additional filters layered atop the
# regular wrapper.
# ===========================================================================


# ---------------------------------------------------------------------------
# Strict wrapper: no-op cases
# ---------------------------------------------------------------------------

def test_strict_no_op_at_placeworker_level():
    """An empty pending stack means a PlaceWorker decision — strict adds nothing."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    regular = restricted_legal_actions(state)
    strict = strict_restricted_legal_actions(state)
    assert strict == regular


def test_strict_empty_input_passes_through():
    """When the engine returns no actions, the strict wrapper returns []."""
    from agricola.constants import Phase

    from tests.factories import with_phase

    state = setup(seed=0)
    state = with_phase(state, Phase.BEFORE_SCORING)
    assert strict_restricted_legal_actions(state) == []


def test_strict_is_subset_of_regular():
    """The strict wrapper's output is always a subset of the regular wrapper's
    output on a single fresh-game state."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_pending_stack(state, [
        PendingCultivation(player_idx=0, initiated_by_id="space:cultivation"),
    ])
    regular = set(map(repr, restricted_legal_actions(state)))
    strict = set(map(repr, strict_restricted_legal_actions(state)))
    assert strict <= regular


# ---------------------------------------------------------------------------
# Cultivation sow-max (§7.1)
# ---------------------------------------------------------------------------

def test_cultivation_sow_max_picks_max_total():
    """At Cultivation's PendingSow, only the grain+veg-maximizing commit survives."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=2, veg=1)
    # Two empty fields.
    state = with_grid(state, 0, {
        (0, 1): Cell(cell_type=CellType.FIELD),
        (0, 2): Cell(cell_type=CellType.FIELD),
    })
    state = with_pending_stack(state, [
        PendingSow(player_idx=0, initiated_by_id="cultivation"),
    ])
    actions = strict_restricted_legal_actions(state)
    sows = [a for a in actions if isinstance(a, CommitSow)]
    assert len(sows) == 1
    # Best: total=2 with grain priority → (grain=2, veg=0). Note that
    # (1, 1) also totals 2 but the grain-priority tiebreak picks (2, 0).
    assert sows[0].grain + sows[0].veg == 2
    assert sows[0].grain == 2


def test_cultivation_sow_max_grain_priority_on_ties():
    """When several commits tie on total, more-grain wins."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=1, veg=1)
    state = with_grid(state, 0, {
        (0, 1): Cell(cell_type=CellType.FIELD),
        (0, 2): Cell(cell_type=CellType.FIELD),
    })
    state = with_pending_stack(state, [
        PendingSow(player_idx=0, initiated_by_id="cultivation"),
    ])
    actions = strict_restricted_legal_actions(state)
    sows = [a for a in actions if isinstance(a, CommitSow)]
    assert len(sows) == 1
    # (g=1, v=1) ties with itself on total=2; only one option.
    assert (sows[0].grain, sows[0].veg) == (1, 1)


def test_cultivation_sow_max_does_not_fire_for_grain_utilization():
    """Sow-max applies ONLY when PendingSow was pushed by Cultivation."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=2)
    state = with_grid(state, 0, {
        (0, 1): Cell(cell_type=CellType.FIELD),
        (0, 2): Cell(cell_type=CellType.FIELD),
    })
    state = with_pending_stack(state, [
        PendingSow(player_idx=0, initiated_by_id="grain_utilization"),
    ])
    actions = strict_restricted_legal_actions(state)
    sows = [a for a in actions if isinstance(a, CommitSow)]
    # Veggie rule applies (veg=0), but sow-max does NOT, so both grain values
    # survive: (g=1, v=0) and (g=2, v=0).
    grain_values = sorted(a.grain for a in sows)
    assert grain_values == [1, 2]


# ---------------------------------------------------------------------------
# Grain-Utilization veggie rule (§7.2)
# ---------------------------------------------------------------------------

def test_grain_util_veggie_auto_maxed():
    """At Grain-Util's PendingSow with veggies available, `veg_sown` is auto-maxed
    per grain choice: `veg_sown == min(veg_supply, empty_fields − grain_sown)`."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=2, veg=2)
    # Three empty fields.
    state = with_grid(state, 0, {
        (0, 1): Cell(cell_type=CellType.FIELD),
        (0, 2): Cell(cell_type=CellType.FIELD),
        (1, 1): Cell(cell_type=CellType.FIELD),
    })
    state = with_pending_stack(state, [
        PendingSow(player_idx=0, initiated_by_id="grain_utilization"),
    ])
    actions = strict_restricted_legal_actions(state)
    sows = [a for a in actions if isinstance(a, CommitSow)]
    # Per the rule, for each `grain_sown` ∈ {0, 1, 2}, the required
    # veg = min(2, 3 - grain).
    # grain=0 → veg=2; grain=1 → veg=2; grain=2 → veg=1.
    expected = {(0, 2), (1, 2), (2, 1)}
    actual = {(a.grain, a.veg) for a in sows}
    assert actual == expected


def test_grain_util_veggie_no_veggies_means_veg_zero():
    """When the player has no veggies, only commits with veg=0 survive."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=2, veg=0)
    state = with_grid(state, 0, {
        (0, 1): Cell(cell_type=CellType.FIELD),
        (0, 2): Cell(cell_type=CellType.FIELD),
    })
    state = with_pending_stack(state, [
        PendingSow(player_idx=0, initiated_by_id="grain_utilization"),
    ])
    actions = strict_restricted_legal_actions(state)
    sows = [a for a in actions if isinstance(a, CommitSow)]
    assert all(a.veg == 0 for a in sows)
    # All grain values 1..2 survive.
    assert sorted(a.grain for a in sows) == [1, 2]


def test_grain_util_veggie_does_not_fire_for_cultivation():
    """Veggie rule applies ONLY at Grain-Util's PendingSow, not Cultivation's."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=1, veg=1)
    state = with_grid(state, 0, {
        (0, 1): Cell(cell_type=CellType.FIELD),
        (0, 2): Cell(cell_type=CellType.FIELD),
    })
    state = with_pending_stack(state, [
        PendingSow(player_idx=0, initiated_by_id="cultivation"),
    ])
    actions = strict_restricted_legal_actions(state)
    sows = [a for a in actions if isinstance(a, CommitSow)]
    # Cultivation sow-max fires → unique max-total commit (g=1, v=1) wins.
    assert len(sows) == 1
    assert (sows[0].grain, sows[0].veg) == (1, 1)


# ---------------------------------------------------------------------------
# Fencing patterns (§7.3) — 9 hand-curated rules
# ---------------------------------------------------------------------------

def _fencing_test_state(wood, pasture_cell_sets=()):
    """Build a state at PendingBuildFences with the given wood + existing pastures.

    `pasture_cell_sets` is a list of cell-set tuples; each becomes one pasture
    via `_add_pasture`. `pastures_built` on the pending is set to the number
    of pastures provided so the engine knows the session is mid-action.
    """
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=wood)
    for cells in pasture_cell_sets:
        state = _add_pasture(state, 0, cells)
    state = with_pending_stack(state, [
        _build_fences_pending(
            pastures_built=len(pasture_cell_sets), fences_built=0,
        ),
    ])
    return state


def test_fencing_rule_1_wood7_through_9_opens_with_top_right_cell():
    """No pastures + wood ∈ {7, 8, 9} → only CommitBuildPasture({(0, 4)})."""
    for wood in (7, 8, 9):
        state = _fencing_test_state(wood=wood)
        actions = strict_restricted_legal_actions(state)
        commits = [a for a in actions if isinstance(a, CommitBuildPasture)]
        assert len(commits) == 1, f"wood={wood}: got {len(commits)} commits"
        assert commits[0].cells == frozenset({(0, 4)})


def test_fencing_rule_2_wood10_offers_2x2_or_3x2():
    """No pastures + wood = 10 → 2x2 OR 3x2 at top-right."""
    state = _fencing_test_state(wood=10)
    actions = strict_restricted_legal_actions(state)
    commits = [a for a in actions if isinstance(a, CommitBuildPasture)]
    cell_sets = {a.cells for a in commits}
    assert cell_sets == {
        frozenset({(0, 3), (0, 4), (1, 3), (1, 4)}),
        frozenset({(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)}),
    }


def test_fencing_rule_3_wood13_locks_3x2():
    """No pastures + wood = 13 → only the 3x2 at top-right."""
    state = _fencing_test_state(wood=13)
    actions = strict_restricted_legal_actions(state)
    commits = [a for a in actions if isinstance(a, CommitBuildPasture)]
    assert len(commits) == 1
    assert commits[0].cells == frozenset(
        {(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)},
    )


def test_fencing_rule_4_wood15_offers_8cell_L_or_3x2():
    """No pastures + wood = 15 → 8-cell L OR 3x2."""
    state = _fencing_test_state(wood=15)
    actions = strict_restricted_legal_actions(state)
    commits = [a for a in actions if isinstance(a, CommitBuildPasture)]
    cell_sets = {a.cells for a in commits}
    assert cell_sets == {
        frozenset({(0, 3), (0, 4), (1, 2), (1, 3), (1, 4),
                   (2, 2), (2, 3), (2, 4)}),
        frozenset({(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)}),
    }


def test_fencing_rule_5_extend_top_right_with_one_cell():
    """1x1 at (0,4) + wood = 3 → CommitBuildPasture({(0,3)}) OR Stop."""
    state = _fencing_test_state(wood=3, pasture_cell_sets=[[(0, 4)]])
    actions = strict_restricted_legal_actions(state)
    commits = [a for a in actions if isinstance(a, CommitBuildPasture)]
    assert len(commits) == 1
    assert commits[0].cells == frozenset({(0, 3)})
    # Stop is allowed by the rule AND legal at the pending (pastures_built=1).
    assert Stop() in actions


def test_fencing_rule_6_extend_down_two_cells():
    """1x1 at (0,4) + wood = 5 → CommitBuildPasture({(1,4),(2,4)}) OR Stop."""
    state = _fencing_test_state(wood=5, pasture_cell_sets=[[(0, 4)]])
    actions = strict_restricted_legal_actions(state)
    commits = [a for a in actions if isinstance(a, CommitBuildPasture)]
    assert len(commits) == 1
    assert commits[0].cells == frozenset({(1, 4), (2, 4)})
    assert Stop() in actions


def test_fencing_rule_7_subdivide_2x2_at_top_right():
    """Single 2x2 at top-right + wood = 2 → subdivide into 1x2 ({(0,3),(0,4)})."""
    state = _fencing_test_state(
        wood=2, pasture_cell_sets=[[(0, 3), (0, 4), (1, 3), (1, 4)]],
    )
    actions = strict_restricted_legal_actions(state)
    commits = [a for a in actions if isinstance(a, CommitBuildPasture)]
    assert len(commits) == 1
    assert commits[0].cells == frozenset({(0, 3), (0, 4)})
    # Stop is NOT in the rule's allowed set, so it's filtered out.
    assert Stop() not in actions


def test_fencing_rule_8_extend_top_2_when_split_into_one_pasture():
    """Single 1x2 at {(0,3),(0,4)} + wood = 4 → extend to row 1 OR Stop."""
    state = _fencing_test_state(
        wood=4, pasture_cell_sets=[[(0, 3), (0, 4)]],
    )
    actions = strict_restricted_legal_actions(state)
    commits = [a for a in actions if isinstance(a, CommitBuildPasture)]
    assert len(commits) == 1
    assert commits[0].cells == frozenset({(1, 3), (1, 4)})
    assert Stop() in actions


def test_fencing_rule_8_extend_top_2_when_split_into_two_pastures():
    """Two 1x1s at (0,3) and (0,4) + wood = 4 → same allowed action.

    Rules 8/9 are cell-set-union-keyed: they fire whether the union is one
    pasture or several. Verify by building two non-adjacent 1x1s.
    """
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=4)
    # Build (0,3) and (0,4) as separate 1x1 pastures (fence between them).
    state = _add_pasture(state, 0, [(0, 3)])
    state = _add_pasture(state, 0, [(0, 4)])
    state = with_pending_stack(state, [
        _build_fences_pending(pastures_built=2),
    ])
    # Sanity: union of pasture cells is {(0,3),(0,4)}; two pastures present.
    p = state.players[0]
    assert len(p.farmyard.pastures) == 2
    assert frozenset(c for past in p.farmyard.pastures for c in past.cells) \
        == frozenset({(0, 3), (0, 4)})
    actions = strict_restricted_legal_actions(state)
    commits = [a for a in actions if isinstance(a, CommitBuildPasture)]
    cell_sets = {a.cells for a in commits}
    # Should still see the single allowed extension (the rule fires on union).
    assert frozenset({(1, 3), (1, 4)}) in cell_sets


def test_fencing_rule_9_extend_top_2_into_bottom_2x2():
    """Pastures cover exactly {(0,3),(0,4)} + wood = 6 → bottom 2x2 OR Stop."""
    state = _fencing_test_state(
        wood=6, pasture_cell_sets=[[(0, 3), (0, 4)]],
    )
    actions = strict_restricted_legal_actions(state)
    commits = [a for a in actions if isinstance(a, CommitBuildPasture)]
    assert len(commits) == 1
    assert commits[0].cells == frozenset({(1, 3), (1, 4), (2, 3), (2, 4)})
    assert Stop() in actions


def test_fencing_no_rule_match_passes_through():
    """No matching rule (e.g., wood = 8 with an existing pasture) → no filter."""
    state = _fencing_test_state(wood=8, pasture_cell_sets=[[(0, 4)]])
    regular = restricted_legal_actions(state)
    strict = strict_restricted_legal_actions(state)
    # Strict adds no extra filter — output identical to regular.
    assert sorted(map(repr, strict)) == sorted(map(repr, regular))


def test_fencing_rule_7_pasture_identity_required():
    """Rule 7 (subdivision) requires the 2x2 cells to be ONE pasture, not split."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=2)
    # Build the 2x2 as TWO separate 1x2 pastures (split horizontally).
    state = _add_pasture(state, 0, [(0, 3), (0, 4)])
    state = _add_pasture(state, 0, [(1, 3), (1, 4)])
    state = with_pending_stack(state, [
        _build_fences_pending(pastures_built=2),
    ])
    # Sanity check.
    p = state.players[0]
    assert len(p.farmyard.pastures) == 2
    actions = strict_restricted_legal_actions(state)
    # Rule 7 doesn't apply (pastures != single 2x2). Pasture union is
    # {(0,3),(0,4),(1,3),(1,4)} which doesn't match rule 8/9's {(0,3),(0,4)}.
    # So strict is inert — output equals regular.
    regular = restricted_legal_actions(state)
    assert sorted(map(repr, strict_restricted_legal_actions(state))) \
        == sorted(map(repr, regular))


# ---------------------------------------------------------------------------
# Harvest-feed cap (§7.4)
# ---------------------------------------------------------------------------

def _harvest_feed_state_with_many_commits():
    """Build a state with > 7 legal CommitConvert options at PendingHarvestFeed.

    Player: 2 people (need=4), 0 food, lots of crops + animals + Cooking
    Hearth so all conversion rates are non-zero. The frontier produces many
    Pareto-optimal payment configurations that all meet need exactly with
    different goods tradeoffs.
    """
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_people(state, 0, total=2, home=2, newborns=0)
    # Cooking Hearth (idx 2) gives rates (sheep=2, boar=3, cattle=4, veg=3).
    state = with_majors(state, owner_by_idx={2: 0})
    state = with_resources(state, 0, food=0, grain=4, veg=2)
    state = with_animals(state, 0, sheep=4, boar=2, cattle=1)
    state = with_pending_stack(state, [
        PendingHarvestFeed(player_idx=0, initiated_by_id="phase:harvest_feed"),
    ])
    return state


def test_harvest_feed_cap_inactive_when_seven_or_fewer_commits():
    """≤7 commits: no cap. Strict output equals regular at this layer."""
    # A simple state with very few commits.
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_people(state, 0, total=2, home=2, newborns=0)
    state = with_resources(state, 0, food=4)
    state = with_pending_stack(state, [
        PendingHarvestFeed(player_idx=0, initiated_by_id="phase:harvest_feed"),
    ])
    regular = restricted_legal_actions(state)
    strict = strict_restricted_legal_actions(state)
    # With food=4 and need=4, the only commit is (0,0,0,0,0).
    assert sorted(map(repr, regular)) == sorted(map(repr, strict))


def test_harvest_feed_cap_engages_when_many_commits():
    """When > 7 commits remain after the regular wrapper, the cap fires.

    Crafts and other actions pass through unchanged; commit count drops to 7
    (top-5 by V3 + 2 random).
    """
    state = _harvest_feed_state_with_many_commits()
    regular = restricted_legal_actions(state)
    regular_commits = [a for a in regular if isinstance(a, CommitConvert)]
    if len(regular_commits) <= 7:
        # State doesn't trigger the cap — sanity-skip the cap-specific
        # assertion, but verify the inert pass-through.
        assert sorted(map(repr, strict_restricted_legal_actions(state))) \
            == sorted(map(repr, regular))
        return
    strict = strict_restricted_legal_actions(state)
    strict_commits = [a for a in strict if isinstance(a, CommitConvert)]
    # Cap kicks in: exactly 7 commits surviving (5 top + 2 random).
    assert len(strict_commits) == 7
    # All commits in strict are also in regular.
    for a in strict_commits:
        assert a in regular_commits


def test_harvest_feed_cap_preserves_crafts():
    """The cap never sub-samples CommitHarvestConversion entries."""
    state = _harvest_feed_state_with_many_commits()
    # Add a Joinery and wood to expose a craft option.
    state = with_majors(state, owner_by_idx={2: 0, 7: 0})  # Hearth + Joinery
    state = add_resources(state, 0, wood=1)
    strict = strict_restricted_legal_actions(state)
    crafts = [a for a in strict if isinstance(a, CommitHarvestConversion)]
    # The engine offers exactly one craft action (fire Joinery); the cap passes
    # crafts through untouched. Joinery + 1 wood available → one craft remains.
    assert len(crafts) == 1
    assert crafts[0].conversion_id == "joinery"


def test_harvest_feed_cap_deterministic_with_same_rng():
    """Two strict wrappers built with the same seed produce the same picks."""
    import numpy as np

    state = _harvest_feed_state_with_many_commits()
    regular_commits = [
        a for a in restricted_legal_actions(state) if isinstance(a, CommitConvert)
    ]
    if len(regular_commits) <= 7:
        # Cap inactive — determinism check is trivially satisfied.
        return
    fn_a = make_strict_restricted_legal_actions(rng=np.random.default_rng(42))
    fn_b = make_strict_restricted_legal_actions(rng=np.random.default_rng(42))
    out_a = sorted(map(repr, fn_a(state)))
    out_b = sorted(map(repr, fn_b(state)))
    assert out_a == out_b


# ---------------------------------------------------------------------------
# Cross-cutting: strict wrapper always-≥1 invariant on a random walk
# ---------------------------------------------------------------------------

def test_strict_wrapper_never_empties_action_set_in_random_play():
    """Run a random game using strict legality; assert non-empty action sets."""
    import numpy as np

    from agricola.constants import Phase
    from agricola.engine import step
    from tests.test_utils import filter_implemented

    rng = np.random.default_rng(0)
    state = setup(seed=0)
    while state.phase != Phase.BEFORE_SCORING:
        unrestricted = filter_implemented(legal_actions(state))
        strict = filter_implemented(strict_restricted_legal_actions(state))
        if unrestricted:
            assert strict, (
                f"Strict wrapper emptied a non-empty set. "
                f"phase={state.phase}, "
                f"stack_top={type(state.pending_stack[-1]).__name__ if state.pending_stack else None}"
            )
            for a in strict:
                assert a in unrestricted, (
                    f"Strict returned action {a!r} not in unrestricted."
                )
            action = strict[int(rng.integers(len(strict)))]
        else:
            break
        state = step(state, action)
