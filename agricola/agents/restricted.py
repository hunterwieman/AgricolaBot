"""Action-pruning wrapper around `legal_actions`.

`restricted_legal_actions(state)` returns a (possibly narrower) list of legal
actions, applying a fixed set of strategic priors. The wrapper never produces
an empty action set: each filter that would empty the list is skipped, so the
restricted list is always a subset of `legal_actions(state)` of size ≥ 1
(or 0 only when the input is also empty — phase=BEFORE_SCORING).

The priors are organized into per-pending filters:

- **Sub-action ordering** (provably losses are bounded — see notes):
    - Cultivation: plow before sow.
    - Grain Utilization: sow before bake.  (Caveat: bake-first is strictly
      more flexible with Potter Ceramics in play. The user accepted this
      tradeoff explicitly for the current card scope; revisit when more
      bake-event triggers land.)
    - Farm Expansion: build rooms before stables.

- **Cell priority** (opinionated; rooms/stables/plow go to predetermined cells):
    - Stables built in order: (0,4), (0,3), (1,4), (1,3).
    - Rooms built in order:   (0,0), (2,1), (1,1), (2,2).
    - Plow targets in order:  (0,1), (0,2), (1,1), (0,0), (1,2), (2,2), (2,3).
  At each Commit*-cell decision, the wrapper keeps only the top-priority
  legal cell. If none of the priority cells happen to be legal at the
  current state, the filter falls back to the full action set (preserves
  ≥1 legal action).

- **First-pasture opener**: the very first CommitBuildPasture in a given
  PendingBuildFences session must include cell (0,4) or (1,4). Once
  pastures_built >= 1 the restriction lifts.

- **Hard room cap**: never grow past 5 total rooms (2 starting + 3 additional).
  Applied at PendingFarmExpansion (drop ChooseSubAction("build_rooms")) and
  at PendingBuildRooms (drop further CommitBuildRoom once at cap).

- **Minimum-begging at CommitConvert**: at PendingHarvestFeed, among all
  enumerated CommitConvert options keep only those that incur the minimum
  begging count. If multiple actions tie for the minimum, all are kept.

Architectural choices:

- Engine code is NOT modified. `restricted_legal_actions` is a pure wrapper
  over the unrestricted `legal_actions(state)`. Removing or A/B-testing the
  restrictions is one constructor argument away.
- Filters compose. Each is a pure function `(state, top, actions) ->
  list[Action]`. The dispatcher inspects the top pending frame and applies
  the relevant filters in a fixed order.
- The wrapper has zero effect when the pending stack is empty
  (PlaceWorker-level decisions). No restriction is applied to top-level
  worker placement.
"""

from __future__ import annotations

from typing import Callable

from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitPlow,
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
from agricola.state import GameState


# ---------------------------------------------------------------------------
# Priority lists and caps
# ---------------------------------------------------------------------------
#
# These tuples define both WHICH cells are allowed AND in what order they
# are filled. Cells not appearing in a list are never selected as long as
# any listed cell is legal. (If no listed cell is legal — rare; happens
# only in atypical board states — the filter falls back to the full
# action set so the agent stays unstuck.)
#
# Starting rooms are at (1, 0) and (2, 0) per setup.py, so they are
# intentionally absent from ROOM_PRIORITY (those cells already hold rooms).
# Plow priority lists 7 cells out of 13 plowable cells; the omitted cells
# are reserved for pasture / stable / room placements.

STABLE_PRIORITY: tuple[tuple[int, int], ...] = (
    (0, 4),
    (0, 3),
    (1, 4),
    (1, 3),
)

ROOM_PRIORITY: tuple[tuple[int, int], ...] = (
    (0, 0),
    (2, 1),
    (1, 1),
    (2, 2),
)

PLOW_PRIORITY: tuple[tuple[int, int], ...] = (
    (0, 1),
    (0, 2),
    (1, 1),
    (0, 0),
    (1, 2),
    (2, 2),
    (2, 3),
)

# The first pasture in any Build Fences session must include at least one of
# these cells. Once one pasture has been committed, the restriction lifts.
FIRST_PASTURE_REQUIRED_CELLS: frozenset = frozenset({(0, 4), (1, 4)})

# Hard cap on total rooms in the farmyard. 2 starting + 3 additional = 5.
MAX_TOTAL_ROOMS: int = 5


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def restricted_legal_actions(state: GameState) -> list[Action]:
    """Apply strategic action-pruning to `legal_actions(state)`.

    Returns a list that is a (possibly narrowed) subset of the unrestricted
    legal action set. Empty only when the unrestricted set is empty.

    Composition: filters are applied in dispatch order based on the type of
    the top pending frame. Each filter's `_safe_narrow(...)` call guarantees
    the result stays non-empty (filter is skipped if it would empty the set).
    """
    actions = legal_actions(state)
    if not actions:
        return actions
    if not state.pending_stack:
        # PlaceWorker-level decisions get no restriction.
        return actions

    top = state.pending_stack[-1]

    if isinstance(top, PendingFarmExpansion):
        actions = _filter_farm_expansion_room_cap(state, top, actions)
        actions = _filter_farm_expansion_ordering(state, top, actions)
    elif isinstance(top, PendingCultivation):
        actions = _filter_cultivation_ordering(state, top, actions)
    elif isinstance(top, PendingGrainUtilization):
        actions = _filter_grain_utilization_ordering(state, top, actions)
    elif isinstance(top, PendingBuildStables):
        actions = _filter_cell_priority(actions, STABLE_PRIORITY, CommitBuildStable)
    elif isinstance(top, PendingBuildRooms):
        actions = _filter_build_rooms_cap(state, top, actions)
        actions = _filter_cell_priority(actions, ROOM_PRIORITY, CommitBuildRoom)
    elif isinstance(top, PendingPlow):
        actions = _filter_cell_priority(actions, PLOW_PRIORITY, CommitPlow)
    elif isinstance(top, PendingBuildFences):
        actions = _filter_first_pasture(state, top, actions)
    elif isinstance(top, PendingHarvestFeed):
        actions = _filter_min_begging(state, top, actions)

    return actions


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_narrow(filtered: list[Action], fallback: list[Action]) -> list[Action]:
    """Return `filtered` if non-empty, else `fallback`.

    Universal escape valve: every filter calls through this so that an
    over-aggressive restriction can never produce an empty action set. The
    fallback preserves the engine's invariant that an active player always
    has at least one legal action available.
    """
    return filtered if filtered else fallback


def _count_rooms(grid: tuple) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )


# ---------------------------------------------------------------------------
# Sub-action ordering filters (ChooseSubAction level)
# ---------------------------------------------------------------------------

def _filter_farm_expansion_ordering(
    state: GameState, top: PendingFarmExpansion, actions: list[Action],
) -> list[Action]:
    """Build rooms before stables at PendingFarmExpansion.

    If ChooseSubAction("build_rooms") is on offer (engine has decided room
    builds are legal), drop ChooseSubAction("build_stables"). Stop and any
    other actions pass through unchanged.
    """
    has_rooms = any(
        isinstance(a, ChooseSubAction) and a.name == "build_rooms"
        for a in actions
    )
    if not has_rooms:
        return actions
    narrowed = [
        a for a in actions
        if not (isinstance(a, ChooseSubAction) and a.name == "build_stables")
    ]
    return _safe_narrow(narrowed, actions)


def _filter_cultivation_ordering(
    state: GameState, top: PendingCultivation, actions: list[Action],
) -> list[Action]:
    """Plow before sow at PendingCultivation."""
    has_plow = any(
        isinstance(a, ChooseSubAction) and a.name == "plow"
        for a in actions
    )
    if not has_plow:
        return actions
    narrowed = [
        a for a in actions
        if not (isinstance(a, ChooseSubAction) and a.name == "sow")
    ]
    return _safe_narrow(narrowed, actions)


def _filter_grain_utilization_ordering(
    state: GameState, top: PendingGrainUtilization, actions: list[Action],
) -> list[Action]:
    """Sow before bake at PendingGrainUtilization."""
    has_sow = any(
        isinstance(a, ChooseSubAction) and a.name == "sow"
        for a in actions
    )
    if not has_sow:
        return actions
    narrowed = [
        a for a in actions
        if not (isinstance(a, ChooseSubAction) and a.name == "bake_bread")
    ]
    return _safe_narrow(narrowed, actions)


# ---------------------------------------------------------------------------
# Room cap filters (PendingFarmExpansion + PendingBuildRooms)
# ---------------------------------------------------------------------------

def _filter_farm_expansion_room_cap(
    state: GameState, top: PendingFarmExpansion, actions: list[Action],
) -> list[Action]:
    """Drop ChooseSubAction("build_rooms") when at the MAX_TOTAL_ROOMS cap.

    Stops the player from entering PendingBuildRooms when no more rooms can
    be built per this wrapper's policy (even though the engine would allow
    it).
    """
    p = state.players[top.player_idx]
    if _count_rooms(p.farmyard.grid) < MAX_TOTAL_ROOMS:
        return actions
    narrowed = [
        a for a in actions
        if not (isinstance(a, ChooseSubAction) and a.name == "build_rooms")
    ]
    return _safe_narrow(narrowed, actions)


def _filter_build_rooms_cap(
    state: GameState, top: PendingBuildRooms, actions: list[Action],
) -> list[Action]:
    """At PendingBuildRooms, drop CommitBuildRoom once the player is at cap.

    This catches the case where the cap is reached mid-session (multi-shot:
    the player built their MAX_TOTAL_ROOMS-th room and a further build is
    still offered by the engine but disallowed by policy). Stop is left in
    place — the engine offers it once num_built >= 1, which is always true
    in this branch because reaching the cap requires at least one commit.
    """
    p = state.players[top.player_idx]
    if _count_rooms(p.farmyard.grid) < MAX_TOTAL_ROOMS:
        return actions
    narrowed = [a for a in actions if not isinstance(a, CommitBuildRoom)]
    return _safe_narrow(narrowed, actions)


# ---------------------------------------------------------------------------
# Cell priority filter (PendingBuildStables / PendingBuildRooms / PendingPlow)
# ---------------------------------------------------------------------------

def _filter_cell_priority(
    actions: list[Action],
    priority: tuple[tuple[int, int], ...],
    commit_class: type,
) -> list[Action]:
    """Keep only the highest-priority cell among Commit* of `commit_class`.

    Strategy: walk `priority` in order; if any cell appears in the legal
    commit set, keep ONLY that one commit (plus any non-`commit_class`
    actions in the input — typically Stop). If none of the priority cells
    are legal, fall back to the original action set (the priority list
    didn't anticipate the current board shape).

    The semantic is: cells outside the priority list are never chosen as
    long as a priority cell is available; ordering among priority cells is
    strict, no tiebreaks.
    """
    commits = [a for a in actions if isinstance(a, commit_class)]
    others = [a for a in actions if not isinstance(a, commit_class)]
    if not commits:
        return actions
    by_cell = {(a.row, a.col): a for a in commits}
    for (r, c) in priority:
        if (r, c) in by_cell:
            return others + [by_cell[(r, c)]]
    # No priority cell is legal — fall back so the agent isn't stuck.
    return actions


# ---------------------------------------------------------------------------
# First-pasture filter (PendingBuildFences)
# ---------------------------------------------------------------------------

def _filter_first_pasture(
    state: GameState, top: PendingBuildFences, actions: list[Action],
) -> list[Action]:
    """At a fresh PendingBuildFences (`pastures_built == 0`), require the
    first committed pasture to include at least one cell from
    FIRST_PASTURE_REQUIRED_CELLS.

    Once any pasture has been committed (`pastures_built >= 1`), the
    restriction lifts and the full set of CommitBuildPasture options passes
    through.
    """
    if top.pastures_built > 0:
        return actions
    pastures = [a for a in actions if isinstance(a, CommitBuildPasture)]
    others = [a for a in actions if not isinstance(a, CommitBuildPasture)]
    if not pastures:
        return actions
    eligible = [
        p for p in pastures
        if any(cell in FIRST_PASTURE_REQUIRED_CELLS for cell in p.cells)
    ]
    return _safe_narrow(others + eligible, actions)


# ---------------------------------------------------------------------------
# Min-begging filter (PendingHarvestFeed)
# ---------------------------------------------------------------------------

def _filter_min_begging(
    state: GameState, top: PendingHarvestFeed, actions: list[Action],
) -> list[Action]:
    """Among enumerated CommitConvert options, keep only those with minimum
    begging.

    CommitHarvestConversion (craft-firing decisions) and Stop pass through
    unchanged — the filter only constrains the final convert.

    The begging count is computed directly from the action's consumed
    amounts:
        food_produced = grain·1 + veg·vR + sheep·sR + boar·bR + cattle·cR
        need = 2·people_total − newborns
        begging = max(0, need − food_supply − food_produced)
    where rates come from `cooking_rates(state, player_idx)`.

    All CommitConvert options sharing the minimum begging value are kept
    (typically a unique config, but ties are possible — e.g. two
    different upstream-goods configurations that both produce exactly
    enough food).
    """
    # Avoid importing helpers at module top to keep imports light.
    from agricola.helpers import cooking_rates

    converts = [a for a in actions if isinstance(a, CommitConvert)]
    others = [a for a in actions if not isinstance(a, CommitConvert)]
    if len(converts) <= 1:
        return actions

    p = state.players[top.player_idx]
    rates = cooking_rates(state, top.player_idx)  # (sheep, boar, cattle, veg)
    sR, bR, cR, vR = rates
    need = 2 * p.people_total - p.newborns
    food_supply = p.resources.food

    def begging_of(a: CommitConvert) -> int:
        food_produced = (
            a.grain
            + a.veg * vR
            + a.sheep * sR
            + a.boar * bR
            + a.cattle * cR
        )
        return max(0, need - food_supply - food_produced)

    scored = [(a, begging_of(a)) for a in converts]
    min_beg = min(b for _, b in scored)
    keep = [a for a, b in scored if b == min_beg]
    return _safe_narrow(others + keep, actions)


# ---------------------------------------------------------------------------
# Convenience export: the wrapper as a `legal_actions_fn` argument
# ---------------------------------------------------------------------------
#
# Both `RandomAgent` and `HeuristicAgent` take a `legal_actions_fn` kwarg
# defaulting to `agricola.legality.legal_actions`. Passing
# `restricted_legal_actions` swaps in the pruned action set everywhere the
# agent consults legality (top-level pick, singleton-skip, rollout).

LegalActionsFn = Callable[[GameState], list[Action]]
