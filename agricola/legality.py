from __future__ import annotations

import contextlib
import functools
import threading
from typing import Callable

from agricola import opt_config
from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitBake,
    CommitBreed,
    CommitBuildMajor,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitHarvestConversion,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    RevealCard,
    Stop,
)
from agricola.constants import (
    BAKING_IMPROVEMENT_SPECS,
    BAKING_IMPROVEMENTS,
    CellType,
    HouseMaterial,
    MAJOR_IMPROVEMENT_COSTS,
    Phase,
    ROOM_COSTS,
    STAGE_CARDS,
    stage_of_round,
)
from agricola.fences import (
    NUM_COLS,
    NUM_ROWS,
    PastureCandidate,
    UNIVERSE_RESTRICTED_ENTRIES,
    UNIVERSE_RESTRICTED_SET,
    UNIVERSE_RESTRICTED_SMALLEST_ENTRIES,
    pack_fences_h,
    pack_fences_v,
)
from agricola.resources import Resources
from agricola.helpers import enclosed_cells, fences_in_supply, stables_in_supply
from agricola.pending import (
    PendingBakeBread,
    PendingBuildFences,
    PendingBuildMajor,
    PendingBuildRooms,
    PendingBuildStables,
    PendingDecision,
    PendingFarmExpansion,
    PendingFarmRedevelopment,
    PendingFencing,
    PendingGrainUtilization,
    PendingPlow,
    PendingRenovate,
    PendingReveal,
    PendingSow,
)
from agricola.state import GameState, PlayerState, get_space


# ---------------------------------------------------------------------------
# Active fence-universe constants (TASK_6 §4.1)
# ---------------------------------------------------------------------------
#
# Three module-level constants set the default universe for `legal_actions`.
# All three must point at the same universe; they are kept aligned by the
# `fences.py` construction (RESTRICTED_ENTRIES ↔ RESTRICTED_SMALLEST_ENTRIES ↔
# RESTRICTED_SET).
#
# Switching the active universe:
#
#   - For a single call, pass `entries=`, `smallest_entries=`, `universe_set=`
#     kwargs to the enumerator.
#   - For a block of code, reassign all three constants. The enumerators
#     resolve the active universe at CALL time (not definition time), so a
#     reassignment takes effect immediately for default-kwarg call sites.
#     The `active_universe(...)` context manager in `agricola.fence_universe`
#     wraps this with save/restore (recommended over manual reassignment).
#   - For derived universes, build a (entries, smallest_entries, set) triple
#     via `restrict_to(predicate, base=...)` in `agricola.fence_universe`.

ACTIVE_FENCE_UNIVERSE_ENTRIES:          tuple     = UNIVERSE_RESTRICTED_ENTRIES
ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES: tuple     = UNIVERSE_RESTRICTED_SMALLEST_ENTRIES
ACTIVE_FENCE_UNIVERSE_SET:              frozenset = UNIVERSE_RESTRICTED_SET


# ---------------------------------------------------------------------------
# Card-extension registries
# ---------------------------------------------------------------------------

# Cards may broaden _can_bake_bread by registering an extension predicate.
# Each extension is `(state, p) -> bool`. _can_bake_bread returns True if
# the base check passes OR any extension returns True. See
# IMPLEMENTATION_CHOICES.md "Card-extension pattern for legality helpers".
BAKE_BREAD_ELIGIBILITY_EXTENSIONS: list[Callable] = []


def register_bake_bread_extension(fn: Callable) -> None:
    """Add a card-supplied predicate that may broaden _can_bake_bread."""
    BAKE_BREAD_ELIGIBILITY_EXTENSIONS.append(fn)


# Card-supplied baking sources. Each registered fn takes (state, player_idx)
# and returns a list of (max_grain_per_action, food_per_grain) tuples for
# baking sources the player owns from non-major-improvement origins
# (minor improvements, occupations, future card types).
BAKING_SPEC_EXTENSIONS: list[Callable] = []


def register_baking_spec_extension(fn: Callable) -> None:
    BAKING_SPEC_EXTENSIONS.append(fn)


def baking_specs_for_player(
    state: GameState, player_idx: int,
) -> list[tuple]:
    """Collect (max_grain_per_action, food_per_grain) specs for every baking
    source the player owns. Major improvements feed in directly from
    BAKING_IMPROVEMENT_SPECS; cards (minor improvements, occupations) feed in
    via BAKING_SPEC_EXTENSIONS. The greedy allocator in _execute_bake and the
    grain-cap computation in _enumerate_pending_bake_bread both consume this
    spec list and remain agnostic to source.

    Note: resolution.py imports this helper, introducing a
    resolution.py -> legality.py dependency. The arrow is one-way today
    (legality.py does not import from resolution.py), so no cycle. If a
    future card-eligibility path forces a cycle, move this helper and
    BAKING_SPEC_EXTENSIONS into a new agricola/baking.py module.
    """
    specs: list = []
    owners = state.board.major_improvement_owners
    for idx, spec in BAKING_IMPROVEMENT_SPECS.items():
        if owners[idx] == player_idx:
            specs.append(spec)
    for ext in BAKING_SPEC_EXTENSIONS:
        specs.extend(ext(state, player_idx))
    return specs


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _is_available(state: GameState, space: str) -> bool:
    """Cross-cutting check: space is unoccupied and currently revealed."""
    sp = get_space(state.board, space)
    unoccupied = sp.workers == (0, 0)
    return unoccupied and sp.revealed


def _num_rooms(player: PlayerState) -> int:
    """Count ROOM cells in the player's farmyard grid."""
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if player.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _owns_baker(state: GameState, p: PlayerState) -> bool:
    """Whether the given player owns at least one baking improvement.

    Identity-based player_idx derivation, same as the rest of this module.
    """
    player_idx = 0 if p is state.players[0] else 1
    return any(
        state.board.major_improvement_owners[i] == player_idx
        for i in BAKING_IMPROVEMENTS
    )


def _can_bake_bread(state: GameState, p: PlayerState) -> bool:
    """The given player can execute a Bake Bread action.

    Base check: owns a baker AND has at least 1 grain in personal supply.
    Card extensions registered via register_bake_bread_extension may
    broaden this (e.g., Potter Ceramics enables baking when grain == 0
    but clay >= 1 — the trigger fires before bake, swapping clay for grain).

    The player's index is derived from `p` itself (by identity comparison
    against `state.players`), not from `state.current_player`. This makes
    the helper correct for any `p` in the state, not just the
    currently-active player.
    """
    if _owns_baker(state, p) and p.resources.grain >= 1:
        return True
    # Card extensions widen the predicate.
    for ext in BAKE_BREAD_ELIGIBILITY_EXTENSIONS:
        if ext(state, p):
            return True
    return False


def _can_sow(p: PlayerState) -> bool:
    """At least one empty field cell exists AND ≥1 grain or veg in supply."""
    grid = p.farmyard.grid
    has_empty_field = any(
        grid[r][c].cell_type == CellType.FIELD
        and grid[r][c].grain == 0
        and grid[r][c].veg == 0
        for r in range(3) for c in range(5)
    )
    has_seed = p.resources.grain >= 1 or p.resources.veg >= 1
    return has_empty_field and has_seed


def _can_plow(p: PlayerState) -> bool:
    """At least one valid plow target exists.

    A plow target must be EMPTY AND non-enclosed (cells inside a pasture cannot
    be converted to fields per RULES.md §Fields and Crops).

    First field: any EMPTY non-enclosed cell.
    Subsequent fields: additionally orthogonally adjacent to an existing FIELD.
    """
    return bool(_legal_plow_cells(p))


def _can_build_stable(p: PlayerState, cost: Resources) -> bool:
    """Combined legality check for one stable build at the given cost.

    Empty cell exists + ≥1 stable in supply + can afford `cost`.
    Parameterized on cost: Farm Expansion uses 2 wood; Side Job uses 1 wood;
    future cards may inject other costs.
    """
    return (
        stables_in_supply(p.farmyard) >= 1
        and bool(_legal_stable_cells(p))
        and _can_afford(p, cost)
    )


def _legal_plow_cells(p: PlayerState) -> list:
    """Enumerate every (row, col) that is a legal plow target.

    Same conditions as `_can_plow`'s existence check, but returns the
    set of cells. Used by `_enumerate_pending_plow`.
    """
    grid = p.farmyard.grid
    enclosed = enclosed_cells(p.farmyard)
    field_cells = {
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    }
    empty_unenclosed = [
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY
        and (r, c) not in enclosed
    ]
    if not field_cells:
        # First field: any empty, non-enclosed cell.
        return empty_unenclosed
    # Subsequent fields: orthogonally adjacent to an existing field.
    adjacent_to_field = {
        (r + dr, c + dc)
        for (r, c) in field_cells
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]
    }
    return [cell for cell in empty_unenclosed if cell in adjacent_to_field]


def _legal_stable_cells(p: PlayerState) -> list:
    """Enumerate every EMPTY cell on the farmyard.

    Stables have no adjacency requirement, only "cell must be empty"
    (per RULES.md §Stables). Cost-affordability and stable-supply checks
    happen at the parent enumerator level, not here.
    """
    grid = p.farmyard.grid
    return [
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY
    ]


_RESOURCE_FIELDS = ("wood", "clay", "reed", "stone", "food", "grain", "veg")


def _can_afford(p: PlayerState, cost: Resources) -> bool:
    """True iff every component of the player's resources >= the corresponding cost component."""
    r = p.resources
    return all(getattr(r, f) >= getattr(cost, f) for f in _RESOURCE_FIELDS)


def _can_afford_room(p: PlayerState) -> bool:
    """Affordability check for one room only.

    Cost: 5 of the current house material + 2 reed (`ROOM_COSTS` in constants).

    Split out from `_can_build_room` so future card support can vary the
    affordability calc without touching placement geometry.
    """
    return _can_afford(p, ROOM_COSTS[p.house_material])


def _legal_room_cells(p: PlayerState) -> list:
    """Enumerate every (row, col) where a room can be placed.

    Empty, non-enclosed, orthogonally adjacent to an existing ROOM cell.
    Cells inside a pasture cannot have rooms built on them per RULES.md
    §House and Rooms.

    Naturally handles within-action adjacency chaining: a room just built
    counts as an existing ROOM for the next call.
    """
    grid = p.farmyard.grid
    enclosed = enclosed_cells(p.farmyard)
    room_cells = {
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    }
    empty_unenclosed = [
        (r, c)
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY
        and (r, c) not in enclosed
    ]
    adjacent_to_room = {
        (r + dr, c + dc)
        for (r, c) in room_cells
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]
    }
    return [cell for cell in empty_unenclosed if cell in adjacent_to_room]


def _has_room_placement(p: PlayerState) -> bool:
    """Placement geometry: an EMPTY non-enclosed cell adjacent to a ROOM exists.

    Cells inside a pasture cannot have rooms built on them per RULES.md
    §House and Rooms.
    """
    return bool(_legal_room_cells(p))


def _can_build_room(p: PlayerState) -> bool:
    """The player can afford one room AND has a valid placement cell."""
    return _can_afford_room(p) and _has_room_placement(p)


def _can_renovate(p: PlayerState) -> bool:
    """The house is wood or clay AND the player can afford to upgrade ALL rooms.

    Wood→Clay: 1 clay per room + 1 reed total.
    Clay→Stone: 1 stone per room + 1 reed total.
    """
    material = p.house_material
    if material == HouseMaterial.STONE:
        return False
    num_rooms = _num_rooms(p)
    res = p.resources
    if material == HouseMaterial.WOOD:
        return res.clay >= num_rooms and res.reed >= 1
    else:  # CLAY
        return res.stone >= num_rooms and res.reed >= 1


def _can_afford_major(state: GameState, p: PlayerState, idx: int) -> bool:
    """Whether the given player can afford the major improvement at index `idx`.

    The player's index is derived from `p` itself (by identity comparison
    against `state.players`), not from `state.current_player`.

    Cost table (from RULES.md):
      0: clay ≥ 2
      1: clay ≥ 3
      2: clay ≥ 4 OR owns Fireplace (idx 0 or 1)
      3: clay ≥ 5 OR owns Fireplace (idx 0 or 1)
      4: stone ≥ 3 AND wood ≥ 1
      5: clay  ≥ 3 AND stone ≥ 1
      6: clay  ≥ 1 AND stone ≥ 3
      7: wood  ≥ 2 AND stone ≥ 2
      8: clay  ≥ 2 AND stone ≥ 2
      9: reed  ≥ 2 AND stone ≥ 2
    """
    player_idx = 0 if p is state.players[0] else 1
    res = p.resources
    owns = state.board.major_improvement_owners
    owns_fireplace = owns[0] == player_idx or owns[1] == player_idx
    if idx == 0:
        return res.clay >= 2
    if idx == 1:
        return res.clay >= 3
    if idx == 2:
        return res.clay >= 4 or owns_fireplace
    if idx == 3:
        return res.clay >= 5 or owns_fireplace
    if idx == 4:
        return res.stone >= 3 and res.wood >= 1
    if idx == 5:
        return res.clay >= 3 and res.stone >= 1
    if idx == 6:
        return res.clay >= 1 and res.stone >= 3
    if idx == 7:
        return res.wood >= 2 and res.stone >= 2
    if idx == 8:
        return res.clay >= 2 and res.stone >= 2
    if idx == 9:
        return res.reed >= 2 and res.stone >= 2
    raise ValueError(f"Invalid major improvement index: {idx}")


def _can_afford_any_major_improvement(state: GameState, p: PlayerState) -> bool:
    """Whether at least one unowned major improvement is affordable."""
    owners = state.board.major_improvement_owners
    return any(
        owners[i] is None and _can_afford_major(state, p, i)
        for i in range(10)
    )


# ---------------------------------------------------------------------------
# Per-space predicates — atomic spaces
# ---------------------------------------------------------------------------

def _legal_day_laborer(state: GameState) -> bool:
    return _is_available(state, "day_laborer")


def _legal_fishing(state: GameState) -> bool:
    return (
        _is_available(state, "fishing")
        and get_space(state.board, "fishing").accumulated_amount > 0
    )


def _legal_forest(state: GameState) -> bool:
    return (
        _is_available(state, "forest")
        and bool(get_space(state.board, "forest").accumulated)
    )


def _legal_clay_pit(state: GameState) -> bool:
    return (
        _is_available(state, "clay_pit")
        and bool(get_space(state.board, "clay_pit").accumulated)
    )


def _legal_reed_bank(state: GameState) -> bool:
    return (
        _is_available(state, "reed_bank")
        and bool(get_space(state.board, "reed_bank").accumulated)
    )


def _legal_grain_seeds(state: GameState) -> bool:
    return _is_available(state, "grain_seeds")


def _legal_meeting_place(state: GameState) -> bool:
    # Legal even when accumulated food is 0 — taking the SP token is itself an effect.
    return _is_available(state, "meeting_place")


def _legal_western_quarry(state: GameState) -> bool:
    return (
        _is_available(state, "western_quarry")
        and bool(get_space(state.board, "western_quarry").accumulated)
    )


def _legal_vegetable_seeds(state: GameState) -> bool:
    return _is_available(state, "vegetable_seeds")


def _legal_eastern_quarry(state: GameState) -> bool:
    return (
        _is_available(state, "eastern_quarry")
        and bool(get_space(state.board, "eastern_quarry").accumulated)
    )


def _legal_basic_wish_for_children(state: GameState) -> bool:
    if not _is_available(state, "basic_wish_for_children"):
        return False
    p = state.players[state.current_player]
    return p.people_total < 5 and p.people_total < _num_rooms(p)


def _legal_urgent_wish_for_children(state: GameState) -> bool:
    if not _is_available(state, "urgent_wish_for_children"):
        return False
    p = state.players[state.current_player]
    return p.people_total < 5


# ---------------------------------------------------------------------------
# Per-space predicates — non-atomic spaces
# ---------------------------------------------------------------------------

def _legal_farm_expansion(state: GameState) -> bool:
    if not _is_available(state, "farm_expansion"):
        return False
    p = state.players[state.current_player]
    return _can_build_room(p) or _can_build_stable(p, Resources(wood=2))


def _legal_farmland(state: GameState) -> bool:
    if not _is_available(state, "farmland"):
        return False
    p = state.players[state.current_player]
    return _can_plow(p)


def _legal_side_job(state: GameState) -> bool:
    if not _is_available(state, "side_job"):
        return False
    p = state.players[state.current_player]
    can_stable = _can_build_stable(p, Resources(wood=1))
    can_bake = _can_bake_bread(state, p)
    return can_stable or can_bake


def _legal_grain_utilization(state: GameState) -> bool:
    if not _is_available(state, "grain_utilization"):
        return False
    p = state.players[state.current_player]
    return _can_sow(p) or _can_bake_bread(state, p)


def _legal_sheep_market(state: GameState) -> bool:
    return (
        _is_available(state, "sheep_market")
        and get_space(state.board, "sheep_market").accumulated_amount > 0
    )


def _legal_pig_market(state: GameState) -> bool:
    return (
        _is_available(state, "pig_market")
        and get_space(state.board, "pig_market").accumulated_amount > 0
    )


def _legal_cattle_market(state: GameState) -> bool:
    return (
        _is_available(state, "cattle_market")
        and get_space(state.board, "cattle_market").accumulated_amount > 0
    )


def _legal_major_improvement(state: GameState) -> bool:
    if not _is_available(state, "major_improvement"):
        return False
    p = state.players[state.current_player]
    return _can_afford_any_major_improvement(state, p)


def _legal_house_redevelopment(state: GameState) -> bool:
    if not _is_available(state, "house_redevelopment"):
        return False
    p = state.players[state.current_player]
    return _can_renovate(p)


def _legal_cultivation(state: GameState) -> bool:
    if not _is_available(state, "cultivation"):
        return False
    p = state.players[state.current_player]
    return _can_plow(p) or _can_sow(p)


def _legal_farm_redevelopment(state: GameState) -> bool:
    if not _is_available(state, "farm_redevelopment"):
        return False
    p = state.players[state.current_player]
    return _can_renovate(p)


def _legal_fencing(state: GameState) -> bool:
    """Placement legality for the Fencing action space.

    Requires: space available + ≥1 wood + ≥1 fence in supply + at least one
    legal pasture commit exists at the current state. The last check uses
    `_any_legal_pasture_commit`'s two-pass iteration (1×1 fast path, then
    larger shapes) over the active universe.
    """
    if not _is_available(state, "fencing"):
        return False
    p = state.players[state.current_player]
    if p.resources.wood < 1:
        return False
    if fences_in_supply(p.farmyard) < 1:
        return False
    return _any_legal_pasture_commit(state, p)


# ---------------------------------------------------------------------------
# Fence-action helpers
# ---------------------------------------------------------------------------

def _enclosable_cells_bm(farmyard) -> int:
    """Bitmap of cells that can legally be enclosed by fences (EMPTY or STABLE).

    Rooms and fields cannot be enclosed per RULES.md "Fences and Pastures".
    Starting-room cells (1, 0) and (2, 0) are ROOM type and therefore
    excluded automatically.
    """
    bm = 0
    for r in range(NUM_ROWS):
        for c in range(NUM_COLS):
            ct = farmyard.grid[r][c].cell_type
            if ct == CellType.EMPTY or ct == CellType.STABLE:
                bm |= 1 << (r * NUM_COLS + c)
    return bm


def _cells_bm_of_pasture(pasture) -> int:
    """Cell-set of a `Pasture` (from agricola.pasture) as a 15-bit bitmap."""
    bm = 0
    for (r, c) in pasture.cells:
        bm |= 1 << (r * NUM_COLS + c)
    return bm


def _check_entry_legal(
    entry: PastureCandidate,
    *,
    enclosable_bm: int,
    pasture_bms: tuple,
    existing_pasture_cells_bm: int,
    has_existing_pastures: bool,
    subdivision_started: bool,
    h_fences_bm: int,
    v_fences_bm: int,
    wood: int,
    fences_left: int,
    universe_set: frozenset,
) -> tuple[bool, int, int]:
    """Apply the unified pasture-commit legality chain (TASK_6 §4.5) to one
    universe entry against precomputed per-call state.

    Returns (is_legal, h_new_bm, v_new_bm). h_new/v_new are 0 if not legal.
    Both callers (`_any_legal_pasture_commit` and
    `_enumerate_pending_build_fences`) share this function.
    """
    bm = entry.cells_bm

    # 1. Enclosable cells only.
    if bm & ~enclosable_bm:
        return False, 0, 0

    # 2. Subdivision vs new-pasture: must be entirely within ONE existing
    #    pasture, or entirely in unenclosed area.
    is_subdivision = False
    parent_bm = 0
    if bm & existing_pasture_cells_bm:
        for P_bm in pasture_bms:
            if (bm & P_bm) == bm:
                is_subdivision = True
                parent_bm = P_bm
                break
        if not is_subdivision:
            return False, 0, 0                   # straddles multiple pastures

    # 2b. Builds-before-subdivisions ordering rule (TASK_6 §2.3).
    if (not is_subdivision) and subdivision_started:
        return False, 0, 0

    # 3. Adjacency: subdivision is fine (within); new-pasture must touch an
    #    existing pasture OR there are no existing pastures (first-pasture rule).
    if not is_subdivision and has_existing_pastures:
        if not (entry.adjacency_bm & existing_pasture_cells_bm):
            return False, 0, 0

    # 4. Affordability + supply + at-least-one-new-fence.
    h_new = entry.h_boundary_bm & ~h_fences_bm
    v_new = entry.v_boundary_bm & ~v_fences_bm
    new_count = h_new.bit_count() + v_new.bit_count()
    if new_count < 1:
        return False, 0, 0
    if new_count > wood:
        return False, 0, 0
    if new_count > fences_left:
        return False, 0, 0

    # 5. Subdivision canonicalization: if complement-within-parent is also a
    #    universe entry, emit only the lex-smaller-min-cell side.
    if is_subdivision:
        complement_bm = parent_bm & ~bm
        if complement_bm in universe_set:
            lo_self = (bm & -bm).bit_length()
            lo_comp = (complement_bm & -complement_bm).bit_length()
            if lo_comp < lo_self:
                return False, 0, 0

    return True, h_new, v_new


def _legal_pasture_commits_compute(farmyard, wood, subdivision_started):
    """The fence-universe scan, factored out of the two callers so a cache can
    front it. Returns a tuple of legal `PastureCandidate` entries in active-
    universe order. Shared by `_any_legal_pasture_commit` (length check) and
    `_enumerate_pending_build_fences` (one CommitBuildPasture per entry). Pure
    function of (farmyard, wood, subdivision_started) under the active universe.
    """
    entries = ACTIVE_FENCE_UNIVERSE_ENTRIES
    universe_set = ACTIVE_FENCE_UNIVERSE_SET
    enclosable_bm = _enclosable_cells_bm(farmyard)
    pasture_bms = tuple(_cells_bm_of_pasture(P) for P in farmyard.pastures)
    existing_pasture_cells_bm = 0
    for P_bm in pasture_bms:
        existing_pasture_cells_bm |= P_bm
    h_fences_bm = pack_fences_h(farmyard.horizontal_fences)
    v_fences_bm = pack_fences_v(farmyard.vertical_fences)
    fences_left = fences_in_supply(farmyard)
    has_existing_pastures = bool(pasture_bms)
    common = dict(
        enclosable_bm=enclosable_bm,
        pasture_bms=pasture_bms,
        existing_pasture_cells_bm=existing_pasture_cells_bm,
        has_existing_pastures=has_existing_pastures,
        subdivision_started=subdivision_started,
        h_fences_bm=h_fences_bm,
        v_fences_bm=v_fences_bm,
        wood=wood,
        fences_left=fences_left,
        universe_set=universe_set,
    )
    return tuple(
        entry for entry in entries
        if _check_entry_legal(entry, **common)[0]
    )


@functools.lru_cache(maxsize=50_000)
def _legal_pasture_commits_cached(farmyard, wood, subdivision_started):
    """Projection-keyed cache (S7 / FENCE_SCAN_CACHE) of the legal pasture-commit
    scan. Pure over (farmyard, wood, subdivision_started); see
    POSSIBLE_SPEEDUPS.md S7 and FRONTIER_OPT_DESIGN.md §7. Key changes (i.e.
    invalidation) on: plow, build-rooms, build-fences, any wood change.
    `active_universe(...)` clears this cache on entry/exit so it stays correct
    under universe swaps.
    """
    return _legal_pasture_commits_compute(farmyard, wood, subdivision_started)


def _any_legal_pasture_commit(
    state: GameState, p: PlayerState,
    *,
    entries: tuple | None     = None,
    smallest_entries: tuple | None = None,
    universe_set: frozenset | None = None,
) -> bool:
    """Return True iff at least one pasture commit is legal for `p` in `state`.

    Two-pass iteration: precomputed 1×1 fast-path first, then the rest of the
    universe (skipping 1×1's already checked). The fast path capitalizes on
    the property "if any commit is legal, some 1×1 commit is legal" (TASK_6
    Part 4.3); the (0, 0)-1×1 addition (Part 1.8) ensures every enclosable
    cell has a 1×1 candidate.

    `subdivision_started=False` is hardcoded because this helper answers a
    placement-time question (Fencing space availability) or a pre-entry
    question (Farm Redev's optional Build Fences offer) — no in-progress
    Build Fences action exists at either call site.

    Universe resolution: when any of `entries`, `smallest_entries`, or
    `universe_set` is None, the corresponding `ACTIVE_FENCE_UNIVERSE_*`
    module constant is read at call time. This lets `active_universe(...)`
    reassignments affect this call site without requiring an explicit kwarg.
    """
    if (opt_config.FENCE_SCAN_CACHE
            and entries is None and smallest_entries is None and universe_set is None):
        return bool(_legal_pasture_commits_cached(p.farmyard, p.resources.wood, False))

    if entries is None:
        entries = ACTIVE_FENCE_UNIVERSE_ENTRIES
    if smallest_entries is None:
        smallest_entries = ACTIVE_FENCE_UNIVERSE_SMALLEST_ENTRIES
    if universe_set is None:
        universe_set = ACTIVE_FENCE_UNIVERSE_SET
    farmyard = p.farmyard
    enclosable_bm = _enclosable_cells_bm(farmyard)
    pasture_bms = tuple(_cells_bm_of_pasture(P) for P in farmyard.pastures)
    existing_pasture_cells_bm = 0
    for P_bm in pasture_bms:
        existing_pasture_cells_bm |= P_bm
    h_fences_bm = pack_fences_h(farmyard.horizontal_fences)
    v_fences_bm = pack_fences_v(farmyard.vertical_fences)
    wood = p.resources.wood
    fences_left = fences_in_supply(farmyard)
    has_existing_pastures = bool(pasture_bms)

    common = dict(
        enclosable_bm=enclosable_bm,
        pasture_bms=pasture_bms,
        existing_pasture_cells_bm=existing_pasture_cells_bm,
        has_existing_pastures=has_existing_pastures,
        subdivision_started=False,
        h_fences_bm=h_fences_bm,
        v_fences_bm=v_fences_bm,
        wood=wood,
        fences_left=fences_left,
        universe_set=universe_set,
    )

    # Fast path: precomputed 1×1 tuple (~13 entries under RESTRICTED).
    for entry in smallest_entries:
        ok, _h, _v = _check_entry_legal(entry, **common)
        if ok:
            return True
    # Slow path: full universe minus 1×1's.
    for entry in entries:
        if entry.cells_bm.bit_count() == 1:
            continue
        ok, _h, _v = _check_entry_legal(entry, **common)
        if ok:
            return True
    return False


# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------

# Atomic spaces — single worker placement, no follow-up sub-decisions.
ATOMIC_LEGALITY: dict[str, Callable[[GameState], bool]] = {
    "day_laborer":               _legal_day_laborer,
    "fishing":                   _legal_fishing,
    "forest":                    _legal_forest,
    "clay_pit":                  _legal_clay_pit,
    "reed_bank":                 _legal_reed_bank,
    "grain_seeds":               _legal_grain_seeds,
    "meeting_place":             _legal_meeting_place,
    "western_quarry":            _legal_western_quarry,
    "vegetable_seeds":           _legal_vegetable_seeds,
    "eastern_quarry":            _legal_eastern_quarry,
    "basic_wish_for_children":   _legal_basic_wish_for_children,
    "urgent_wish_for_children":  _legal_urgent_wish_for_children,
}

# Non-atomic spaces. `lessons` is permanently illegal in the Family game
# and omitted. After TASK_6, both `fencing` and `farm_redevelopment` are
# implemented; every non-atomic space appears here.
NON_ATOMIC_LEGALITY: dict[str, Callable[[GameState], bool]] = {
    "farm_expansion":      _legal_farm_expansion,
    "farmland":            _legal_farmland,
    "side_job":            _legal_side_job,
    "grain_utilization":   _legal_grain_utilization,
    "sheep_market":        _legal_sheep_market,
    "pig_market":          _legal_pig_market,
    "cattle_market":       _legal_cattle_market,
    "major_improvement":   _legal_major_improvement,
    "house_redevelopment": _legal_house_redevelopment,
    "cultivation":         _legal_cultivation,
    "farm_redevelopment":  _legal_farm_redevelopment,
    "fencing":             _legal_fencing,
}

# Combined dispatch used by `legal_placements`.
ALL_LEGALITY: dict[str, Callable[[GameState], bool]] = {
    **ATOMIC_LEGALITY,
    **NON_ATOMIC_LEGALITY,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def legal_placements(state: GameState) -> list[PlaceWorker]:
    """Return all legal PlaceWorker actions across atomic and non-atomic spaces.

    Returns an empty list if the active player has no workers left to place.
    Excludes `lessons` (always illegal in the Family game); every other space
    in `ALL_LEGALITY` (including `fencing`) is surfaced when its predicate holds.

    Called by `legal_actions` when the pending stack is empty during WORK phase.
    """
    if state.players[state.current_player].people_home < 1:
        return []
    return [
        PlaceWorker(space=s)
        for s, predicate in ALL_LEGALITY.items()
        if predicate(state)
    ]


# ---------------------------------------------------------------------------
# Per-pending legality enumerators
# ---------------------------------------------------------------------------
#
# Each enumerator answers "what sub-actions are legal when this specific
# pending is on top of the stack?" — distinct from per-space placement
# legality (which answers "is PlaceWorker(space) legal at all?").
#
# Returned actions follow a deterministic order; per-enumerator ordering is
# documented at each function.


def _enumerate_pending_grain_utilization(
    state: GameState, pending: PendingGrainUtilization,
) -> list[Action]:
    """Enumerate legal actions at PendingGrainUtilization.

    Order: ChooseSubAction("bake_bread") first if legal, then
    ChooseSubAction("sow") if legal, then Stop() if legal (at least one
    sub-action completed).
    """
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.bake_chosen and _can_bake_bread(state, p):
        actions.append(ChooseSubAction(name="bake_bread"))
    if not pending.sow_chosen and _can_sow(p):
        actions.append(ChooseSubAction(name="sow"))
    if pending.sow_chosen or pending.bake_chosen:
        actions.append(Stop())
    return actions


def _enumerate_pending_sow(
    state: GameState, pending: PendingSow,
) -> list[Action]:
    """Enumerate legal (grain, veg) commits at PendingSow.

    Constraints:
      - grain + veg >= 1 (must sow at least one field)
      - grain <= p.resources.grain
      - veg <= p.resources.veg
      - grain + veg <= number of empty field cells

    Order: sorted by (grain, veg) ascending.
    """
    p = state.players[pending.player_idx]
    empty_fields = sum(
        1 for r in range(3) for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.FIELD
        and p.farmyard.grid[r][c].grain == 0
        and p.farmyard.grid[r][c].veg == 0
    )
    actions: list[Action] = []
    for g in range(p.resources.grain + 1):
        for v in range(p.resources.veg + 1):
            if g + v == 0:
                continue
            if g + v > empty_fields:
                continue
            actions.append(CommitSow(grain=g, veg=v))
    return actions


def _enumerate_pending_bake_bread(
    state: GameState, pending: PendingBakeBread,
) -> list[Action]:
    """Enumerate legal actions at PendingBakeBread.

    Includes eligible-and-unfired triggers as FireTrigger options, plus
    CommitBake options if the player can currently bake. No SkipTrigger —
    declining is implicit (player picks a commit or another trigger).

    Order: FireTrigger entries alphabetically by card_id, then CommitBake
    entries in ascending grain amount.
    """
    from agricola.cards.triggers import TRIGGERS  # local import to avoid load-order issues

    p = state.players[pending.player_idx]
    actions: list[Action] = []

    # Eligible unfired triggers for this pending's event.
    event = type(pending).TRIGGER_EVENT   # "before_bake_bread"
    eligible_entries = []
    for entry in TRIGGERS.get(event, []):
        if entry.card_id in pending.triggers_resolved:
            continue
        if not entry.eligibility_fn(
            state, pending.player_idx, pending.triggers_resolved,
        ):
            continue
        eligible_entries.append(entry)
    eligible_entries.sort(key=lambda e: e.card_id)
    for entry in eligible_entries:
        actions.append(FireTrigger(card_id=entry.card_id))

    # Commit options. The max grain that can be baked in this action is the
    # min of the player's supply and the sum of per-source caps (uncapped
    # sources, e.g. Fireplace/Hearth, lift the cap to player's grain supply).
    specs = baking_specs_for_player(state, pending.player_idx)
    if specs:
        finite_cap = sum(cap for (cap, _rate) in specs if cap is not None)
        uncapped_present = any(cap is None for (cap, _rate) in specs)
        max_grain = p.resources.grain if uncapped_present else min(p.resources.grain, finite_cap)
        for n in range(1, max_grain + 1):
            actions.append(CommitBake(grain=n))

    return actions


# ---------------------------------------------------------------------------
# Shared sub-action pending enumerators (Plow, BuildStable, BuildMajor, Renovate)
# ---------------------------------------------------------------------------

def _enumerate_pending_plow(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal CommitPlow actions at PendingPlow.

    One CommitPlow per legal target cell (empty, non-enclosed, adjacent to
    an existing field — or anywhere if there are no fields yet).
    """
    p = state.players[pending.player_idx]
    return [CommitPlow(row=r, col=c) for (r, c) in _legal_plow_cells(p)]


def _enumerate_pending_build_stables(
    state: GameState, pending: PendingBuildStables,
) -> list[Action]:
    """Enumerate legal actions at PendingBuildStables (multi-shot).

    Three constraints filter CommitBuildStable options independently:
      - Caller-imposed cap: max_builds is None or num_built < max_builds.
        Side Job's max_builds=1 saturates after the single commit;
        Farm Expansion's None never blocks here.
      - Buildability: _can_build_stable(p, cost) — combined supply +
        cell-availability + affordability check.
    Stop is legal once num_built >= 1 (the "must do at least one" rule).
    """
    actions: list[Action] = []
    p = state.players[pending.player_idx]

    cap_ok = pending.max_builds is None or pending.num_built < pending.max_builds
    if cap_ok and _can_build_stable(p, pending.cost):
        for (r, c) in _legal_stable_cells(p):
            actions.append(CommitBuildStable(row=r, col=c))

    if pending.num_built >= 1:
        actions.append(Stop())

    return actions


def _enumerate_pending_build_rooms(
    state: GameState, pending: PendingBuildRooms,
) -> list[Action]:
    """Enumerate legal actions at PendingBuildRooms (multi-shot).

    Same shape as _enumerate_pending_build_stables. Cell list comes from
    _legal_room_cells (empty, non-enclosed, adjacent to existing ROOM —
    naturally handles within-action adjacency chaining).
    """
    actions: list[Action] = []
    p = state.players[pending.player_idx]

    cap_ok = pending.max_builds is None or pending.num_built < pending.max_builds
    if cap_ok and _can_afford(p, pending.cost):
        for (r, c) in _legal_room_cells(p):
            actions.append(CommitBuildRoom(row=r, col=c))

    if pending.num_built >= 1:
        actions.append(Stop())

    return actions


def _enumerate_pending_build_major(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal CommitBuildMajor actions at PendingBuildMajor.

    If `build_chosen` is True, we're back here after an oven flow
    completed; only Stop is legal. Otherwise enumerate every unowned,
    affordable major as a CommitBuildMajor (standard payment), plus one
    additional CommitBuildMajor per Fireplace owned (Cooking Hearth via
    Fireplace return).
    """
    if pending.build_chosen:
        return [Stop()]
    owners = state.board.major_improvement_owners
    actions: list[Action] = []
    p = state.players[pending.player_idx]
    for idx in range(10):
        if owners[idx] is not None:
            continue
        # Standard-payment option requires the raw cost specifically. We can't
        # use `_can_afford_major` here because for Cooking Hearth (idx 2, 3)
        # that predicate also accepts the Fireplace-return alternative; using
        # it as a gate for the standard-payment option leaks unaffordable
        # standard-payment commits (the player ends with negative clay).
        # The Fireplace-return alternative is emitted separately below.
        if _can_afford(p, MAJOR_IMPROVEMENT_COSTS[idx]):
            actions.append(CommitBuildMajor(major_idx=idx, return_fireplace_idx=None))
        # Cooking Hearth via Fireplace return: emit one option per Fireplace owned.
        from agricola.constants import COOKING_HEARTH_INDICES, FIREPLACE_INDICES
        if idx in COOKING_HEARTH_INDICES:
            for fp_idx in FIREPLACE_INDICES:
                if owners[fp_idx] == pending.player_idx:
                    actions.append(CommitBuildMajor(
                        major_idx=idx, return_fireplace_idx=fp_idx,
                    ))
    return actions


def _enumerate_pending_renovate(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal CommitRenovate actions at PendingRenovate.

    Renovate has no per-action parameter — exactly one option.
    """
    return [CommitRenovate()]


# ---------------------------------------------------------------------------
# Parent pending enumerators (Farm Expansion, Farmland, Cultivation, Side Job,
# Markets, Major/Minor Improvement, Clay/Stone Oven wrappers, House Redevelopment)
# ---------------------------------------------------------------------------

def _enumerate_pending_farm_expansion(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal actions at PendingFarmExpansion.

    Once-per-category: build_rooms and build_stables each appear only if the
    corresponding *_chosen flag is False AND the player can actually do it.
    Stop is legal once at least one sub-action has been chosen (the
    "must do at least one when entering the action" rule).
    """
    actions: list[Action] = []
    p = state.players[pending.player_idx]
    if not pending.room_chosen and _can_build_room(p):
        actions.append(ChooseSubAction(name="build_rooms"))
    if not pending.stable_chosen and _can_build_stable(p, Resources(wood=2)):
        actions.append(ChooseSubAction(name="build_stables"))
    if pending.room_chosen or pending.stable_chosen:
        actions.append(Stop())
    return actions


def _enumerate_pending_farmland(
    state: GameState, pending,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.plow_chosen and _can_plow(p):
        actions.append(ChooseSubAction(name="plow"))
    if pending.plow_chosen:
        actions.append(Stop())
    return actions


def _enumerate_pending_cultivation(
    state: GameState, pending,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.plow_chosen and _can_plow(p):
        actions.append(ChooseSubAction(name="plow"))
    if not pending.sow_chosen and _can_sow(p):
        actions.append(ChooseSubAction(name="sow"))
    if pending.plow_chosen or pending.sow_chosen:
        actions.append(Stop())
    return actions


def _enumerate_pending_side_job(
    state: GameState, pending,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.stable_chosen:
        if _can_build_stable(p, Resources(wood=1)):
            actions.append(ChooseSubAction(name="build_stable"))
    if not pending.bake_chosen and _can_bake_bread(state, p):
        actions.append(ChooseSubAction(name="bake_bread"))
    if pending.stable_chosen or pending.bake_chosen:
        actions.append(Stop())
    return actions


def _enumerate_pending_animal_market(
    state: GameState, pending,
) -> list[Action]:
    """Shared enumerator for the three animal markets.

    Computes the Pareto frontier over (sheep, boar, cattle) configs the
    player can land on after taking the animals from the market, and
    emits one CommitAccommodate per frontier point. No Stop — the action
    is mandatory single-step (commit pops the parent directly).
    """
    from agricola.helpers import cooking_rates, pareto_frontier
    from agricola.pending import PendingCattleMarket, PendingPigMarket, PendingSheepMarket
    from agricola.resources import Animals

    p = state.players[pending.player_idx]
    # Animal markets don't convert veg; slice to the (sheep, boar, cattle) triple
    # that pareto_frontier expects.
    rates = cooking_rates(state, pending.player_idx)[:3]
    if isinstance(pending, PendingSheepMarket):
        gained = Animals(sheep=pending.gained)
    elif isinstance(pending, PendingPigMarket):
        gained = Animals(boar=pending.gained)
    elif isinstance(pending, PendingCattleMarket):
        gained = Animals(cattle=pending.gained)
    else:
        raise AssertionError(f"Unexpected animal market pending: {type(pending).__name__}")
    frontier = pareto_frontier(p, gained, rates)
    return [
        CommitAccommodate(sheep=a.sheep, boar=a.boar, cattle=a.cattle)
        for (a, _food) in frontier
    ]


def _enumerate_pending_major_minor_improvement(
    state: GameState, pending,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.major_chosen and _can_afford_any_major_improvement(state, p):
        actions.append(ChooseSubAction(name="build_major"))
    # Family scope: no play_minor path.
    if pending.major_chosen or pending.minor_chosen:
        actions.append(Stop())
    return actions


def _enumerate_pending_clay_oven(
    state: GameState, pending,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = [Stop()]
    if not pending.bake_chosen and _can_bake_bread(state, p):
        actions.append(ChooseSubAction(name="bake_bread"))
    return actions


def _enumerate_pending_stone_oven(
    state: GameState, pending,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = [Stop()]
    if not pending.bake_chosen and _can_bake_bread(state, p):
        actions.append(ChooseSubAction(name="bake_bread"))
    return actions


def _enumerate_pending_house_redevelopment(
    state: GameState, pending,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.renovate_chosen and _can_renovate(p):
        actions.append(ChooseSubAction(name="renovate"))
    if pending.renovate_chosen and not pending.improvement_chosen and _can_afford_any_major_improvement(state, p):
        actions.append(ChooseSubAction(name="improvement"))
    if pending.renovate_chosen:
        actions.append(Stop())
    return actions


def _enumerate_pending_fencing(
    state: GameState, pending: PendingFencing,
) -> list[Action]:
    """Enumerate legal actions at PendingFencing.

    The space has a single sub-action category (build_fences). Before that
    category has been entered, only ChooseSubAction("build_fences") is legal.
    After entering and committing through PendingBuildFences (which has its
    own Stop), control returns to PendingFencing where only Stop is legal.
    """
    actions: list[Action] = []
    if not pending.build_fences_chosen:
        actions.append(ChooseSubAction(name="build_fences"))
    else:
        actions.append(Stop())
    # Future: eligible card triggers at `before_fencing` would be appended here.
    return actions


def _enumerate_pending_build_fences(
    state: GameState,
    pending: PendingBuildFences,
    *,
    entries: tuple | None     = None,
    universe_set: frozenset | None = None,
) -> list[Action]:
    """Enumerate legal CommitBuildPasture + Stop actions at PendingBuildFences.

    Implements the unified pasture-commit legality chain (TASK_6 §4.5) via
    `_check_entry_legal`. Walks every entry in `entries` and emits one
    CommitBuildPasture per legal entry. Stop is appended once at least one
    pasture has been committed.

    Universe resolution: when `entries` or `universe_set` is None, the
    corresponding `ACTIVE_FENCE_UNIVERSE_*` module constant is read at call
    time. This lets `active_universe(...)` reassignments affect this call
    site without requiring an explicit kwarg.
    """
    if opt_config.FENCE_SCAN_CACHE and entries is None and universe_set is None:
        p = state.players[pending.player_idx]
        legal = _legal_pasture_commits_cached(
            p.farmyard, p.resources.wood, pending.subdivision_started,
        )
        actions: list[Action] = [CommitBuildPasture(cells=e.cells) for e in legal]
        if pending.pastures_built >= 1:
            actions.append(Stop())
        return actions

    if entries is None:
        entries = ACTIVE_FENCE_UNIVERSE_ENTRIES
    if universe_set is None:
        universe_set = ACTIVE_FENCE_UNIVERSE_SET
    p = state.players[pending.player_idx]
    farmyard = p.farmyard

    enclosable_bm = _enclosable_cells_bm(farmyard)
    pasture_bms = tuple(_cells_bm_of_pasture(P) for P in farmyard.pastures)
    existing_pasture_cells_bm = 0
    for P_bm in pasture_bms:
        existing_pasture_cells_bm |= P_bm
    h_fences_bm = pack_fences_h(farmyard.horizontal_fences)
    v_fences_bm = pack_fences_v(farmyard.vertical_fences)
    wood = p.resources.wood
    fences_left = fences_in_supply(farmyard)
    has_existing_pastures = bool(pasture_bms)

    common = dict(
        enclosable_bm=enclosable_bm,
        pasture_bms=pasture_bms,
        existing_pasture_cells_bm=existing_pasture_cells_bm,
        has_existing_pastures=has_existing_pastures,
        subdivision_started=pending.subdivision_started,
        h_fences_bm=h_fences_bm,
        v_fences_bm=v_fences_bm,
        wood=wood,
        fences_left=fences_left,
        universe_set=universe_set,
    )

    actions: list[Action] = []
    for entry in entries:
        ok, _h, _v = _check_entry_legal(entry, **common)
        if ok:
            actions.append(CommitBuildPasture(cells=entry.cells))

    if pending.pastures_built >= 1:
        actions.append(Stop())

    # Future: eligible card triggers at `before_build_fences` would be appended here.
    return actions


def _enumerate_pending_farm_redevelopment(
    state: GameState, pending: PendingFarmRedevelopment,
) -> list[Action]:
    """Enumerate legal actions at PendingFarmRedevelopment.

    Mirrors `_enumerate_pending_house_redevelopment` with the optional second
    step swapped from "improvement" to "build_fences". Renovate is mandatory
    first (Stop illegal until renovate_chosen); Build Fences is offered only
    after renovate AND only when at least one legal pasture commit exists.
    """
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.renovate_chosen and _can_renovate(p):
        actions.append(ChooseSubAction(name="renovate"))
    if (pending.renovate_chosen
            and not pending.build_fences_chosen
            and _any_legal_pasture_commit(state, p)):
        actions.append(ChooseSubAction(name="build_fences"))
    if pending.renovate_chosen:
        actions.append(Stop())
    return actions


def _enumerate_pending_harvest_feed(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal actions at PendingHarvestFeed.

    Two regimes based on the pending's state:

    1. `conversion_done == False`: offer each undecided owned conversion as
       use=True/False (use=True only if affordable), AND all Pareto-frontier
       CommitConvert points from harvest_feed_frontier.
    2. `conversion_done == True`: only Stop is legal.

    No ordering between crafts and the main convert: the agent can fire
    crafts in any order before committing convert, or commit convert
    immediately (forfeiting any undecided crafts — strategically equivalent
    to explicitly skipping each one).

    `food_owed` is derived on each call from the live player state:
        need      = 2*people_total - newborns
        food_owed = max(0, need - p.resources.food)
    Not cached on the pending — see CLAUDE.md Foundations (Derived data,
    not cached data). Recomputing here means any food the player
    spent/gained earlier in the feed phase (via crafts today, or food-side
    card effects in the future) is reflected immediately.

    The conversion frontier is always non-empty (food_owed == 0 yields the
    trivial (0,0,0,0,0)-consumed config; food_owed > 0 always has the
    consume-nothing + beg-everything entry).
    """
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
    from agricola.helpers import cooking_rates, harvest_feed_frontier

    actions: list[Action] = []
    p = state.players[pending.player_idx]

    if pending.conversion_done:
        actions.append(Stop())
        return actions

    # 1. Undecided owned conversions.
    for conversion_id, spec in HARVEST_CONVERSIONS.items():
        if conversion_id in p.harvest_conversions_used:
            continue
        if not spec.is_owned_fn(state, pending.player_idx):
            continue
        # use=False is always available (record-skip).
        actions.append(CommitHarvestConversion(conversion_id=conversion_id, use=False))
        # use=True only if affordable.
        if _can_afford(p, spec.input_cost):
            actions.append(CommitHarvestConversion(conversion_id=conversion_id, use=True))

    # 2. All Pareto-frontier CommitConvert points. Invert REMAINING tuples
    #    to CONSUMED amounts (consumed = player_max - remaining).
    rates = cooking_rates(state, pending.player_idx)  # 4-tuple
    need       = 2 * p.people_total - p.newborns
    food_owed  = max(0, need - p.resources.food)
    grain_pre  = p.resources.grain
    veg_pre    = p.resources.veg
    sheep_pre  = p.animals.sheep
    boar_pre   = p.animals.boar
    cattle_pre = p.animals.cattle
    for ((g_rem, v_rem, s_rem, b_rem, c_rem), _begging) in harvest_feed_frontier(
        p, food_owed, rates,
    ):
        actions.append(CommitConvert(
            grain  = grain_pre  - g_rem,
            veg    = veg_pre    - v_rem,
            sheep  = sheep_pre  - s_rem,
            boar   = boar_pre   - b_rem,
            cattle = cattle_pre - c_rem,
        ))

    return actions


def _enumerate_pending_harvest_breed(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal actions at PendingHarvestBreed.

    Before `breed_chosen`: one CommitBreed per Pareto-frontier point from
    breeding_frontier (frontier always non-empty — includes at minimum the
    do-nothing config). After `breed_chosen`: only Stop.
    """
    from agricola.helpers import breeding_frontier, cooking_rates

    actions: list[Action] = []
    p = state.players[pending.player_idx]

    if pending.breed_chosen:
        actions.append(Stop())
        return actions

    rates_3 = cooking_rates(state, pending.player_idx)[:3]
    for (cfg, _food) in breeding_frontier(p, rates_3):
        actions.append(CommitBreed(sheep=cfg.sheep, boar=cfg.boar, cattle=cfg.cattle))

    return actions


def _enumerate_pending_reveal(
    state: GameState, pending: PendingReveal,
) -> list[Action]:
    """Nature's candidate reveals at PendingReveal.

    The unrevealed cards of the stage the round being entered belongs to.
    `state.round_number` is the round just completed (§4.5), so the reveal turns
    up the next round's card — the candidate stage is `stage_of_round(round + 1)`.
    Uniform over candidates; for the k=1 stages this yields a single RevealCard
    (the trivial chance node). Derived purely from public state — STAGE_CARDS
    minus the already-revealed cards; the env's true card is always one of these.
    """
    stage = stage_of_round(state.round_number + 1)
    return [
        RevealCard(c)
        for c in STAGE_CARDS[stage]
        if not get_space(state.board, c).revealed
    ]


# Dispatch table for per-pending enumerators. New pending types register here.
from agricola.pending import (
    PendingCattleMarket,
    PendingClayOven,
    PendingCultivation,
    PendingFarmland,
    PendingHarvestBreed,
    PendingHarvestFeed,
    PendingHouseRedevelopment,
    PendingMajorMinorImprovement,
    PendingPigMarket,
    PendingSheepMarket,
    PendingSideJob,
    PendingStoneOven,
)
from agricola.actions import CommitAccommodate
PENDING_ENUMERATORS: dict[type, Callable] = {
    PendingGrainUtilization:    _enumerate_pending_grain_utilization,
    PendingSow:                 _enumerate_pending_sow,
    PendingBakeBread:           _enumerate_pending_bake_bread,
    PendingPlow:                _enumerate_pending_plow,
    PendingBuildStables:        _enumerate_pending_build_stables,
    PendingBuildRooms:          _enumerate_pending_build_rooms,
    PendingBuildMajor:          _enumerate_pending_build_major,
    PendingRenovate:            _enumerate_pending_renovate,
    PendingFarmExpansion:       _enumerate_pending_farm_expansion,
    PendingFarmland:            _enumerate_pending_farmland,
    PendingCultivation:         _enumerate_pending_cultivation,
    PendingSideJob:             _enumerate_pending_side_job,
    PendingSheepMarket:         _enumerate_pending_animal_market,
    PendingPigMarket:           _enumerate_pending_animal_market,
    PendingCattleMarket:        _enumerate_pending_animal_market,
    PendingMajorMinorImprovement: _enumerate_pending_major_minor_improvement,
    PendingClayOven:            _enumerate_pending_clay_oven,
    PendingStoneOven:           _enumerate_pending_stone_oven,
    PendingHouseRedevelopment:  _enumerate_pending_house_redevelopment,
    PendingFencing:             _enumerate_pending_fencing,
    PendingBuildFences:         _enumerate_pending_build_fences,
    PendingFarmRedevelopment:   _enumerate_pending_farm_redevelopment,
    PendingHarvestFeed:         _enumerate_pending_harvest_feed,
    PendingHarvestBreed:        _enumerate_pending_harvest_breed,
    PendingReveal:              _enumerate_pending_reveal,
}


def _enumerate_pending(state: GameState, top: PendingDecision) -> list[Action]:
    """Dispatch to the per-pending enumerator for `top`."""
    enumerator = PENDING_ENUMERATORS.get(type(top))
    if enumerator is None:
        raise AssertionError(
            f"No enumerator registered for pending type {type(top).__name__}"
        )
    return enumerator(state, top)


# ---------------------------------------------------------------------------
# Top-level legality entry point
# ---------------------------------------------------------------------------

# Thread-local cache stack for `legal_actions(state)` memoization. Empty (or
# missing `stack` attribute) means no cache is active and every call hits the
# full enumeration path. The `legal_actions_cache()` context manager pushes a
# fresh dict for the duration of a search and pops on exit. Stacking lets
# nested searches each have their own scoped cache without leaking entries.
#
# Design notes (PROFILING.md R1):
#   - The cache is opt-in via the context manager — random play / tests /
#     profiling do NOT pay any lookup cost. The only overhead in the absence
#     of an active cache is one `getattr` + truthiness check at the top of
#     `legal_actions`, which is essentially free.
#   - The cache keys on `id(state)`, NOT on the state's content hash.
#     Measured cost: `hash(GameState)` is ~26 us — recursively hashing the
#     full state dominates any savings from caching enumeration (~30 us);
#     content-based caching only buys ~2x. Identity-based `id(state)` lookup
#     is ~70 ns — ~370x faster on cache hit. MCTS is the intended consumer,
#     and a TreeNode holds a reference to its state object, so the same
#     state OBJECT is queried many times during selection. That's exactly
#     the identity-cache shape.
#   - A consequence: the cache stores the state object alongside the result
#     (`cache[id(state)] = (state, result)`) to prevent Python from
#     recycling the id while a cache entry still references it. Without
#     this, a state could be garbage-collected and its id reused by an
#     unrelated state with a different result — silent corruption.
#   - Transposition tables (different action paths arriving at identical
#     state content sharing statistics) need content-based hashing, NOT
#     this cache. That's a separate, slower layer for a future MCTS
#     enhancement. See PROFILING.md for the framing.
#   - The returned list is cached by reference, NOT defensively copied.
#     Callers must not mutate `legal_actions(state)` output (this was
#     already the convention; the cache makes it load-bearing).
_cache_tls = threading.local()


@contextlib.contextmanager
def legal_actions_cache():
    """Enable in-search memoization of `legal_actions(state)`.

    Returns a context manager that pushes a fresh per-search cache onto a
    thread-local stack. While the context is active, calls to
    `legal_actions(state)` hit the cache on repeat queries (keyed on
    `id(state)`); on exit the cache is dropped and subsequent calls are
    uncached again.

    Intended for MCTS (and any other consumer that revisits the same state
    object). TreeNode-style search where each node holds a reference to its
    state benefits directly. For transposition-table use (different paths
    → same state content) a separate content-keyed layer is needed; this
    cache is identity-based.

        with legal_actions_cache() as cache:
            ...  # run a search; legal_actions(state) is memoized
            print(f"cache size at end of search: {len(cache)}")

    Nests cleanly — inner `with` blocks get their own cache that doesn't
    leak entries to the outer scope. Random play / profiling / tests that
    never enter the context pay zero cost.
    """
    stack = getattr(_cache_tls, "stack", None)
    if stack is None:
        stack = []
        _cache_tls.stack = stack
    cache: dict = {}
    stack.append(cache)
    try:
        yield cache
    finally:
        stack.pop()


def legal_actions(state: GameState) -> list[Action]:
    """Return all currently-legal actions, given pending and phase state.

    Dispatches:
      - Pending stack non-empty → enumerate sub-actions at the top pending.
      - Phase == BEFORE_SCORING → return [] (game over, no actions).
      - Phase == WORK with empty stack → return legal_placements(state).

    Other phases (RETURN_HOME, PREPARATION, HARVEST_*) do not surface to
    the agent in Task 5 because no triggers push pendings during them.

    Memoization: when called inside a `with legal_actions_cache():` block,
    repeated calls on the SAME state object return the cached list (by
    reference). Identity-based — see the module-level comment and
    PROFILING.md R1 for the rationale. Outside the context manager, this
    function is uncached.
    """
    # Fast cache path (opt-in via legal_actions_cache()).
    stack = getattr(_cache_tls, "stack", None)
    if stack:
        cache = stack[-1]
        sid = id(state)
        entry = cache.get(sid)
        if entry is not None:
            # entry is (state_ref, result); state_ref pins the object so its
            # id can't be recycled while this cache entry is live.
            return entry[1]
        result = _legal_actions_uncached(state)
        cache[sid] = (state, result)
        return result
    return _legal_actions_uncached(state)


def _legal_actions_uncached(state: GameState) -> list[Action]:
    """The actual dispatch — see `legal_actions` for the public contract."""
    if state.pending_stack:
        return _enumerate_pending(state, state.pending_stack[-1])
    if state.phase == Phase.BEFORE_SCORING:
        return []
    if state.phase == Phase.WORK:
        return legal_placements(state)
    raise AssertionError(
        f"legal_actions called in unexpected state: phase={state.phase}, "
        f"stack={state.pending_stack}"
    )
