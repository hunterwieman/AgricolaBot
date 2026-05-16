from __future__ import annotations

from typing import Callable

from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitBake,
    CommitBuildMajor,
    CommitBuildRoom,
    CommitBuildStable,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.constants import (
    BAKING_IMPROVEMENT_SPECS,
    BAKING_IMPROVEMENTS,
    CellType,
    HouseMaterial,
    Phase,
    ROOM_COSTS,
)
from agricola.resources import Resources
from agricola.helpers import enclosed_cells, stables_in_supply
from agricola.pending import (
    PendingBakeBread,
    PendingBuildMajor,
    PendingBuildRooms,
    PendingBuildStables,
    PendingDecision,
    PendingFarmExpansion,
    PendingGrainUtilization,
    PendingPlow,
    PendingRenovate,
    PendingSow,
)
from agricola.state import GameState, PlayerState


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
    sp = state.board.action_spaces[space]
    unoccupied = sp.workers == (0, 0)
    revealed = sp.round_revealed <= state.round_number
    return unoccupied and revealed


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
        and state.board.action_spaces["fishing"].accumulated_amount > 0
    )


def _legal_forest(state: GameState) -> bool:
    return (
        _is_available(state, "forest")
        and bool(state.board.action_spaces["forest"].accumulated)
    )


def _legal_clay_pit(state: GameState) -> bool:
    return (
        _is_available(state, "clay_pit")
        and bool(state.board.action_spaces["clay_pit"].accumulated)
    )


def _legal_reed_bank(state: GameState) -> bool:
    return (
        _is_available(state, "reed_bank")
        and bool(state.board.action_spaces["reed_bank"].accumulated)
    )


def _legal_grain_seeds(state: GameState) -> bool:
    return _is_available(state, "grain_seeds")


def _legal_meeting_place(state: GameState) -> bool:
    # Legal even when accumulated food is 0 — taking the SP token is itself an effect.
    return _is_available(state, "meeting_place")


def _legal_western_quarry(state: GameState) -> bool:
    return (
        _is_available(state, "western_quarry")
        and bool(state.board.action_spaces["western_quarry"].accumulated)
    )


def _legal_vegetable_seeds(state: GameState) -> bool:
    return _is_available(state, "vegetable_seeds")


def _legal_eastern_quarry(state: GameState) -> bool:
    return (
        _is_available(state, "eastern_quarry")
        and bool(state.board.action_spaces["eastern_quarry"].accumulated)
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
        and state.board.action_spaces["sheep_market"].accumulated_amount > 0
    )


def _legal_pig_market(state: GameState) -> bool:
    return (
        _is_available(state, "pig_market")
        and state.board.action_spaces["pig_market"].accumulated_amount > 0
    )


def _legal_cattle_market(state: GameState) -> bool:
    return (
        _is_available(state, "cattle_market")
        and state.board.action_spaces["cattle_market"].accumulated_amount > 0
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

# Non-atomic spaces covered by this task. `fencing` is deferred (requires fence
# enumeration); `lessons` is permanently illegal in the Family game and omitted.
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
    Excludes `fencing` (deferred — requires fence enumeration) and `lessons`
    (always illegal in the Family game).

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
        if _can_afford_major(state, p, idx):
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
    rates = cooking_rates(state, pending.player_idx)
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


# Dispatch table for per-pending enumerators. New pending types register here.
from agricola.pending import (
    PendingCattleMarket,
    PendingClayOven,
    PendingCultivation,
    PendingFarmland,
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

def legal_actions(state: GameState) -> list[Action]:
    """Return all currently-legal actions, given pending and phase state.

    Dispatches:
      - Pending stack non-empty → enumerate sub-actions at the top pending.
      - Phase == BEFORE_SCORING → return [] (game over, no actions).
      - Phase == WORK with empty stack → return legal_placements(state).

    Other phases (RETURN_HOME, PREPARATION, HARVEST_*) do not surface to
    the agent in Task 5 because no triggers push pendings during them.
    """
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
