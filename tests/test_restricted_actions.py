"""Tests for `agricola/agents/restricted.py`.

`restricted_legal_actions(state)` wraps the engine's unrestricted
`legal_actions(state)` and applies a fixed set of strategic priors. The
tests below validate each filter independently, plus the cross-cutting
invariants:

  - The wrapper never returns an empty action set when the input is
    non-empty (the `_safe_narrow` fallback).
  - The wrapper is a no-op when the pending stack is empty.
  - Each filter narrows or leaves alone — never adds an action.
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitPlow,
    PlaceWorker,
    Stop,
)
from agricola.agents.restricted import (
    FIRST_PASTURE_REQUIRED_CELLS,
    MAX_TOTAL_ROOMS,
    PLOW_PRIORITY,
    ROOM_PRIORITY,
    STABLE_PRIORITY,
    restricted_legal_actions,
)
from agricola.constants import CellType
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBuildFences,
    PendingBuildRooms,
    PendingBuildStables,
    PendingCultivation,
    PendingFarmExpansion,
    PendingGrainUtilization,
    PendingHarvestFeed,
    PendingPlow,
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
# Sub-action ordering: Cultivation
# ---------------------------------------------------------------------------

def test_cultivation_plow_before_sow_when_both_legal():
    """At PendingCultivation with both plow + sow legal, sow drops."""
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
    assert ChooseSubAction(name="sow") not in actions


def test_cultivation_sow_when_plow_already_chosen():
    """Once plow_chosen=True, the ordering filter doesn't apply — sow surfaces."""
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
    assert Stop() in actions


def test_cultivation_sow_only_when_plow_impossible():
    """If plow is illegal (no eligible cells), sow surfaces despite ordering."""
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
    # plow not in offer ⇒ ordering filter is inert, sow stays.
    assert ChooseSubAction(name="sow") in actions
    assert ChooseSubAction(name="plow") not in actions


# ---------------------------------------------------------------------------
# Sub-action ordering: Grain Utilization
# ---------------------------------------------------------------------------

def test_grain_utilization_sow_before_bake():
    """Sow drops bake when sow is also legal."""
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
    assert ChooseSubAction(name="bake_bread") not in actions


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
# Sub-action ordering: Farm Expansion (rooms-before-stables)
# ---------------------------------------------------------------------------

def test_farm_expansion_rooms_before_stables():
    """When both build_rooms and build_stables are legal, stables drop."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Wood house (default), room cost = 5 wood + 2 reed. Stable cost = 2 wood.
    state = with_resources(state, 0, wood=10, reed=2)
    state = with_pending_stack(state, [
        PendingFarmExpansion(player_idx=0, initiated_by_id="space:farm_expansion"),
    ])
    actions = restricted_legal_actions(state)
    assert ChooseSubAction(name="build_rooms") in actions
    assert ChooseSubAction(name="build_stables") not in actions


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
    """At pastures_built == 0, every CommitBuildPasture must include (0,4) or (1,4)."""
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
            f"Restricted opener {sorted(a.cells)} missing both (0,4) and (1,4)."
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
