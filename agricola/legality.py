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
    CommitDraftPick,
    CommitFamilyGrowth,
    CommitFieldTake,
    CommitFoodPayment,
    CommitCardChoice,
    CommitHarvestConversion,
    CommitPlayMinor,
    CommitPlayOccupation,
    CommitPlow,
    CommitChooseCost,
    CommitRenovate,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Proceed,
    RevealCard,
    Stop,
)
from agricola.constants import (
    BAKING_IMPROVEMENT_SPECS,
    BAKING_IMPROVEMENTS,
    CellType,
    GameMode,
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
    compute_new_fence_edges,
    pack_fences_h,
    pack_fences_v,
)
from agricola.cost import CostCtx
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.helpers import (
    buildable_fences, cooking_rates, enclosed_cells, fences_built, food_payment_frontier,
    stables_in_supply,
)
from agricola.pending import (
    ACTION_SPACE_PENDING_IDS,
    PendingActionSpace,
    PendingBakeBread,
    PendingBasicWishForChildren,
    PendingBuildFences,
    PendingBuildMajor,
    PendingBuildRooms,
    PendingBuildStables,
    PendingDecision,
    PendingDraftPick,
    PendingFamilyGrowth,
    PendingFarmExpansion,
    PendingFieldPhase,
    FenceRestrictions,
    PendingFarmRedevelopment,
    PendingGrantedBuildFences,
    PendingFoodPayment,
    PendingGrainUtilization,
    PendingHarvestOccasion,
    PendingHarvestWindow,
    PendingMeetingPlace,
    PendingCardChoice,
    PendingPlayMinor,
    PendingPlayOccupation,
    PendingPlow,
    PendingPreparation,
    PendingChooseCost,
    PendingRenovate,
    PendingReveal,
    PendingSow,
    PendingSubActionSpace,
)
from agricola.state import Cell, GameState, PlayerState, get_space


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


# Cards may let the CURRENT player place a worker on an OCCUPIED space (normally
# illegal). Each override is `(state, space_id) -> bool`, consulted by
# `_is_available` ONLY on the occupied branch — so the common unoccupied path,
# and the entire Family game (empty registry), pay nothing. An override
# self-gates on its own card's ownership, the space id, and the precise
# occupancy shape it relaxes. Sleeping Corner is the first: use a "Wish for
# Children" space occupied by exactly one OTHER player (counting PLAYERS with a
# worker there, not workers — a normally-used wish space already holds the
# parent + newborn). See CARD_AUTHORING_GUIDE.md.
OCCUPANCY_OVERRIDE_EXTENSIONS: list[Callable] = []


def register_occupancy_override(fn: Callable) -> None:
    """Add a card-supplied predicate that may permit placing on an OCCUPIED space."""
    OCCUPANCY_OVERRIDE_EXTENSIONS.append(fn)


# Card-supplied renovate-TARGET extensions. Renovation normally goes one tier
# (WOOD→CLAY, CLAY→STONE); a card may make further targets legal — Conservator lets a
# wood house renovate directly to STONE. Each fn takes (state, player_idx,
# current_material) -> list[HouseMaterial] (extra legal targets) and self-gates on its
# own ownership. Consumed by `_legal_renovate_targets`. (The cost of each target then
# flows through the cost-modifier chokepoint as usual.) See COST_MODIFIER_DESIGN.md.
RENOVATE_TARGET_EXTENSIONS: list[Callable] = []


def register_renovate_target_extension(fn: Callable) -> None:
    """Add a card-supplied fn that may add legal renovate targets."""
    RENOVATE_TARGET_EXTENSIONS.append(fn)


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
    """Cross-cutting check: the current player may place a worker here — the
    space is revealed and either unoccupied, or a card grants an occupancy
    exemption for it. The occupancy-override registry is consulted ONLY on the
    occupied branch, so the common unoccupied path (and the entire Family game)
    pay nothing."""
    sp = get_space(state.board, space)
    if not sp.revealed:
        return False
    if sp.workers == (0, 0):
        return True
    for override in OCCUPANCY_OVERRIDE_EXTENSIONS:
        if override(state, space):
            return True
    return False


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
    """At least one empty field cell exists AND ≥1 grain or veg in supply —
    or a card-field sow is possible (an owned card-field with an empty stack
    and a matching sowable good in supply; rulings 45-48, 2026-07-12). The
    card check is inert in Family states (no card-fields owned)."""
    from agricola.cards.card_fields import (   # local import: load-order safe
        can_sow_card_fields,
    )

    grid = p.farmyard.grid
    has_empty_field = any(
        grid[r][c].cell_type == CellType.FIELD
        and grid[r][c].grain == 0
        and grid[r][c].veg == 0
        for r in range(3) for c in range(5)
    )
    has_seed = p.resources.grain >= 1 or p.resources.veg >= 1
    return (has_empty_field and has_seed) or can_sow_card_fields(p)


def _can_plow(p: PlayerState) -> bool:
    """At least one valid plow target exists.

    A plow target must be EMPTY AND non-enclosed (cells inside a pasture cannot
    be converted to fields per RULES.md §Fields and Crops).

    First field: any EMPTY non-enclosed cell.
    Subsequent fields: additionally orthogonally adjacent to an existing FIELD.
    """
    return bool(_legal_plow_cells(p))


def _build_stable_ctx(p: PlayerState, base_cost: Resources, build_index: int = 0) -> CostCtx:
    """Cost-resolution context for building ONE stable. Unlike rooms, the base (printed)
    cost is caller-supplied (`base_cost`) — Side Job 1 wood, Farm Expansion 2 wood, card
    grants 0 — not derivable from player state, so it stays on `PendingBuildStables.cost`
    and is passed in here. `build_index` (the running `num_built`) lets a cost card discount
    the Nth stable (Carpenter's Apprentice)."""
    return CostCtx(
        "build_stable", base_cost, num_rooms=_num_rooms(p), build_index=build_index,
    )


def _build_fence_ctx(
    p: PlayerState, wood_cost: int, *,
    build_index: int = 0, space_id: str | None = None,
) -> CostCtx:
    """Cost-resolution context for a fence wood bill of `wood_cost` edges. Unlike
    rooms/stables, the base is geometry-derived: each new fence edge is 1 wood, so the base
    is `Resources(wood=wood_cost)`. `build_index` is the running pasture count within this
    multi-shot Build Fences action and `space_id` the action's entry point (Fencing /
    Farm Redevelopment) — discriminators future per-segment / per-entry-point fence cards
    will read; no cost card reads them in the Family game, so `effective_payments`/`can_pay`
    reduce to "can afford `wood_cost` wood" (byte-identical to the old raw `new_count > wood`
    check).

    `wood_cost` is always a WHOLE-ACTION RUNNING TOTAL, never one pasture's edges in isolation
    (COST_MODIFIER_DESIGN.md §9.2): the during-building affordability check passes the running
    paid-edge total `accrued_cost.wood + this_pasture_paid` and the Proceed settle passes the
    final `accrued_cost.wood`. This is what makes a PER-ACTION-CAPPED conversion (Millwright's
    "up to 2 grain per action") correct — its 2-grain budget is counted ONCE against the whole
    action, not re-granted per pasture, so a wood-tight build that grain funds is enabled during
    building and pays with grain at settle, with no during-building / settle divergence."""
    return CostCtx(
        "build_fence", Resources(wood=wood_cost),
        build_index=build_index, space_id=space_id,
    )


def _can_build_stable(state: GameState, p: PlayerState, cost: Resources) -> bool:
    """Combined legality check for one stable build at the given base cost.

    Empty cell exists + ≥1 stable in supply + the cost is payable through the cost-modifier
    chokepoint (`can_pay`). In the Family game `can_pay` reduces to "can afford `cost`";
    with cost cards it also accepts a reduced / converted payment. Parameterized on cost:
    Farm Expansion uses 2 wood; Side Job uses 1 wood; card grants inject their own.
    """
    idx = 0 if p is state.players[0] else 1
    return (
        stables_in_supply(p) >= 1
        and bool(_legal_stable_cells(p))
        and can_pay(state, idx, _build_stable_ctx(p, cost))
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


def safe_plow_cells(p: PlayerState) -> list:
    """The legal plow cells that leave a base plow STILL legal after they are plowed.

    A granted "plow 1 additional field" before-trigger on Farmland precedes the
    mandatory (non-declinable) base plow, so the granted plow must not consume the last
    cell the base plow needs. Two uses (CARD_AUTHORING_GUIDE.md): the granted plow's cell
    choice is restricted to this set (via `PendingPlow.must_preserve_base`), and
    `_can_plow_twice` is the existence check over it (the eligibility gate that never
    offers the grant when this set is empty).

    Plowing is adjacency-constrained (a second field must touch an existing one) AND
    plowing the first field can OPEN new adjacent targets, so this is a per-cell
    simulation, not a count (e.g. with no field yet, two non-adjacent empty cells do NOT
    allow a second plow). Plowing only converts an EMPTY, non-enclosed cell to FIELD, so
    it never changes enclosure — only the field set the second plow's adjacency reads."""
    grid = p.farmyard.grid
    out = []
    for (r, c) in _legal_plow_cells(p):
        new_row = tuple(Cell(cell_type=CellType.FIELD) if cc == c else grid[r][cc]
                        for cc in range(len(grid[r])))
        new_grid = tuple(new_row if rr == r else grid[rr] for rr in range(len(grid)))
        p2 = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=new_grid))
        if _legal_plow_cells(p2):
            out.append((r, c))
    return out


def _can_plow_twice(p: PlayerState) -> bool:
    """True iff the player can legally plow two fields in sequence — the existence check
    over `safe_plow_cells` (see it for the rationale and the simulation)."""
    return bool(safe_plow_cells(p))


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


def _liquidatable_to(
    state: GameState, idx: int, p: PlayerState, cost: Resources,
    reserved_animals: Animals = Animals(),
) -> bool:
    """True iff `cost` (a resource payment) is affordable when the food component may be
    raised mid-turn by converting crops/animals to food (FOOD_PAYMENT_DESIGN.md §4).

    The non-food components must be on hand outright (liquidation only ever *produces*
    food). The animal portion of the surrounding cost — `reserved_animals` — is set aside
    before counting animals as conversion fuel, so liquidation never spends an animal the
    cost itself needs. The max-producible-food math here MUST agree with
    `food_payment_frontier`'s feasibility (same rates over the same goods) so a card the
    gate marks playable always yields a non-empty payment frontier at execution."""
    if not _can_afford(p, fast_replace(cost, food=0)):       # non-food must be on hand
        return False
    if not _can_afford_minor_animals(p, reserved_animals):
        return False
    owe = cost.food - p.resources.food
    if owe <= 0:
        return True
    rem = p.resources - fast_replace(cost, food=0)            # food untouched; non-food reserved
    sR, bR, cR, vR = cooking_rates(state, idx)
    max_food = (
        rem.grain + rem.veg * vR
        + (p.animals.sheep  - reserved_animals.sheep)  * sR
        + (p.animals.boar   - reserved_animals.boar)   * bR
        + (p.animals.cattle - reserved_animals.cattle) * cR
    )
    return max_food >= owe


def _payable(
    state: GameState, idx: int, p: PlayerState, cost: Resources,
    reserved_animals: Animals = Animals(),
) -> bool:
    """A resource payment is affordable now, possibly by liquidating crops/animals to
    cover its food component. A `food == 0` cost takes the plain `_can_afford` fast path
    (every Family build cost) and never touches the liquidation frontier — the perf/clarity
    guard of FOOD_PAYMENT_DESIGN.md §4; only a food-bearing card cost consults liquidation."""
    return _can_afford(p, cost) or (
        cost.food > 0 and _liquidatable_to(state, idx, p, cost, reserved_animals)
    )


def _payable_occupation(state: GameState, idx: int, p: PlayerState, cost: Resources) -> bool:
    """Can `idx` pay an occupation play cost — directly, via liquidation, OR by first firing
    an owned occupation-cost FOOD SOURCE (Paper Maker: 1 wood -> N food)?

    This is the affordability GATE for offering an occupation play (Lessons / Scholar). A
    source is simulated by spending its inputs and adding its food, then re-running `_payable`,
    so the liquidation it competes with sees the reduced goods — the spent wood is reserved
    automatically (forward-compatible with a future wood->food liquidation). The source itself
    is a real `before_play_occupation` trigger; the play-occupation enumerator's commit gate
    (`_payable(top.cost)`) then forces it to be fired before the commit unlocks, so there is no
    empty-frontier dead state. (Single-source today; a multi-source future would need to
    consider firing combinations.)"""
    if _payable(state, idx, p, cost):
        return True
    from agricola.cards.specs import OCCUPATION_FOOD_SOURCES
    owned = p.occupations | p.minor_improvements
    for source_card, source_fn in OCCUPATION_FOOD_SOURCES.items():
        if source_card not in owned:
            continue
        result = source_fn(state, idx)          # (food_produced, inputs: Resources) | None
        if result is None:
            continue
        produced, inputs = result
        p_fired = fast_replace(
            p, resources=p.resources - inputs + Resources(food=produced))
        if _payable(state, idx, p_fired, cost):
            return True
    return False


# ---------------------------------------------------------------------------
# Cost resolution — the cost-modifier-card chokepoint (COST_MODIFIER_DESIGN.md)
# ---------------------------------------------------------------------------
# `effective_payments` is THE place a payment frontier is produced; enumeration and
# the debit read it. Legality reads its cheaper existence-view, `can_pay`. Both live
# here, beside `_can_afford` (which they call) and the per-pending enumerators that
# consume them; the modifier registries live in `agricola.cards.cost_mods` and are
# imported lazily (the Family game never registers, so the folds are no-ops).

def effective_payments(state, idx: int, ctx) -> list:
    """The Pareto-minimal set of `PaymentOption`s player `idx` may use for the build
    described by `ctx` (COST_MODIFIER_DESIGN.md §2.1). Family game (no cost cards) →
    returns exactly `[ctx.base]`."""
    from agricola.cards.cost_mods import (
        apply_reductions, base_routes, expand_conversions, formula_mods,
    )
    from agricola.cost import pareto_min_over_goods
    p = state.players[idx]
    # 1. Resource bases: printed cost + each owned formula card's alternative.
    resource_bases = [ctx.base] + formula_mods(ctx.action_kind, state, idx, ctx)
    # 2. Conversions expand each base (before reductions, §2.4). 3. Reductions (signed, floor 0).
    cands = [c for b in resource_bases
             for c in expand_conversions(ctx.action_kind, state, idx, ctx, b)]
    cands = [apply_reductions(ctx.action_kind, state, idx, ctx, c) for c in cands]
    # 4. Keep affordable (resource payments + non-resource routes), then Pareto-min over goods.
    #    `_payable` accepts a food-short-but-liquidatable payment (food raised at execution via
    #    PendingFoodPayment) so it must agree with `can_pay`'s gate — else a card the gate marks
    #    playable would emit zero pay buttons (FOOD_PAYMENT_DESIGN.md §4 gate↔frontier agreement).
    affordable: list = [c for c in cands if _payable(state, idx, p, c, ctx.reserved_animals)]
    affordable += [r for r in base_routes(ctx.action_kind, state, idx, ctx)
                   if _route_affordable(state, idx, r)]
    return pareto_min_over_goods(affordable)


def can_pay(state, idx: int, ctx) -> bool:
    """Short-circuiting existence view of `effective_payments`, for legality — does NOT
    build the full frontier (COST_MODIFIER_DESIGN.md §2.6 / A4). Tries the base first
    (the common / Family case), then any formula base / conversion path / non-resource
    route, stopping at the first affordable one."""
    p = state.players[idx]
    if _payable(state, idx, p, ctx.base, ctx.reserved_animals):
        return True
    from agricola.cards.cost_mods import (
        apply_reductions, base_routes, expand_conversions, formula_mods,
    )
    for b in [ctx.base] + formula_mods(ctx.action_kind, state, idx, ctx):
        for c in expand_conversions(ctx.action_kind, state, idx, ctx, b):
            if _payable(state, idx, p,
                        apply_reductions(ctx.action_kind, state, idx, ctx, c),
                        ctx.reserved_animals):
                return True
    return any(_route_affordable(state, idx, r)
               for r in base_routes(ctx.action_kind, state, idx, ctx))


def _route_affordable(state, idx: int, route) -> bool:
    """Whether a non-resource `ReturnImprovement` route is takeable now — i.e. the
    player owns the major improvement it returns."""
    return state.board.major_improvement_owners[route.improvement_idx] == idx


def _build_room_ctx(p: PlayerState, build_index: int = 0) -> CostCtx:
    """Cost-resolution context for building ONE room for player `p`.

    Base (printed) cost is `ROOM_COSTS[house_material]` (5 of the house material +
    2 reed). `build_index` is the 0-based index of the room within a multi-shot
    build session (the running `num_built`), which a cost card may read to discount
    the Nth room (Carpenter's Apprentice); `num_rooms` is the current room count.
    """
    return CostCtx(
        "build_room", ROOM_COSTS[p.house_material],
        num_rooms=_num_rooms(p), build_index=build_index,
    )


def _can_afford_room(state: GameState, p: PlayerState, build_index: int = 0) -> bool:
    """Affordability check for one room, through the cost-modifier chokepoint.

    In the Family game `can_pay` reduces to "can afford `ROOM_COSTS`" (5 of the
    current house material + 2 reed); with cost cards it also accepts a reduced /
    converted / routed payment. Split out from `_can_build_room` so card cost
    support varies affordability without touching placement geometry.
    """
    idx = 0 if p is state.players[0] else 1
    return can_pay(state, idx, _build_room_ctx(p, build_index))


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


def _can_build_room(state: GameState, p: PlayerState) -> bool:
    """The player can afford one room AND has a valid placement cell."""
    return _can_afford_room(state, p) and _has_room_placement(p)


_RENOVATE_BASE_FIELD = {HouseMaterial.CLAY: "clay", HouseMaterial.STONE: "stone"}


def _renovate_ctx(p: PlayerState, to_material: HouseMaterial) -> CostCtx:
    """The cost-resolution context for renovating player `p`'s house to `to_material`.

    Base (printed) cost: 1 of the TARGET material per room + 1 reed total (to clay:
    `num_rooms` clay + 1 reed; to stone: `num_rooms` stone + 1 reed). `to_material` is a
    degree of freedom — usually the next tier, but a card may make a further tier legal
    (Conservator: wood→stone). Cost-modifier cards may read `to_material` (e.g. a card
    that only discounts the stone tier).
    """
    num_rooms = _num_rooms(p)
    base = Resources(**{_RENOVATE_BASE_FIELD[to_material]: num_rooms, "reed": 1})
    return CostCtx("renovate", base, to_material=to_material, num_rooms=num_rooms)


def _legal_renovate_targets(state: GameState, p: PlayerState) -> list:
    """The house materials player `p` may renovate to right now. Normally the single
    next tier (WOOD→[CLAY], CLAY→[STONE], STONE→[]); card extensions add more
    (Conservator: a wood house may also go straight to STONE)."""
    mat = p.house_material
    if mat == HouseMaterial.WOOD:
        targets = [HouseMaterial.CLAY]
    elif mat == HouseMaterial.CLAY:
        targets = [HouseMaterial.STONE]
    else:  # STONE — already top tier
        targets = []
    idx = 0 if p is state.players[0] else 1
    for ext in RENOVATE_TARGET_EXTENSIONS:
        for t in ext(state, idx, mat):
            if t not in targets:
                targets.append(t)
    return targets


def _can_renovate(state: GameState, p: PlayerState) -> bool:
    """At least one legal renovate target exists AND is payable through the cost-modifier
    chokepoint `can_pay` (so a card that discounts/converts/extends a target makes it
    reachable). In the Family game this reduces to "can afford the next tier's printed
    cost", i.e. the old inline check.

    Mantlepiece permanently forbids renovation for its owner (card ownership is checked
    directly — no extra state needed since it is a permanent effect).
    """
    if "mantlepiece" in p.minor_improvements:
        return False
    idx = 0 if p is state.players[0] else 1
    return any(
        can_pay(state, idx, _renovate_ctx(p, t))
        for t in _legal_renovate_targets(state, p)
    )


def _build_major_ctx(idx: int) -> CostCtx:
    """Cost-resolution context for building major improvement `idx` (base = its printed
    `MAJOR_IMPROVEMENT_COSTS` entry; `major_idx` lets cost cards / the built-in
    Cooking-Hearth Fireplace-return route dispatch on which major)."""
    return CostCtx("build_major", MAJOR_IMPROVEMENT_COSTS[idx], major_idx=idx)


def _can_afford_major(state: GameState, p: PlayerState, idx: int) -> bool:
    """Whether the given player can afford the major improvement at index `idx`.

    Routes through the cost-modifier chokepoint `can_pay`, which covers the printed
    cost (`MAJOR_IMPROVEMENT_COSTS[idx]`), any owned cost-card variant, AND the built-in
    Cooking-Hearth Fireplace-return route (idx 2/3 are payable by returning an owned
    Fireplace — §4.5). In the Family game this reduces to the printed cost-or-Fireplace
    check. The player's index is derived from `p` by identity (not `current_player`)."""
    player_idx = 0 if p is state.players[0] else 1
    return can_pay(state, player_idx, _build_major_ctx(idx))


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
    return _can_build_room(state, p) or _can_build_stable(state, p, Resources(wood=2))


def _legal_farmland(state: GameState) -> bool:
    if not _is_available(state, "farmland"):
        return False
    p = state.players[state.current_player]
    return _can_plow(p)


def _legal_side_job(state: GameState) -> bool:
    if not _is_available(state, "side_job"):
        return False
    p = state.players[state.current_player]
    can_stable = _can_build_stable(state, p, Resources(wood=1))
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
    return _can_renovate(state, p)


def _legal_cultivation(state: GameState) -> bool:
    if not _is_available(state, "cultivation"):
        return False
    p = state.players[state.current_player]
    return _can_plow(p) or _can_sow(p)


def _legal_farm_redevelopment(state: GameState) -> bool:
    if not _is_available(state, "farm_redevelopment"):
        return False
    p = state.players[state.current_player]
    return _can_renovate(state, p)


def _legal_fencing(state: GameState) -> bool:
    """Placement legality for the Fencing action space.

    Requires: space available + ≥1 fence in supply + at least one legal pasture commit
    exists at the current state. The commit check uses `_any_legal_pasture_commit`'s
    two-pass iteration (1×1 fast path, then larger shapes) over the active universe — which
    is itself free-fence-aware, so it is the single authority on "can the player afford any
    fence." In the Family game a 0-wood player can afford none, so a fast `wood < 1` reject is
    kept; in the card game free-fence cards (Hedge Keeper's budget, Briar Hedge's perimeter
    frees) can make a fully-free build affordable at 0 wood, so the wood proxy is dropped
    there and `_any_legal_pasture_commit` decides (COST_MODIFIER_DESIGN.md §9.2)."""
    if not _is_available(state, "fencing"):
        return False
    p = state.players[state.current_player]
    if state.mode is GameMode.FAMILY and p.resources.wood < 1:
        return False
    if buildable_fences(p) < 1:
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
    state: GameState | None = None,
    idx: int | None = None,
    free_budget: int = 0,
    accrued_wood: int = 0,
    initiated_by_id: str | None = None,
    build_fences_action: bool = True,
    restrictions: FenceRestrictions = FenceRestrictions(),
) -> tuple[bool, int, int]:
    """Apply the unified pasture-commit legality chain (TASK_6 §4.5) to one
    universe entry against precomputed per-call state.

    Returns (is_legal, h_new_bm, v_new_bm). h_new/v_new are 0 if not legal.
    Both callers (`_any_legal_pasture_commit` and
    `_enumerate_pending_build_fences`) share this function.

    Free-fence-aware, running-total affordability (COST_MODIFIER_DESIGN.md §9.2/§9.4). Two
    adjustments turn this pasture's raw new-edge count into the wood actually tested:
      * the per-action free-fence budget covers the first `free_budget` of this pasture's new
        edges, so this pasture's PAID edges are `paid = max(0, new_count - free_budget)`; and
      * affordability is checked against the WHOLE-ACTION RUNNING TOTAL
        `running = accrued_wood + paid` — the paid edges of every pasture committed so far this
        Build Fences action (`accrued_wood` = the frame's `accrued_cost.wood`) plus this one —
        not this pasture in isolation.
    The running total is what makes a PER-ACTION-CAPPED conversion correct: Millwright's "up to
    2 grain per action" is counted once against `running`, never re-granted per pasture, so a
    grain-funded build is *enabled* during building and pays with grain at the Proceed settle,
    with no during-building/settle divergence (this replaces the earlier settle-only Millwright
    gate). Gating on `running` (not `new_count`) likewise means a tight-wood build that the free
    budget or a conversion covers is enabled, not merely discounted at settle.

    `free_budget` is the REMAINING per-action budget — the frame's `free_fence_budget` (during
    building) or the anticipated seed (at placement). `accrued_wood` is the frame's
    `accrued_cost.wood` (0 at placement — the first pasture — and in Family, which debits
    per-commit and never accrues). `initiated_by_id` / `build_fences_action` are the frame's
    provenance + literal-action flag, read by the per-edge POSITIONAL fold
    (`positional_free_edge_count`) so a positional card can gate on them (Field Fences on its
    grant) or ignore them (Briar Hedge, any build). Positional frees are computed only on the
    canonical (state/idx) path; all four free-related inputs default to the no-card value, so
    the Family / cached path gates on exactly `new_count` as before. The fence-PIECE supply
    check (`new_count > fences_left`) is on full edge count — free fences still consume pieces
    (§9.7).

    The `running`-wood affordability runs through the cost-modifier chokepoint `can_pay` (with
    the geometry-derived base) when `state`/`idx` are supplied — the non-cached, canonical path.
    The projection-keyed cached scan (`_legal_pasture_commits_compute`) passes neither (and
    `free_budget = accrued_wood = 0`) and falls back to the equivalent `running > wood`
    arithmetic: in the Family game (empty cost registries, zero budget/accrual) `can_pay` against
    `Resources(wood=new_count)` reduces to exactly `wood >= new_count`, a pure function of the
    cache key `(farmyard, wood, subdivision_started)`, so cache and chokepoint agree byte-for-byte
    (`test_fence_scan_cache_transparent`).
    """
    bm = entry.cells_bm

    # 0. Restricted-grant geometry (Mini Pasture etc., §9.8): exact cell count. Default
    #    (exact_size None) = unrestricted, so the Family / normal path is unaffected.
    if restrictions.exact_size is not None and bm.bit_count() != restrictions.exact_size:
        return False, 0, 0

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

    # 2c. Restricted grant: only NEW enclosures (Mini Pasture forbids subdivisions, §9.8).
    if restrictions.forbid_subdivision and is_subdivision:
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
    # WOOD affordability on the PAID edges: POSITIONAL per-edge frees (board-perimeter /
    # next-to-field cards) cover specific new edges by geometry, THEN the per-action
    # free-fence budget covers the next `free_budget` (§9.4 greedy order), and the rest is
    # paid — checked through the cost chokepoint (the canonical path), else the equivalent raw
    # arithmetic in the cached scan (see the docstring). Fence-PIECE supply is checked
    # separately on FULL edge count — free fences still use pieces (§9.7).
    positional_free = 0
    pool_free = 0
    if state is not None and idx is not None:
        from agricola.cards.cost_mods import (
            free_fence_pool_remaining, positional_free_edge_count)
        positional_free = positional_free_edge_count(
            state, idx, state.players[idx].farmyard, h_new, v_new,
            initiated_by_id=initiated_by_id, build_fences_action=build_fences_action)
        pool_free = free_fence_pool_remaining(state.players[idx])   # source 3 (Ash Trees)
    paid = max(0, new_count - positional_free - free_budget - pool_free)
    running = accrued_wood + paid   # whole-action running paid-edge total (§9.2)
    if state is not None and idx is not None:
        if not can_pay(state, idx, _build_fence_ctx(state.players[idx], running)):
            return False, 0, 0
    elif running > wood:
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
    fences_left = 15 - fences_built(farmyard)   # Family cached path: buildable == 15 - built
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
    SPEEDUPS.md S7 and FRONTIER_OPT_DESIGN.md §7. Key changes (i.e.
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
    space_id: str = "fencing",
    initiated_by_id: str | None = None,
    restrictions: FenceRestrictions = FenceRestrictions(),
    free_budget: int | None = None,
    build_fences_action: bool = True,
) -> bool:
    """Return True iff at least one pasture commit is legal for `p` in `state`.

    `restrictions` / `free_budget` / `build_fences_action` support restricted-grant playability
    checks (Mini Pasture's "is a free 1×1 new-enclosure possible?" prereq): pass the grant's
    `FenceRestrictions`, its fixed free-fence allowance (`free_budget` overrides the
    literal-action anticipation), and `build_fences_action=False`. Defaults reproduce the
    original placement / Farm-Redev-offer behavior exactly.

    Two-pass iteration: precomputed 1×1 fast-path first, then the rest of the
    universe (skipping 1×1's already checked). The fast path capitalizes on
    the property "if any commit is legal, some 1×1 commit is legal" (TASK_6
    Part 4.3); the (0, 0)-1×1 addition (Part 1.8) ensures every enclosable
    cell has a 1×1 candidate.

    `subdivision_started=False` is hardcoded because this helper answers a
    placement-time question (Fencing space availability) or a pre-entry
    question (Farm Redev's optional Build Fences offer) — no in-progress
    Build Fences action exists at either call site.

    Free-fence anticipation (COST_MODIFIER_DESIGN.md §9.2): the Build Fences frame
    doesn't exist yet here, so its per-action `free_fence_budget` isn't seeded — but the
    affordability question must already account for it (else a tight-wood build the budget
    would cover is wrongly reported unavailable). So in Cards mode we compute the budget
    the frame *would* seed for a literal Build Fences action at this entry point (`space_id`)
    and gate on the discounted cost. `space_id` defaults to "fencing"; the Farm Redev caller
    passes "farm_redevelopment" (Hedge Keeper ignores it; future entry-point-scoped cards read
    it). Family game → anticipated budget 0 → identical to the old behavior.

    Universe resolution: when any of `entries`, `smallest_entries`, or
    `universe_set` is None, the corresponding `ACTIVE_FENCE_UNIVERSE_*`
    module constant is read at call time. This lets `active_universe(...)`
    reassignments affect this call site without requiring an explicit kwarg.
    """
    # The projection-keyed cache knows nothing about the free-fence budget, so it serves
    # ONLY the Family game (COST_MODIFIER_DESIGN.md §9.7); Cards computes fresh below through
    # the budget-aware `_check_entry_legal`. In Family the anticipated budget is always 0.
    if (opt_config.FENCE_SCAN_CACHE
            and entries is None and smallest_entries is None and universe_set is None
            and restrictions == FenceRestrictions()
            and state.mode is GameMode.FAMILY):
        return bool(_legal_pasture_commits_cached(p.farmyard, p.resources.wood, False))

    idx = 0 if p is state.players[0] else 1
    if free_budget is None:                  # default: anticipate the literal-action budget
        from agricola.cards.cost_mods import free_fence_budget_for
        free_budget = free_fence_budget_for(
            state, idx, build_fences_action=build_fences_action, space_id=space_id)

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
    fences_left = buildable_fences(p)
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
        state=state,
        idx=idx,
        free_budget=free_budget,
        initiated_by_id=initiated_by_id,   # provenance for positional gating (Field Fences)
        build_fences_action=build_fences_action,
        restrictions=restrictions,         # restricted-grant geometry (Mini Pasture prereq)
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
# Card game — playing occupations (CARD_IMPLEMENTATION_PLAN.md II.4)
# ---------------------------------------------------------------------------

def occupation_cost(num_played: int) -> Resources:
    """Food cost to play your NEXT occupation, given how many you've already played.

    2-player rule (RULES.md → Playing occupations): the first occupation is free,
    every later one costs 1 food. (This is the Lessons-space cost; Scholar charges
    a flat 1 food via its own route, so cost is route-supplied, not per-card.)
    """
    return Resources() if num_played == 0 else Resources(food=1)


def playable_occupations(state: GameState, idx: int) -> list[str]:
    """Occupation card ids in player `idx`'s hand that can currently be played.

    Occupations have no prerequisites and a route-supplied (not per-card) cost, so
    every hand occupation is equally playable once the play itself is affordable —
    that affordability gate lives at the placement predicate, not here. Filtered to
    ids with a registered OccupationSpec so an as-yet-unimplemented card in hand is
    simply not offered (no KeyError) while the base set is being built out.
    """
    from agricola.cards.specs import OCCUPATIONS  # local import: load-order safe
    return sorted(state.players[idx].hand_occupations & OCCUPATIONS.keys())


def _legal_lessons_cards(state: GameState) -> bool:
    """Lessons (card game): legal iff the space is free, the player has a playable
    occupation in hand, and they can afford the next occupation's cost."""
    if not _is_available(state, "lessons"):
        return False
    idx = state.current_player
    p = state.players[idx]
    if not playable_occupations(state, idx):
        return False
    # The 2nd+ occupation's 1-food cost may be raised by liquidation at execution
    # (FOOD_PAYMENT_DESIGN.md §4.1) OR by firing an owned occupation-cost food source first
    # (Paper Maker). `_payable_occupation` folds in both; occupations carry no animal cost and
    # stay off `effective_payments` (no cost card touches occupation play cost).
    return _payable_occupation(state, idx, p, occupation_cost(len(p.occupations)))


def _legal_major_improvement_cards(state: GameState) -> bool:
    """Major/Minor Improvement (card game): legal if you can build a major OR play
    a minor from hand. (Family keeps the major-only `_legal_major_improvement`.)"""
    if not _is_available(state, "major_improvement"):
        return False
    idx = state.current_player
    p = state.players[idx]
    return _can_afford_any_major_improvement(state, p) or bool(playable_minors(state, idx))


def _can_afford_cost(p: PlayerState, cost) -> bool:
    """Affordability for a card Cost (Resources + Animals), at the PRINTED price.

    Note: this does NOT apply cost-modifier cards — it is the plain printed-cost check.
    For a minor's playability (which a card may discount), use `playable_minors`, whose
    resource gate routes through the chokepoint `can_pay`."""
    a, ca = p.animals, cost.animals
    return (_can_afford(p, cost.resources)
            and a.sheep >= ca.sheep and a.boar >= ca.boar and a.cattle >= ca.cattle)


def _minor_cost_alternatives(spec, state: GameState, idx: int) -> tuple:
    """The alternative costs for playing this minor, as a tuple of `Cost`s — the
    player pays exactly ONE affordable member (Chophouse "2 Wood / 2 Clay").

    A `cost_fn` card computes a single scaling cost (no printed alternatives);
    otherwise the alternatives are `(spec.cost,) + spec.alt_costs` — the printed
    cost first, then any "/"-alternatives. Ordinary single-cost cards (empty
    `alt_costs`) yield exactly one Cost, unchanged from before."""
    if spec.cost_fn is not None:
        return (spec.cost_fn(state, idx),)
    return (spec.cost,) + spec.alt_costs


def _play_minor_ctx(card_id: str, cost, state: GameState, idx: int) -> CostCtx:
    """Cost-resolution context for playing minor `card_id` with a SPECIFIC alternative
    `cost` (a `Cost`, one member of `_minor_cost_alternatives`).

    The resource portion is the cost-modifier `base`; the animal portion is NOT
    modifiable by cost cards and rides on `reserved_animals` so food-liquidation
    affordability sets it aside (FOOD_PAYMENT_DESIGN.md §4)."""
    return CostCtx(
        "play_minor", cost.resources, card_id=card_id,
        reserved_animals=cost.animals,
    )


def _can_afford_minor_animals(p: PlayerState, animals) -> bool:
    """The (unmodifiable) animal portion of a minor's cost is affordable."""
    a = p.animals
    return a.sheep >= animals.sheep and a.boar >= animals.boar and a.cattle >= animals.cattle


def playable_minors(state: GameState, idx: int) -> list[str]:
    """Minor card ids in player `idx`'s hand that can currently be played:
    registered spec + prerequisite met + cost affordable. Filtered to registered
    MinorSpecs so an as-yet-unimplemented hand card is simply not offered.

    The resource portion of the cost runs through the cost-modifier chokepoint
    (`can_pay`) so an owned cost card (e.g. Bricklayer's clay reduction) makes a
    previously-unaffordable minor playable; the animal portion is checked directly.

    For a "/"-alternative-cost minor (Chophouse) the card is playable iff ANY one
    alternative is fully affordable (resources via `can_pay` AND its own animals)."""
    from agricola.cards.specs import MINORS, prereq_met  # local import: load-order safe
    p = state.players[idx]
    result = []
    for cid in sorted(p.hand_minors & MINORS.keys()):
        spec = MINORS[cid]
        if not prereq_met(spec, state, idx):
            continue
        if any(
            can_pay(state, idx, _play_minor_ctx(cid, cost, state, idx))
            and _can_afford_minor_animals(p, cost.animals)
            for cost in _minor_cost_alternatives(spec, state, idx)
        ):
            result.append(cid)
    return result


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

# Combined dispatch used by `legal_placements` in GameMode.FAMILY.
FAMILY_GAME_LEGALITY: dict[str, Callable[[GameState], bool]] = {
    **ATOMIC_LEGALITY,
    **NON_ATOMIC_LEGALITY,
}

# Combined dispatch used by `legal_placements` in GameMode.CARDS. The card board
# differs from the Family board (CARD_IMPLEMENTATION_PLAN.md I.2–I.4): Side Job is
# gone (absent here); `lessons` (play an occupation) becomes usable; and
# `meeting_place` reuses its slot for the card variant (become SP + optionally
# play a minor) — same placement predicate (`_legal_meeting_place`: legal whenever
# available), with the card behavior selected by mode in the resolver.
CARD_GAME_LEGALITY: dict[str, Callable[[GameState], bool]] = {
    space_id: predicate
    for space_id, predicate in FAMILY_GAME_LEGALITY.items()
    if space_id != "side_job"
}
CARD_GAME_LEGALITY["lessons"] = _legal_lessons_cards
# Major/Minor Improvement is placeable to build a major OR play a minor in cards.
CARD_GAME_LEGALITY["major_improvement"] = _legal_major_improvement_cards


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def legal_placements(state: GameState) -> list[PlaceWorker]:
    """Return all legal PlaceWorker actions across atomic and non-atomic spaces.

    Returns an empty list if the active player has no workers left to place.
    Dispatches on `state.mode`: FAMILY iterates `FAMILY_GAME_LEGALITY` (excludes
    `lessons`, has `side_job` / food-accumulation `meeting_place`); CARDS iterates
    `CARD_GAME_LEGALITY` (the card board's spaces). Each space is surfaced when its
    predicate holds. The mode is chosen at setup; the Family branch is byte-identical
    to before. See CARD_IMPLEMENTATION_PLAN.md I.1.

    Called by `legal_actions` when the pending stack is empty during WORK phase.
    """
    if state.players[state.current_player].people_home < 1:
        return []
    table = (
        FAMILY_GAME_LEGALITY if state.mode is GameMode.FAMILY else CARD_GAME_LEGALITY
    )
    return [
        PlaceWorker(space=s)
        for s, predicate in table.items()
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

    A Proceed-host (and/or; SPACE_HOST_REFACTOR.md §4.3). In the after-phase the
    space's work is done — only after_action_space triggers + Stop are offered.
    In the before-phase: any before_action_space triggers, then the legal
    ChooseSubActions, then Proceed once at least one sub-action has run (the
    "must take at least one effect" gate).

    Order: ChooseSubAction("bake_bread") first if legal, then
    ChooseSubAction("sow") if legal, then Proceed() if its gate is met.
    """
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions
    # before-window gate (SPACE_HOST_REFACTOR.md §5.1): once a base sub-action has been
    # chosen, using the space has closed the before-window — no before_action_space triggers.
    actions = ([] if pending.subaction_started
               else _eligible_fire_triggers(state, pending, trigger_event(pending)))
    p = state.players[pending.player_idx]
    if not pending.bake_chosen and _can_bake_bread(state, p):
        actions.append(ChooseSubAction(name="bake_bread"))
    if not pending.sow_chosen and _can_sow(p):
        actions.append(ChooseSubAction(name="sow"))
    if pending.sow_chosen or pending.bake_chosen:
        actions.append(Proceed())
    return actions


def _enumerate_pending_sow(
    state: GameState, pending: PendingSow,
) -> list[Action]:
    """Enumerate legal (grain, veg[, card_sows]) commits at PendingSow.

    Board constraints:
      - grain <= p.resources.grain, veg <= p.resources.veg
      - grain + veg <= number of empty field cells

    Card-field constraints (user rulings 45-48, 2026-07-12; the Family fast
    path — no owned card-fields — enumerates exactly the pre-card list):
      - each (card_id, good) pair sows one empty stack of that card with an
        allowed good, supply-bounded across the whole commit (a wood sow
        spends supply wood, etc.)
      - `pending.crops_only` (a crops-explicit grant — Fodder Planter)
        excludes wood/stone card sows entirely (ruling 48)

    The sow cap (`pending.max_fields`, 0 = uncapped): board fields count 1
    each; a card-field counts exactly ONE field-unit however many of its
    stacks the commit fills (ruling 48's cap accounting, from Chief
    Forester's clarification "You may plant 2 wood at once with 1 trigger").

    Something must be sown: board + card sows >= 1 total.

    Order: card bundles in `enumerate_card_sows` order (the empty bundle
    first), then (grain, veg) ascending — the Family ordering is unchanged.

    Uniform sub-action host (SUBACTION_HOOK_REFACTOR.md): in the after-phase the
    commit is done, so only after_sow triggers + Stop are offered. In the
    before-phase, any before_sow triggers precede the CommitSow options.
    """
    from agricola.cards.card_fields import (   # local import: load-order safe
        enumerate_card_sows,
    )

    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions
    actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
    p = state.players[pending.player_idx]
    empty_fields = sum(
        1 for r in range(3) for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.FIELD
        and p.farmyard.grid[r][c].grain == 0
        and p.farmyard.grid[r][c].veg == 0
    )
    for bundle in enumerate_card_sows(p, crops_only=pending.crops_only):
        spent: dict[str, int] = {}
        for _cid, good in bundle:
            spent[good] = spent.get(good, 0) + 1
        if (spent.get("wood", 0) > p.resources.wood
                or spent.get("stone", 0) > p.resources.stone):
            continue
        cards_touched = len({cid for cid, _good in bundle})
        for g in range(p.resources.grain - spent.get("grain", 0) + 1):
            for v in range(p.resources.veg - spent.get("veg", 0) + 1):
                if g + v == 0 and not bundle:
                    continue   # must sow something
                if g + v > empty_fields:
                    continue
                if (pending.max_fields
                        and g + v + cards_touched > pending.max_fields):
                    continue
                actions.append(CommitSow(grain=g, veg=v, card_sows=bundle))
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

    Uniform sub-action host (SUBACTION_HOOK_REFACTOR.md): the before-phase hosts
    before_bake_bread triggers (e.g. Potter) + CommitBake; the after-phase hosts
    after_bake_bread triggers + Stop. The trigger event is derived from `phase`
    via `trigger_event` (no per-frame TRIGGER_EVENT).
    """
    # Eligible unfired triggers for this pending's <phase>_bake_bread event,
    # ownership-checked + triggers_resolved-filtered, alphabetical.
    actions: list[Action] = _eligible_fire_triggers(state, pending, trigger_event(pending))

    if pending.phase == "after":
        actions.append(Stop())
        return actions

    p = state.players[pending.player_idx]
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

    Uniform sub-action host (SUBACTION_HOOK_REFACTOR.md): after-phase offers
    after_plow triggers + Stop; before-phase offers before_plow triggers + the
    CommitPlow options.

    Multi-shot grant (`max_plows > 1`; Swing/Turnwrest/Wheel Plow): the before-phase
    offers a CommitPlow for each legal cell while `num_plowed < max_plows`, and once at
    least one field has been plowed (`num_plowed >= 1`) also offers Proceed to finish the
    grant early (mirroring the multi-shot build hosts — Proceed flips to the after-phase,
    Stop then pops). The single-shot default (max_plows=1) flips to its after-phase on the
    first commit (see _execute_plow), so this `num_plowed >= 1` branch never fires for it —
    byte-identical to the pre-multi-shot enumerator.
    """
    actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
    if pending.phase == "after":
        actions.append(Stop())
        return actions
    p = state.players[pending.player_idx]
    # A granted plow that must leave the mandatory base plow legal (Moldboard Plow et al.
    # on Farmland) restricts its cell choice to the non-stranding cells; the plain base
    # plow offers every legal cell (CARD_AUTHORING_GUIDE.md). The non-stranding set is
    # recomputed here from the CURRENT state, so the second plow of a multi-shot grant is
    # re-checked against the board left by the first.
    if pending.num_plowed < pending.max_plows:
        cells = safe_plow_cells(p) if pending.must_preserve_base else _legal_plow_cells(p)
        actions.extend(CommitPlow(row=r, col=c) for (r, c) in cells)
    if pending.num_plowed >= 1:
        actions.append(Proceed())   # finish a multi-shot grant early (never reached at max_plows=1)
    return actions


def _enumerate_pending_build_stables(
    state: GameState, pending: PendingBuildStables,
) -> list[Action]:
    """Enumerate legal actions at PendingBuildStables (multi-shot before/after host).

    A uniform before/after host (SUBACTION_HOOK_REFACTOR.md): in the after-phase
    the stables are built, so only after_build_stables triggers + Stop (pop) are
    legal. In the before-phase, three constraints filter CommitBuildStable options:
      - Caller-imposed cap: max_builds is None or num_built < max_builds.
        Side Job's max_builds=1 saturates after the single commit;
        Farm Expansion's None never blocks here.
      - Buildability: _can_build_stable(p, cost) — combined supply +
        cell-availability + affordability check.
    plus any before_build_stables triggers, then Proceed (the multi-shot's explicit
    work-complete signal — flips to the after-phase) once num_built >= 1 (the
    "must do at least one" rule).
    """
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions

    # before-window gate (mirrors the Proceed-host gate, SPACE_HOST_REFACTOR.md §5.1):
    # a multi-shot build is ONE action, so once the first piece is committed the
    # before-window has closed — offer before_build_stables triggers only before any
    # build (num_built == 0). No effect fires between pieces.
    actions: list[Action] = ([] if pending.num_built else _eligible_fire_triggers(
        state, pending, trigger_event(pending)))
    p = state.players[pending.player_idx]

    cap_ok = pending.max_builds is None or pending.num_built < pending.max_builds
    if cap_ok and _can_build_stable(state, p, pending.cost):
        for (r, c) in _legal_stable_cells(p):
            actions.append(CommitBuildStable(row=r, col=c))

    if pending.num_built >= 1:
        actions.append(Proceed())

    return actions


def _enumerate_pending_build_rooms(
    state: GameState, pending: PendingBuildRooms,
) -> list[Action]:
    """Enumerate legal actions at PendingBuildRooms (multi-shot before/after host).

    Same shape as _enumerate_pending_build_stables. Cell list comes from
    _legal_room_cells (empty, non-enclosed, adjacent to existing ROOM —
    naturally handles within-action adjacency chaining). After-phase:
    after_build_rooms triggers + Stop (pop). Before-phase: before_build_rooms
    triggers, room commits, then Proceed (flips to the after-phase) once
    num_built >= 1.
    """
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions

    # before-window gate (see _enumerate_pending_build_stables): once the first room
    # is built the before-window has closed — offer before_build_rooms triggers only
    # before any build (num_built == 0). The multi-shot build is ONE action.
    actions: list[Action] = ([] if pending.num_built else _eligible_fire_triggers(
        state, pending, trigger_event(pending)))
    p = state.players[pending.player_idx]

    cap_ok = pending.max_builds is None or pending.num_built < pending.max_builds
    # Affordability runs through the cost-modifier chokepoint (a card may reduce /
    # convert / route the room cost); CommitBuildRoom stays geometry-only — the
    # payment is resolved after the cell is chosen (singleton debit in Family,
    # PendingChooseCost two-step when a card offers >1 payment). §3.4/§3.7.
    if cap_ok and can_pay(state, pending.player_idx,
                          _build_room_ctx(p, pending.num_built)):
        for (r, c) in _legal_room_cells(p):
            actions.append(CommitBuildRoom(row=r, col=c))

    if pending.num_built >= 1:
        actions.append(Proceed())

    return actions


def _enumerate_pending_build_major(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal CommitBuildMajor actions at PendingBuildMajor.

    Wide over (major, payment) (COST_MODIFIER_DESIGN.md §3.4): for every unowned major,
    one CommitBuildMajor per entry of its cost-modifier frontier `effective_payments` —
    the printed resource cost (when affordable) plus, for Cooking Hearth, the built-in
    Fireplace-return `ReturnImprovement` route(s), plus any owned cost-card variants.

    Uniform sub-action host (SUBACTION_HOOK_REFACTOR.md): in the after-phase the major is
    built (and any oven free-bake done), so only after_build_major triggers + Stop are
    legal — `phase` here replaces the old `build_chosen` flag.
    """
    actions: list[Action] = _eligible_fire_triggers(state, pending, trigger_event(pending))
    if pending.phase == "after":
        actions.append(Stop())
        return actions
    owners = state.board.major_improvement_owners
    for idx in range(10):
        if owners[idx] is not None:
            continue
        for payment in effective_payments(state, pending.player_idx, _build_major_ctx(idx)):
            actions.append(CommitBuildMajor(major_idx=idx, payment=payment))
    return actions


def _enumerate_pending_renovate(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal CommitRenovate actions at PendingRenovate.

    Renovate is *wide* over (target, payment) (COST_MODIFIER_DESIGN.md §3.4 + the
    renovate-target model): for each legal target tier (usually just the next one;
    Conservator adds wood→stone), the before-phase emits one `CommitRenovate` per entry
    of that target's cost-modifier frontier `effective_payments` — exactly one option in
    the Family game (the next tier's singleton printed cost), several with cost cards.

    Uniform sub-action host (SUBACTION_HOOK_REFACTOR.md): after-phase offers
    after_renovate triggers (e.g. Mining Hammer's free stable) + Stop;
    before-phase offers before_renovate triggers + the renovate commit(s).
    """
    actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
    if pending.phase == "after":
        actions.append(Stop())
        return actions
    p = state.players[pending.player_idx]
    for target in _legal_renovate_targets(state, p):
        ctx = _renovate_ctx(p, target)
        for payment in effective_payments(state, pending.player_idx, ctx):
            actions.append(CommitRenovate(payment=payment, to_material=target))
    return actions


def _enumerate_pending_choose_cost(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal actions at PendingChooseCost (the two-step build-payment frame,
    card game only): one CommitChooseCost per entry of the frozen `payments` frontier
    (COST_MODIFIER_DESIGN.md §3.7). No Stop — a payment must be made for the geometry
    already committed; the frontier is non-empty by construction (the build's effect
    only pushes this frame when >1 affordable payment survived)."""
    return [CommitChooseCost(payment=pay) for pay in pending.payments]


# ---------------------------------------------------------------------------
# Parent pending enumerators (Farm Expansion, Farmland, Cultivation, Side Job,
# Markets, Major/Minor Improvement, Clay/Stone Oven wrappers, House Redevelopment)
# ---------------------------------------------------------------------------

def _enumerate_pending_farm_expansion(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal actions at PendingFarmExpansion.

    A Proceed-host (and/or; SPACE_HOST_REFACTOR.md §4.3). After-phase: after
    triggers + Stop. Before-phase: any before triggers, then the legal
    ChooseSubActions, then Proceed once at least one sub-action has run.

    Once-per-category: build_rooms and build_stables each appear only if the
    corresponding *_chosen flag is False AND the player can actually do it.
    Proceed is legal once at least one sub-action has been chosen (the
    "must do at least one when entering the action" rule).
    """
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions
    # before-window gate (SPACE_HOST_REFACTOR.md §5.1): once a base sub-action has been
    # chosen, using the space has closed the before-window — no before_action_space triggers.
    actions = ([] if pending.subaction_started
               else _eligible_fire_triggers(state, pending, trigger_event(pending)))
    p = state.players[pending.player_idx]
    if not pending.room_chosen and _can_build_room(state, p):
        actions.append(ChooseSubAction(name="build_rooms"))
    if not pending.stable_chosen and _can_build_stable(state, p, Resources(wood=2)):
        actions.append(ChooseSubAction(name="build_stables"))
    if pending.room_chosen or pending.stable_chosen:
        actions.append(Proceed())
    return actions


def _subactionspace_choice(state, pending) -> ChooseSubAction | None:
    """The single mandatory ChooseSubAction the generic Delegating space host
    offers in its before-phase, dispatched by `space_id` (SPACE_HOST_REFACTOR.md
    §4.2/§8). Returns None if the sub-action isn't currently doable (only happens
    for spaces whose placement legality doesn't guarantee it — none today, since
    Farmland/Fencing/Major/Lessons all guarantee a doable mandatory at placement).
    """
    sid = pending.space_id
    p = state.players[pending.player_idx]
    if sid == "farmland":
        return ChooseSubAction(name="plow") if _can_plow(p) else None
    if sid == "fencing":
        return ChooseSubAction(name="build_fences")
    if sid == "major_improvement":
        return (ChooseSubAction(name="improvement")
                if _can_afford_any_major_improvement(state, p)
                or (state.mode is GameMode.CARDS
                    and bool(playable_minors(state, pending.player_idx)))
                else None)
    if sid == "lessons":
        return ChooseSubAction(name="play_occupation")
    raise AssertionError(f"Unknown sub-action space host {sid!r}")


def _enumerate_pending_subactionspace(
    state: GameState, pending,
) -> list[Action]:
    """Legal actions at a generic Delegating space host (PendingSubActionSpace;
    SPACE_HOST_REFACTOR.md §4.2). before-phase: any before_action_space triggers +
    the single mandatory ChooseSubAction (the child). after-phase (reached via the
    auto-advance once the child popped): after_action_space triggers + Stop.

    A `before_action_space` trigger is offered ONLY in the before-phase (while
    subaction_complete == False); taking the mandatory ChooseSubAction closes the
    before-window and implicitly declines any unfired one (SPACE_HOST_REFACTOR.md
    §5.1). The auto-advance flips the host to its after-phase the instant the
    mandatory sub-action completes — within the same step — so the
    `subaction_complete && phase=="before"` state is purely transient and never
    enumerated here. A card whose "each time you use [space]" grant the player wants
    must therefore fire it before using the space (CARD_AUTHORING_GUIDE.md); a grant
    that competes with the mandatory sub-action for a resource must gate its own
    eligibility so the sub-action stays legal after it fires."""
    event = trigger_event(pending)
    # Expand play-variant triggers (Cookery Lesson's cook-sheep/boar/cattle on the Lessons
    # after-phase) into one FireTrigger per legal route, mirroring the atomic-host enumerator;
    # a no-op when no owned trigger here is a variant trigger (so Family is byte-identical).
    actions = _expand_variant_triggers(
        state, pending, _eligible_fire_triggers(state, pending, event))
    if pending.phase == "after":
        actions.append(Stop())
        return actions
    choice = _subactionspace_choice(state, pending)
    if choice is not None:
        actions.append(choice)
    return actions


def _enumerate_pending_cultivation(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal actions at PendingCultivation.

    A Proceed-host (and/or; SPACE_HOST_REFACTOR.md §4.3). After-phase: after
    triggers + Stop. Before-phase: any before triggers, the legal
    ChooseSubActions (plow / sow), then Proceed once a sub-action has run.
    Using the space (the first sub-action) is the implicit decline of any
    before-window — the base sub-actions stay offered until Proceed.
    """
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions
    # before-window gate (SPACE_HOST_REFACTOR.md §5.1): once a base sub-action has been
    # chosen, using the space has closed the before-window — no before_action_space triggers.
    actions = ([] if pending.subaction_started
               else _eligible_fire_triggers(state, pending, trigger_event(pending)))
    p = state.players[pending.player_idx]
    if not pending.plow_chosen and _can_plow(p):
        actions.append(ChooseSubAction(name="plow"))
    if not pending.sow_chosen and _can_sow(p):
        actions.append(ChooseSubAction(name="sow"))
    if pending.plow_chosen or pending.sow_chosen:
        actions.append(Proceed())
    return actions


def _enumerate_pending_side_job(
    state: GameState, pending,
) -> list[Action]:
    p = state.players[pending.player_idx]
    actions: list[Action] = []
    if not pending.stable_chosen:
        if _can_build_stable(state, p, Resources(wood=1)):
            actions.append(ChooseSubAction(name="build_stables"))
    if not pending.bake_chosen and _can_bake_bread(state, p):
        actions.append(ChooseSubAction(name="bake_bread"))
    if pending.stable_chosen or pending.bake_chosen:
        actions.append(Stop())
    return actions


def _enumerate_pending_animal_market(
    state: GameState, pending,
) -> list[Action]:
    """Shared enumerator for the three animal markets (4b: before/after phases).

    before-phase: any eligible before_action_space triggers, then one
    CommitAccommodate per Pareto-frontier (sheep, boar, cattle) config the player
    can land on after taking the market's animals. CommitAccommodate pivots the
    frame to the after-phase (it no longer auto-pops).

    after-phase: any eligible after_action_space triggers, then Stop (which pops).
    With no after-trigger this is a singleton [Stop] the agent auto-skips, so a
    Family-game market is one CommitAccommodate followed by an auto-skipped Stop.
    """
    from agricola.helpers import cooking_rates, pareto_frontier
    from agricola.pending import PendingCattleMarket, PendingPigMarket, PendingSheepMarket
    from agricola.resources import Animals

    actions = _eligible_fire_triggers(state, pending, trigger_event(pending))

    if pending.phase == "after":
        actions.append(Stop())
        return actions

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
    actions.extend(
        CommitAccommodate(sheep=a.sheep, boar=a.boar, cattle=a.cattle)
        for (a, _food) in frontier
    )
    return actions


def _enumerate_pending_accommodate(
    state: GameState, pending,
) -> list[Action]:
    """Reconciliation frame (engine._reconcile_accommodation): the player is over animal
    capacity because a decision-free grant landed animals past what the farm can house.

    Offer one CommitAccommodate per housable Pareto-frontier config over the player's
    CURRENT animals (`gained=Animals()` — the grant already landed in `player.animals`);
    the excess is cooked to food at cooking rates by _execute_accommodate, which then
    pops this frame. No before/after triggers — a bare reconciliation, not a space host.

    The frame's `min_keep` (default Animals() — no bound) drops every frontier point
    that keeps fewer than the bound of any type: a card that pushed this frame to house
    a specific just-gained animal (Automatic Water Trough) never offers a config that
    discards it. Loss-less (dominance is over kept counts, so a bound-satisfying point
    is only ever dominated by another bound-satisfying point) and asserted non-empty —
    the pushing card's eligibility gate certified a satisfying config exists.
    """
    from agricola.helpers import cooking_rates, pareto_frontier
    from agricola.resources import Animals

    p = state.players[pending.player_idx]
    rates = cooking_rates(state, pending.player_idx)[:3]
    frontier = pareto_frontier(p, Animals(), rates)
    mk = pending.min_keep
    options = [
        CommitAccommodate(sheep=a.sheep, boar=a.boar, cattle=a.cattle)
        for (a, _food) in frontier
        if a.sheep >= mk.sheep and a.boar >= mk.boar and a.cattle >= mk.cattle
    ]
    assert options, "PendingAccommodate.min_keep filtered the frontier empty (gate/frontier mismatch)"
    return options


def _enumerate_pending_major_minor_improvement(
    state: GameState, pending,
) -> list[Action]:
    """The composite "build a major OR play a minor" action — a Delegating host
    (SPACE_HOST_REFACTOR.md §4.2/§6). after-phase (reached via the auto-advance
    once the child popped): after_major_minor_improvement triggers + Stop.
    before-phase: any before_major_minor_improvement triggers + the exclusive
    build_major / play_minor choice. The transient subaction_complete state is
    never enumerated (the auto-advance flips it inside the same step)."""
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions
    actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
    p = state.players[pending.player_idx]
    # "Build a major OR play a minor" — exclusive, so offer either only while
    # NEITHER has been chosen. (In the Family game minor_chosen is never set and
    # the play_minor branch is gated off by mode, so this is byte-identical.)
    neither = not pending.major_chosen and not pending.minor_chosen
    if neither and _can_afford_any_major_improvement(state, p):
        actions.append(ChooseSubAction(name="build_major"))
    if (neither and state.mode is GameMode.CARDS
            and playable_minors(state, pending.player_idx)):
        actions.append(ChooseSubAction(name="play_minor"))
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
    """Enumerate legal actions at PendingHouseRedevelopment.

    A Proceed-host (and-then; SPACE_HOST_REFACTOR.md §4.3): renovate is the
    mandatory first sub-action (no Proceed until it has run), then the optional
    improvement, then Proceed. After-phase: after triggers + Stop.
    """
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions
    # before-window gate (SPACE_HOST_REFACTOR.md §5.1): once a base sub-action has been
    # chosen, using the space has closed the before-window — no before_action_space triggers.
    actions = ([] if pending.subaction_started
               else _eligible_fire_triggers(state, pending, trigger_event(pending)))
    p = state.players[pending.player_idx]
    if not pending.renovate_chosen and _can_renovate(state, p):
        actions.append(ChooseSubAction(name="renovate"))
    # The optional post-renovate improvement: build a major OR (card game) play a
    # minor. The "improvement" choose pushes PendingMajorMinorImprovement, which
    # offers both branches. Family is byte-identical (mode-gated; playable_minors
    # is empty there anyway).
    can_improve = _can_afford_any_major_improvement(state, p) or (
        state.mode is GameMode.CARDS and bool(playable_minors(state, pending.player_idx))
    )
    if pending.renovate_chosen and not pending.improvement_chosen and can_improve:
        actions.append(ChooseSubAction(name="improvement"))
    if pending.renovate_chosen:
        actions.append(Proceed())
    return actions


def _enumerate_pending_build_fences(
    state: GameState,
    pending: PendingBuildFences,
    *,
    entries: tuple | None     = None,
    universe_set: frozenset | None = None,
) -> list[Action]:
    """Enumerate legal actions at PendingBuildFences (multi-shot before/after host).

    A uniform before/after host (SUBACTION_HOOK_REFACTOR.md), like
    `_enumerate_pending_build_stables` / `_rooms`: in the after-phase the fences
    are built, so only after_build_fences triggers + Stop (pop) are legal. In the
    before-phase, the unified pasture-commit legality chain (TASK_6 §4.5) via
    `_check_entry_legal` emits one CommitBuildPasture per legal entry, preceded by
    any before_build_fences triggers, then Proceed (the multi-shot's explicit
    work-complete signal — flips to the after-phase) once at least one pasture has
    been committed.

    Universe resolution: when `entries` or `universe_set` is None, the
    corresponding `ACTIVE_FENCE_UNIVERSE_*` module constant is read at call
    time. This lets `active_universe(...)` reassignments affect this call
    site without requiring an explicit kwarg.
    """
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions

    # The projection-keyed cache is keyed only on (farmyard, wood, subdivision_started) —
    # it knows nothing about the free-fence budget or any cost modifier — so it is consulted
    # ONLY in the Family game (COST_MODIFIER_DESIGN.md §9.7). Cards computes fresh through the
    # budget-aware `_check_entry_legal` below. The `assert` fails loud if a card state ever
    # reaches the cache (the key would be incomplete → a stale legal-pasture set).
    if (opt_config.FENCE_SCAN_CACHE and entries is None and universe_set is None
            and state.mode is GameMode.FAMILY):
        assert pending.free_fence_budget == 0, (
            "fence-scan cache reached with a nonzero free_fence_budget — key is incomplete")
        assert pending.restrictions == FenceRestrictions(), (
            "fence-scan cache reached with a restricted grant — key is incomplete")
        p = state.players[pending.player_idx]
        legal = _legal_pasture_commits_cached(
            p.farmyard, p.resources.wood, pending.subdivision_started,
        )
        # before-window gate (consistency with the card path below; a no-op here since
        # this cached branch is Family-only where no before_build_fences triggers exist).
        actions: list[Action] = ([] if pending.pastures_built else _eligible_fire_triggers(
            state, pending, trigger_event(pending)))
        actions += [CommitBuildPasture(cells=e.cells) for e in legal]
        if pending.pastures_built >= 1:
            actions.append(Proceed())
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
    fences_left = buildable_fences(p)
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
        state=state,
        idx=pending.player_idx,
        free_budget=pending.free_fence_budget,   # the REMAINING per-action budget (§9.4)
        accrued_wood=pending.accrued_cost.wood,  # whole-action paid-edge running total (§9.2)
        initiated_by_id=pending.initiated_by_id,  # provenance for positional gating (Field Fences)
        build_fences_action=pending.build_fences_action,
        restrictions=pending.restrictions,        # restricted-grant geometry (Mini Pasture, §9.8)
    )

    # before-window gate (see _enumerate_pending_build_stables): once the first pasture
    # is committed the before-window has closed — offer before_build_fences triggers only
    # before any build (pastures_built == 0). A multi-shot fence build is ONE action; no
    # effect (e.g. Loppers) fires between pasture commits.
    actions: list[Action] = ([] if pending.pastures_built else _eligible_fire_triggers(
        state, pending, trigger_event(pending)))
    # A restricted grant caps the action's commit count (Mini Pasture = 1): once the cap is
    # reached, offer no more commits (the player Proceeds to finish). Unrestricted = no cap.
    cap = pending.restrictions.max_pastures
    if cap is None or pending.pastures_built < cap:
        for entry in entries:
            ok, _h, _v = _check_entry_legal(entry, **common)
            if ok:
                actions.append(CommitBuildPasture(cells=entry.cells))

    if pending.pastures_built >= 1:
        actions.append(Proceed())

    return actions


def _enumerate_pending_farm_redevelopment(
    state: GameState, pending: PendingFarmRedevelopment,
) -> list[Action]:
    """Enumerate legal actions at PendingFarmRedevelopment.

    A Proceed-host (and-then; SPACE_HOST_REFACTOR.md §4.3). Mirrors
    `_enumerate_pending_house_redevelopment` with the optional second step
    swapped from "improvement" to "build_fences". Renovate is mandatory first
    (Proceed illegal until renovate_chosen); Build Fences is offered only after
    renovate AND only when at least one legal pasture commit exists. After-phase:
    after triggers + Stop.
    """
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions
    # before-window gate (SPACE_HOST_REFACTOR.md §5.1): once a base sub-action has been
    # chosen, using the space has closed the before-window — no before_action_space triggers.
    actions = ([] if pending.subaction_started
               else _eligible_fire_triggers(state, pending, trigger_event(pending)))
    p = state.players[pending.player_idx]
    if not pending.renovate_chosen and _can_renovate(state, p):
        actions.append(ChooseSubAction(name="renovate"))
    if (pending.renovate_chosen
            and not pending.build_fences_chosen
            and _any_legal_pasture_commit(state, p, space_id="farm_redevelopment")):
        actions.append(ChooseSubAction(name="build_fences"))
    if pending.renovate_chosen:
        actions.append(Proceed())
    return actions


def _enumerate_pending_granted_build_fences(
    state: GameState, pending: "PendingGrantedBuildFences",
) -> list[Action]:
    """Enumerate legal actions at PendingGrantedBuildFences — an OPTIONAL granted Build
    Fences (Field Fences). Offers ChooseSubAction("build_fences") (only before the build is
    taken AND when at least one pasture is buildable under THIS grant's provenance — so the
    grant's positional discount is anticipated, mirroring Farm Redev's offer) plus Stop
    (decline before, or finish after). After the inner build pops, `build_fences_chosen` is
    True, so only Stop remains."""
    actions: list[Action] = []
    if not pending.build_fences_chosen:
        p = state.players[pending.player_idx]
        if _any_legal_pasture_commit(
                state, p, space_id=pending.initiated_by_id,
                initiated_by_id=pending.initiated_by_id):
            actions.append(ChooseSubAction(name="build_fences"))
    actions.append(Stop())
    return actions


def _enumerate_pending_harvest_feed(
    state: GameState, pending,
) -> list[Action]:
    """Enumerate legal actions at PendingHarvestFeed.

    Two regimes based on the pending's state:

    1. `conversion_done == False`: offer each undecided owned conversion that
       the player can afford, AND all Pareto-frontier CommitConvert points from
       harvest_feed_frontier.
    2. `conversion_done == True`: only Stop is legal.

    No ordering between crafts and the main convert: the agent can fire
    crafts in any order before committing convert, or commit convert
    immediately. Committing forfeits any unfired crafts — that is the only way
    to decline a craft (there is no explicit "skip" action, since recording a
    skip is indistinguishable from forfeiting it at commit).

    `food_owed` is derived on each call from the live player state:
        need      = helpers.feeding_requirement (2*people_total - newborns
                    + any owned card folds — Child's Toy)
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
    from agricola.helpers import (
        cooking_rates,
        feeding_requirement,
        harvest_feed_frontier,
    )

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
        # Offer the conversion only if affordable; declining is implicit
        # (commit CommitConvert without firing it).
        if not _can_afford(p, spec.input_cost):
            continue
        if spec.variants_fn is None:
            actions.append(CommitHarvestConversion(conversion_id=conversion_id))
        else:
            # A variant-bearing conversion (Craft Brewery's which-grain-field
            # choice) is offered WIDE: one commit per currently-legal variant;
            # an empty variant list withholds it. Still once per harvest total
            # (harvest_conversions_used records the id, variant included).
            actions.extend(
                CommitHarvestConversion(conversion_id=conversion_id, variant=v)
                for v in spec.variants_fn(state, pending.player_idx))

    # 2. All Pareto-frontier CommitConvert points. Invert REMAINING tuples
    #    to CONSUMED amounts (consumed = player_max - remaining).
    rates = cooking_rates(state, pending.player_idx)  # 4-tuple
    need       = feeding_requirement(state, pending.player_idx)
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

    Before `breed_chosen`: the frame's pre-commit card triggers (event
    "breeding" — Stone Importer's stone buy; user ruling 20, 2026-07-05: an
    in-breeding-phase effect fires BEFORE the CommitBreed decision, never
    after) plus one CommitBreed per Pareto-frontier point from
    breeding_frontier (frontier always non-empty — includes at minimum the
    do-nothing config). After `breed_chosen`: the outcome-reactive triggers
    (event "breeding_outcome" — the Fodder Planter / Slurry Spreader C71 sow
    grants, still inside the breeding phase) plus Stop, which declines
    whatever is unfired. Both trigger lookups are empty-dict no-ops in the
    Family game.
    """
    from agricola.cards.triggers import has_unfired_mandatory_trigger
    from agricola.helpers import breeding_frontier, cooking_rates

    p = state.players[pending.player_idx]

    if pending.breed_chosen:
        actions = _expand_variant_triggers(
            state, pending,
            _eligible_fire_triggers(state, pending, "breeding_outcome"))
        if not has_unfired_mandatory_trigger(state, pending, "breeding_outcome"):
            actions.append(Stop())
        return actions

    actions = _expand_variant_triggers(
        state, pending, _eligible_fire_triggers(state, pending, "breeding"))
    rates_3 = cooking_rates(state, pending.player_idx)[:3]
    for (cfg, _food) in breeding_frontier(p, rates_3):
        actions.append(CommitBreed(sheep=cfg.sheep, boar=cfg.boar, cattle=cfg.cattle))

    return actions


# ---------------------------------------------------------------------------
# Card-trigger event routing + the action-space host enumerator (II.2)
# ---------------------------------------------------------------------------

def trigger_event(frame) -> str:
    """The trigger/auto-effect event a host frame fires, derived from its kind.

    Space-host frames (the bucket above) share `<phase>_action_space`; every
    other frame uses `<phase>_<PENDING_ID>` (e.g. before_bake_bread, after_renovate).
    Requires `frame.phase` ("before"/"after"). See CARD_IMPLEMENTATION_PLAN.md II.2.
    """
    pid = type(frame).PENDING_ID
    base = "action_space" if pid in ACTION_SPACE_PENDING_IDS else pid
    return f"{frame.phase}_{base}"


def _eligible_fire_triggers(state, pending, event: str) -> list:
    """The FireTrigger options for `event` at `pending`: each owned, unfired,
    eligible card registered on the event, alphabetical by card_id.

    Ownership is checked here (a hand card cannot fire); declining is implicit
    (no SkipTrigger — pick a commit / Proceed / Stop instead).
    """
    from agricola.cards.triggers import TRIGGERS, _owns
    p = state.players[pending.player_idx]
    entries = []
    for entry in TRIGGERS.get(event, ()):
        if not _owns(p, entry.card_id):
            continue
        if entry.card_id in pending.triggers_resolved:
            continue
        if not entry.eligibility_fn(state, pending.player_idx, pending.triggers_resolved):
            continue
        entries.append(entry)
    entries.sort(key=lambda e: e.card_id)
    return [FireTrigger(card_id=e.card_id) for e in entries]


def _expand_variant_triggers(state, pending, base: list) -> list:
    """Expand each play-variant trigger in `base` into one FireTrigger per legal
    variant — the route is chosen AT the fire (carried in `FireTrigger.variant`),
    not via an intermediate decision node — passing plain triggers through unchanged.

    Shared by the start-of-round host (Scholar's occupation-vs-minor route) and the
    action-space host (Cottager's build-room-vs-renovate route). A no-op when no card
    in `base` is registered in PLAY_VARIANT_TRIGGERS, so the Family game (no triggers
    at all) is unaffected.
    """
    from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS
    actions: list[Action] = []
    for ft in base:
        variants_fn = PLAY_VARIANT_TRIGGERS.get(ft.card_id)
        if variants_fn is None:
            actions.append(ft)
            continue
        for v in variants_fn(state, pending.player_idx):
            actions.append(FireTrigger(card_id=ft.card_id, variant=v))
    return actions


def _enumerate_pending_action_space(
    state: GameState, pending: PendingActionSpace,
) -> list[Action]:
    """Legal actions at a generic action-space host frame (atomic spaces).

    before-phase: any eligible before-triggers, then Proceed (apply the space's
    primary effect, advance to after). after-phase: any eligible after-triggers,
    then Stop (pop). With no eligible trigger this is a singleton [Proceed] /
    [Stop] the agent auto-skips — so a hosted Forest still plays in one decision.

    Play-variant triggers (Cottager's build-room-vs-renovate on Day Laborer) are
    expanded into one FireTrigger per legal variant, the same way the start-of-round
    host expands Scholar.

    Mandatory-with-choice gate (II.1): the phase-exit (Proceed in before, Stop in
    after) is WITHHELD while an eligible, unfired `mandatory` trigger remains for
    this phase's event — Seasonal Worker on Day Laborer cannot be declined. Once it
    has fired, the exit reopens.
    """
    from agricola.cards.triggers import has_unfired_mandatory_trigger

    event = trigger_event(pending)
    actions = _expand_variant_triggers(
        state, pending, _eligible_fire_triggers(state, pending, event))
    if not has_unfired_mandatory_trigger(state, pending, event):
        actions.append(Proceed() if pending.phase == "before" else Stop())
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
    PendingAccommodate,
    PendingCattleMarket,
    PendingClayOven,
    PendingCultivation,
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
def _enumerate_pending_play_occupation(
    state: GameState, top: PendingPlayOccupation,
) -> list[Action]:
    """Legal actions at PendingPlayOccupation: one CommitPlayOccupation per playable
    hand occupation. Lessons plays exactly one occupation with no decline, so the
    before-phase has no Stop — placement legality already guaranteed at least one
    playable, affordable card.

    Uniform sub-action host (SUBACTION_HOOK_REFACTOR.md): after the occupation is
    played the frame is in its after-phase, offering after_play_occupation
    triggers (e.g. Bread Paddle) + Stop."""
    actions = _eligible_fire_triggers(state, top, trigger_event(top))
    if top.phase == "after":
        actions.append(Stop())
        return actions
    from agricola.cards.specs import PLAY_OCCUPATION_VARIANTS
    p = state.players[top.player_idx]
    for cid in playable_occupations(state, top.player_idx):
        variants_fn = PLAY_OCCUPATION_VARIANTS.get(cid)
        if variants_fn is None:
            # Ordinary occupation: a single variant-less commit — offered only when its play
            # cost is CURRENTLY payable (liquidation-aware). This is the gate↔frontier guard:
            # if the cost is short and not liquidatable, the commit is withheld (a `before_
            # play_occupation` food source like Paper Maker must be fired first to raise the
            # food), so committing never pushes an empty-frontier PendingFoodPayment.
            if _payable(state, top.player_idx, p, top.cost):
                actions.append(CommitPlayOccupation(card_id=cid))
            continue
        # Play-variant occupation (Roof Ballaster): one commit per variant whose
        # base-play-cost + declared SURCHARGE is payable (liquidation-aware). The base play
        # cost lives on the frame (`top.cost`); the surcharge rides on the variant (§8). This
        # is the single affordability gate for the surcharge — `_payable` here folds in food
        # liquidation, so the latent "pay then go negative" bug cannot recur.
        for v, surcharge in variants_fn(state, top.player_idx):
            if _payable(state, top.player_idx, p, top.cost + surcharge):
                actions.append(CommitPlayOccupation(card_id=cid, variant=v))
    return actions


def _enumerate_pending_basic_wish_for_children(
    state: GameState, pending: PendingBasicWishForChildren,
) -> list[Action]:
    """Card game — a Proceed-host (and-then; SPACE_HOST_REFACTOR.md §4.3).

    Family growth is the mandatory first sub-action (no Proceed until it has run),
    then the optional minor, then Proceed. Mirrors
    `_enumerate_pending_house_redevelopment` with `family_growth` as the mandatory
    step and `play_minor` as the optional second.

    After-phase: after_action_space triggers + Stop.
    Before-phase: any before_action_space triggers (only while no base sub-action
    has been chosen — the enforce-first before-window gate), then ChooseSubAction(
    "family_growth") while not yet done, then ChooseSubAction("play_minor") (if a
    minor is playable and not yet chosen) + Proceed once family_growth_done.
    """
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions
    # before-window gate (SPACE_HOST_REFACTOR.md §5.1): once a base sub-action has been
    # chosen, using the space has closed the before-window — no before_action_space triggers.
    actions = ([] if pending.subaction_started
               else _eligible_fire_triggers(state, pending, trigger_event(pending)))
    if not pending.family_growth_done:
        # Mandatory first sub-action — a singleton the agent auto-applies.
        actions.append(ChooseSubAction(name="family_growth"))
        return actions
    # Post-growth: optional minor.
    if not pending.minor_chosen and playable_minors(state, pending.player_idx):
        actions.append(ChooseSubAction(name="play_minor"))
    # Proceed is the work-complete boundary (replaces the old Stop here).
    actions.append(Proceed())
    return actions


def _enumerate_pending_family_growth(
    state: GameState, top: PendingFamilyGrowth,
) -> list[Action]:
    """The family-growth primitive: a single mandatory, parameter-free
    CommitFamilyGrowth (a singleton the agent auto-applies).

    Uniform sub-action host (SUBACTION_HOOK_REFACTOR.md): after the growth the
    frame is in its after-phase, offering after_family_growth triggers + Stop."""
    actions = _eligible_fire_triggers(state, top, trigger_event(top))
    if top.phase == "after":
        actions.append(Stop())
        return actions
    actions.append(CommitFamilyGrowth())
    return actions


def _enumerate_pending_meeting_place(
    state: GameState, pending: PendingMeetingPlace,
) -> list[Action]:
    """Card Meeting Place — a single-optional Proceed-host (SPACE_HOST_REFACTOR.md
    §7). Become-SP already happened. after-phase: after_action_space triggers +
    Stop. before-phase: any before_action_space triggers (only while the minor is
    unchosen — the enforce-first before-window gate) + the optional
    ChooseSubAction("play_minor") (while not yet played and a minor is playable) +
    Proceed — and Proceed is legal FROM THE START (it *is* the decline)."""
    if pending.phase == "after":
        actions = _eligible_fire_triggers(state, pending, trigger_event(pending))
        actions.append(Stop())
        return actions
    # before-window gate (SPACE_HOST_REFACTOR.md §5.1): choosing the minor closes
    # the before-window — no before_action_space triggers after it.
    actions = ([] if pending.subaction_started
               else _eligible_fire_triggers(state, pending, trigger_event(pending)))
    if not pending.minor_chosen and playable_minors(state, pending.player_idx):
        actions.append(ChooseSubAction(name="play_minor"))
    actions.append(Proceed())
    return actions


def _enumerate_pending_play_minor(
    state: GameState, top: PendingPlayMinor,
) -> list[Action]:
    """Legal actions at PendingPlayMinor: one CommitPlayMinor per playable hand
    minor — and nothing else. This frame is pushed only once the player has
    committed to playing a minor (so >=1 is always playable); whether playing was
    optional is handled by the parent's Stop, not here.

    Uniform sub-action host (SUBACTION_HOOK_REFACTOR.md): after the minor is
    played the frame is in its after-phase, offering after_play_minor triggers
    + Stop."""
    actions = _eligible_fire_triggers(state, top, trigger_event(top))
    if top.phase == "after":
        actions.append(Stop())
        return actions
    # Wide over (card, alternative-cost, payment): one CommitPlayMinor per playable card,
    # per printed/"/"-alternative cost, per resource-cost frontier point (§3.4). The
    # `payment` (a `PaymentOption` = Resources vector) already encodes WHICH alternative
    # was chosen — a "2 Wood" alternative and a "2 Clay" alternative yield distinct
    # payments — so no extra field is needed to disambiguate; `_execute_play_minor`
    # debits exactly that payment. A card with no alternatives + no cost card yields the
    # single printed cost, unchanged. The animal cost (if any) rides on the spec, checked
    # per-alternative inside `effective_payments` via the ctx's reserved_animals.
    from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS  # load-order safe
    p = state.players[top.player_idx]
    for cid in playable_minors(state, top.player_idx):
        spec = MINORS[cid]
        alternatives = _minor_cost_alternatives(spec, state, top.player_idx)
        variants_fn = PLAY_MINOR_VARIANTS.get(cid)
        for i, cost in enumerate(alternatives):
            ctx = _play_minor_ctx(cid, cost, state, top.player_idx)
            # `cost` rides on the commit ONLY when it is a genuine alternative (not the
            # printed `spec.cost`, i.e. index > 0), so ordinary single-cost minors keep
            # the default `cost=None` and their commits are unchanged (existing cards +
            # Family byte-identity untouched). `_execute_play_minor` reads the chosen
            # alternative's animal portion from it; the resource debit is `payment`.
            commit_cost = None if i == 0 else cost
            # A card whose reward is coupled to WHICH alternative it paid (Canvas
            # Sack) labels its alternatives; the chosen label rides on the commit's
            # `variant` and is threaded into a 3-arg on_play. The cost itself is the
            # real alternative (already run through `effective_payments` above), so
            # it stays cost-modifier-visible — unlike a play-variant surcharge.
            label = spec.cost_labels[i] if spec.cost_labels else None
            for payment in effective_payments(state, top.player_idx, ctx):
                if variants_fn is None:
                    actions.append(CommitPlayMinor(
                        card_id=cid, payment=payment, cost=commit_cost, variant=label))
                    continue
                # Play-variant minor (PLAY_MINOR_VARIANTS — Facades Carving): one
                # commit per variant whose surcharge, ON TOP of this payment, is
                # payable (liquidation-aware, like the occupation path's gate) —
                # the surcharge folds into `payment` so the executor's debit and
                # food-shortfall guard need no special handling. Cost modifiers
                # never see the surcharge (payments were enumerated from the
                # card's own cost above).
                for v, surcharge in variants_fn(state, top.player_idx):
                    total = payment + surcharge
                    if _payable(state, top.player_idx, p, total):
                        actions.append(CommitPlayMinor(
                            card_id=cid, payment=total,
                            cost=commit_cost, variant=v))
    return actions


def _enumerate_pending_food_payment(
    state: GameState, top: PendingFoodPayment,
) -> list[Action]:
    """Legal actions at PendingFoodPayment: one CommitFoodPayment per Pareto-optimal
    crops/animals-to-food conversion bundle that fully covers the shortfall
    (FOOD_PAYMENT_DESIGN.md §4). A closed frame — only these frontier points, no Stop/triggers.

    `owe` is derived live from the player's current food. The frontier is run over goods MINUS
    `top.reserved` — the convertible part of the cost the resumed action will itself debit — so
    a reserved good is never offered as conversion fuel and can't be double-spent (§5). Invert
    `food_payment_frontier`'s REMAINING tuples to CONSUMED amounts (relative to the reduced
    goods), exactly as `_enumerate_pending_harvest_feed` does. The frontier is asserted
    non-empty: the gate (`_liquidatable_to`) guarantees feasibility over the same reduced
    goods, so an empty frontier here is a gate↔frontier mismatch and must fail loud."""
    from agricola.cards.harvest_windows import (
        available_span_converters,
        post_breed_floors,
    )

    p = state.players[top.player_idx]
    owe = max(0, top.food_needed - p.resources.food)
    rates = cooking_rates(state, top.player_idx)
    avail = fast_replace(
        p,
        resources=p.resources - top.reserved.resources,
        animals=p.animals - top.reserved.animals,
    )
    grain_pre  = avail.resources.grain
    veg_pre    = avail.resources.veg
    sheep_pre  = avail.animals.sheep
    boar_pre   = avail.animals.boar
    cattle_pre = avail.animals.cattle
    # The converter cluster (rulings 34/37/39, 2026-07-12): in-span once-per-
    # harvest building-resource converters join the Pareto space, and the
    # post-breed cooking floor protects bred types. Both are () / zeros in the
    # Family game and outside the harvest span — the legacy path.
    converters = available_span_converters(state, top.player_idx)
    floors = post_breed_floors(state, top.player_idx)
    frontier = food_payment_frontier(
        avail, owe, rates, span_converters=converters, animal_floors=floors)
    assert frontier, (
        f"PendingFoodPayment frontier empty: owe={owe} food_needed={top.food_needed} "
        f"reserved={top.reserved} resume_kind={top.resume_kind} — gate↔frontier mismatch"
    )
    if not converters:
        # With or without floors, the converter-less shape is plain 5-tuples.
        return [
            CommitFoodPayment(
                grain  = grain_pre  - g_rem,
                veg    = veg_pre    - v_rem,
                sheep  = sheep_pre  - s_rem,
                boar   = boar_pre   - b_rem,
                cattle = cattle_pre - c_rem,
            )
            for (g_rem, v_rem, s_rem, b_rem, c_rem) in frontier
        ]
    return [
        CommitFoodPayment(
            grain  = grain_pre  - vec[0],
            veg    = veg_pre    - vec[1],
            sheep  = sheep_pre  - vec[2],
            boar   = boar_pre   - vec[3],
            cattle = cattle_pre - vec[4],
            conversions = fired,
        )
        for (vec, fired) in frontier
    ]


def _enumerate_pending_preparation(
    state: GameState, pending: PendingPreparation,
) -> list[Action]:
    """Legal actions at a PendingPreparation start-of-round host (card game only).

    The phase host for "at the start of each round, you can…" cards. Its event is
    `start_of_round` (the autos already fired at push in `_fire_preparation_hook`);
    this surfaces the remaining eligible, unfired `start_of_round` triggers (Plow
    Driver, Groom, Scholar, and the mandatory Childless) as FireTrigger, then
    `Proceed` — the work-complete boundary that pops the frame.

    Proceed is GATED OFF (mandatory-with-choice, II.1) while an eligible, unfired
    `mandatory` trigger remains for this player: Childless cannot be declined, so the
    only legal exits are firing it (→ a PendingCardChoice crop pick) until it has
    fired, after which Proceed reopens. With no mandatory trigger pending the host is
    an ordinary optional-trigger phase: when no trigger is eligible this is a
    singleton [Proceed] the agent auto-applies.
    """
    from agricola.cards.triggers import has_unfired_mandatory_trigger

    base = _eligible_fire_triggers(state, pending, "start_of_round")
    # Expand any play-variant trigger (Scholar) into per-variant FireTriggers — the
    # route (occupation / minor) is chosen AT the fire, not via an intermediate node.
    actions = _expand_variant_triggers(state, pending, base)
    if not has_unfired_mandatory_trigger(state, pending, "start_of_round"):
        actions.append(Proceed())
    return actions


def _enumerate_pending_harvest_window(
    state: GameState, pending: "PendingHarvestWindow",
) -> list[Action]:
    """Legal actions at a per-player harvest-window choice host (card game only).

    One frame per simple harvest timing window per player with an eligible
    registered trigger (`agricola/cards/harvest_windows.py`; the walk is
    `engine._advance_harvest`). The frame's `window_id` doubles as the event
    string: surface the player's eligible, unfired triggers for it
    (variant-expanded), then `Proceed` — the decline / work-complete boundary
    that pops. Mandatory-with-choice triggers gate Proceed off until fired,
    exactly like the preparation and harvest-field hosts this mirrors.
    """
    from agricola.cards.triggers import has_unfired_mandatory_trigger

    base = _eligible_fire_triggers(state, pending, pending.window_id)
    actions = _expand_variant_triggers(state, pending, base)
    if not has_unfired_mandatory_trigger(state, pending, pending.window_id):
        actions.append(Proceed())
    return actions


def _enumerate_pending_field_phase(
    state: GameState, pending: "PendingFieldPhase",
) -> list[Action]:
    """Legal actions at the FIELD during-window host (card game only;
    HARVEST_WINDOWS_DESIGN.md §4). The window is free-order: its eligible
    "field_phase" triggers (variant-expanded) surface in ANY order around the
    mandatory take —

    - `CommitFieldTake` while `take_fired` is False (the take is the window's
      own mandatory work). Choice-bearing take-MODIFIERS (Stable Manure —
      ruling 11: their extras are part of the one take event) expand it into
      variants: one commit per combination of modifier uses, the bare
      `modifiers=()` being "use none" (each is a "you can"). Committing any
      of them IS the one-way gate of §4b — every unchosen modifier use is
      implicitly declined, because the event it would have modified has
      happened.
    - `Proceed` (the exit) only once the take HAS fired, and never while a
      mandatory-with-choice trigger is unfired, exactly like every other host.
    """
    from agricola.cards.harvest_windows import take_modifier_combos
    from agricola.cards.triggers import has_unfired_mandatory_trigger

    base = _eligible_fire_triggers(state, pending, "field_phase")
    actions = _expand_variant_triggers(state, pending, base)
    if not pending.take_fired:
        # take_modifier_combos is the cross-product of each owned modifier's
        # variants-or-decline, feasibility-filtered (a combination whose
        # merged demands can't all be met — two modifiers competing for the
        # same fields' spare — is dropped), so every offered CommitFieldTake
        # is executable.
        actions.extend(
            CommitFieldTake(modifiers=c)
            for c in take_modifier_combos(state, pending.player_idx))
    elif not has_unfired_mandatory_trigger(state, pending, "field_phase"):
        actions.append(Proceed())
    return actions


def _enumerate_pending_harvest_occasion(
    state: GameState, pending,
) -> list[Action]:
    """Legal actions at a PendingHarvestOccasion host (card game only): the
    player's eligible OPTIONAL reactions to the frame's just-emitted harvest
    occasion (event "harvest_occasion" — Potato Ridger's at-3 exchange, Food
    Merchant's per-grain buys), variant-expanded, plus Proceed to decline and
    pop. The occasion payload rides the frame; the registered elig/variants/
    apply adapters read it from the stack top (harvest_windows.
    register_harvest_occasion_trigger). Mandatory choice-free tiers (Potato
    Ridger's "with 4+ vegetables, you MUST do so") never surface here — they
    are occasion AUTOS, fired with no player input before this host is pushed
    (user ruling 2026-07-05), and the frame's `autos_fired` keeps the same
    card's optional tier from double-reacting."""
    actions = _expand_variant_triggers(
        state, pending,
        _eligible_fire_triggers(state, pending, "harvest_occasion"))
    actions.append(Proceed())
    return actions


def _enumerate_pending_card_choice(
    state: GameState, pending: PendingCardChoice,
) -> list[Action]:
    """Legal actions at a PendingCardChoice (card game only): exactly one
    CommitCardChoice per option, NO Stop/decline (II.6). A single-option frame is a
    singleton the agent auto-resolves; a multi-option frame (Childless / Seasonal
    Worker r6+ grain-vs-veg) is the player's forced pick."""
    return [CommitCardChoice(index=i) for i in range(len(pending.options))]


def _enumerate_pending_draft_pick(
    state: GameState, pending: PendingDraftPick,
) -> list[Action]:
    """One CommitDraftPick per card remaining in the active player's pool."""
    p0_occ, p0_min, p1_occ, p1_min = state.draft_pools
    if pending.player_idx == 0:
        pool = p0_occ if pending.card_type == "occupation" else p0_min
    else:
        pool = p1_occ if pending.card_type == "occupation" else p1_min
    return [CommitDraftPick(card_id=cid) for cid in pool]


PENDING_ENUMERATORS: dict[type, Callable] = {
    PendingPreparation:         _enumerate_pending_preparation,
    PendingHarvestWindow:       _enumerate_pending_harvest_window,
    PendingHarvestOccasion:     _enumerate_pending_harvest_occasion,
    PendingFieldPhase:          _enumerate_pending_field_phase,
    PendingCardChoice:          _enumerate_pending_card_choice,
    PendingPlayOccupation:      _enumerate_pending_play_occupation,
    PendingPlayMinor:           _enumerate_pending_play_minor,
    PendingFoodPayment:         _enumerate_pending_food_payment,
    PendingBasicWishForChildren: _enumerate_pending_basic_wish_for_children,
    PendingFamilyGrowth:        _enumerate_pending_family_growth,
    PendingMeetingPlace:        _enumerate_pending_meeting_place,
    PendingGrainUtilization:    _enumerate_pending_grain_utilization,
    PendingSow:                 _enumerate_pending_sow,
    PendingBakeBread:           _enumerate_pending_bake_bread,
    PendingPlow:                _enumerate_pending_plow,
    PendingBuildStables:        _enumerate_pending_build_stables,
    PendingBuildRooms:          _enumerate_pending_build_rooms,
    PendingBuildMajor:          _enumerate_pending_build_major,
    PendingRenovate:            _enumerate_pending_renovate,
    PendingChooseCost:          _enumerate_pending_choose_cost,
    PendingFarmExpansion:       _enumerate_pending_farm_expansion,
    PendingSubActionSpace:      _enumerate_pending_subactionspace,
    PendingCultivation:         _enumerate_pending_cultivation,
    PendingSideJob:             _enumerate_pending_side_job,
    PendingSheepMarket:         _enumerate_pending_animal_market,
    PendingPigMarket:           _enumerate_pending_animal_market,
    PendingCattleMarket:        _enumerate_pending_animal_market,
    PendingMajorMinorImprovement: _enumerate_pending_major_minor_improvement,
    PendingClayOven:            _enumerate_pending_clay_oven,
    PendingStoneOven:           _enumerate_pending_stone_oven,
    PendingHouseRedevelopment:  _enumerate_pending_house_redevelopment,
    PendingBuildFences:         _enumerate_pending_build_fences,
    PendingFarmRedevelopment:   _enumerate_pending_farm_redevelopment,
    PendingGrantedBuildFences:  _enumerate_pending_granted_build_fences,
    PendingHarvestFeed:         _enumerate_pending_harvest_feed,
    PendingHarvestBreed:        _enumerate_pending_harvest_breed,
    PendingAccommodate:         _enumerate_pending_accommodate,
    PendingReveal:              _enumerate_pending_reveal,
    PendingActionSpace:         _enumerate_pending_action_space,
    PendingDraftPick:           _enumerate_pending_draft_pick,
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
