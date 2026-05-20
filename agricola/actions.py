from __future__ import annotations

from dataclasses import dataclass
from typing import Union


# ---------------------------------------------------------------------------
# Action types
# ---------------------------------------------------------------------------
#
# Flat tagged union: every action is its own frozen dataclass under the
# `Action` alias. Dispatched by `isinstance` in agricola/engine.py's
# `_apply_action`. See CLAUDE.md "Engine and Turn Resolution Architecture"
# for the design rationale.


@dataclass(frozen=True)
class PlaceWorker:
    """Place the active player's worker on an action space.

    For atomic spaces this is the entire action.
    For non-atomic spaces this initiates a chain of pending sub-decisions.
    """
    space: str   # action space ID, e.g. "forest", "grain_utilization"


@dataclass(frozen=True)
class ChooseSubAction:
    """Pick a sub-action category at a non-atomic space's pending decision.

    Categories are space-specific strings: e.g. "sow", "bake_bread" at
    Grain Utilization. The handler pushes the corresponding Pending* onto
    the stack.
    """
    name: str


@dataclass(frozen=True)
class CommitSubAction:
    """Marker base for all Commit* sub-action types.

    Empty by design — concrete commit dataclasses (CommitSow, CommitBake, …)
    inherit from this so `_apply_commit_subaction` in engine.py can dispatch
    them uniformly through the `COMMIT_SUBACTION_HANDLERS` table.
    """


@dataclass(frozen=True)
class CommitSow(CommitSubAction):
    """Commit a sow with specific grain and veg counts."""
    grain: int
    veg: int


@dataclass(frozen=True)
class CommitBake(CommitSubAction):
    """Commit a Bake Bread with the chosen grain amount."""
    grain: int


@dataclass(frozen=True)
class CommitPlow(CommitSubAction):
    """Commit a Plow at the chosen (row, col) cell."""
    row: int
    col: int


@dataclass(frozen=True)
class CommitBuildStable(CommitSubAction):
    """Commit a Build Stable at the chosen (row, col) cell.

    The cost paid is read from the host pending's `cost` field, not from
    this commit (the cost is determined by the caller that pushed
    `PendingBuildStables`, not by the agent at commit time).
    """
    row: int
    col: int


@dataclass(frozen=True)
class CommitBuildRoom(CommitSubAction):
    """Commit a Build Room at the chosen (row, col) cell.

    The cost paid is read from the host PendingBuildRooms' `cost` field
    (set at push time from `ROOM_COSTS[p.house_material]`). Each commit
    builds one room; the multi-shot session continues until the player
    explicitly Stops (the pending does not auto-pop).
    """
    row: int
    col: int


@dataclass(frozen=True)
class CommitBuildMajor(CommitSubAction):
    """Commit a Major Improvement purchase.

    For Cooking Hearth (major_idx 2 or 3), `return_fireplace_idx` can be
    set to 0 or 1 to pay by returning the named Fireplace instead of
    paying clay. For all other majors, `return_fireplace_idx` must be None.

    Dispatched via the generic commit dispatcher with `auto_pop=False`
    (registered in `COMMIT_SUBACTION_HANDLERS`). The effect function
    `_execute_build_major` owns the stack manipulation: pop
    `PendingBuildMajor` for non-oven majors, or push
    `PendingClayOven` / `PendingStoneOven` for Clay/Stone Oven.
    """
    major_idx: int
    return_fireplace_idx: int | None = None


@dataclass(frozen=True)
class CommitRenovate(CommitSubAction):
    """Commit a renovation (all rooms at once)."""


@dataclass(frozen=True)
class CommitAccommodate(CommitSubAction):
    """Commit a final animal configuration after taking from an animal market.

    Lands directly on the parent market pending (PendingSheepMarket /
    PendingPigMarket / PendingCattleMarket) — there is no separate
    sub-action pending pushed by the markets. The dispatcher's
    expected_pending_type entry uses a tuple of the three market types.
    """
    sheep: int
    boar: int
    cattle: int


@dataclass(frozen=True)
class CommitBuildPasture(CommitSubAction):
    """Commit one pasture build at PendingBuildFences.

    `cells` is the cell-set of the pasture being committed — same shape as
    one entry in the active fence universe (UNIVERSE_RESTRICTED by default).
    `frozenset` gives content-based equality and hashing, so two
    CommitBuildPasture objects naming the same cell-set compare equal
    regardless of construction order. By convention, callers iterating
    `cells` for display or logging sort by (row, col) lexicographic order.

    Cost is NOT a field on this commit — it is a pure function of
    (state, commit.cells) computed by `compute_new_fence_edges` in
    `agricola.fences`. This is the 4th sub-action cost-handling bucket
    (CLAUDE.md "Additional Design Principles" → "Sub-action cost handling").

    Dispatched via `auto_pop=False`: the effect function leaves
    PendingBuildFences on top with updated counters; Stop pops it.
    """
    cells: frozenset                          # frozenset[tuple[int, int]]


@dataclass(frozen=True)
class CommitHarvestConversion(CommitSubAction):
    """Commit a once-per-harvest goods-to-food conversion decision at PendingHarvestFeed.

    `conversion_id` is a key in HARVEST_CONVERSIONS (e.g. "joinery", "pottery",
    "basketmaker", or a future card-registered id).

    `use=True` fires the conversion: pays input_cost, produces food_out, applies
    against food_owed (with surplus going to supply). `use=False` records the
    decision without firing. Either way, the conversion_id is added to
    `player.harvest_conversions_used` so the enumerator no longer offers it
    for the remainder of this harvest's FEED. Dispatched with `auto_pop=False`
    — the pending stays on top to host further craft decisions and the final
    CommitConvert.
    """
    conversion_id: str
    use:           bool


@dataclass(frozen=True)
class CommitConvert(CommitSubAction):
    """Commit the player's chosen goods-to-food conversion configuration at
    PendingHarvestFeed.

    Fields hold CONSUMED amounts — values subtracted from the player's supply
    at commit time (contrast with CommitAccommodate / CommitBreed, which hold
    post-event-state counts). The CONSUMED convention fits CommitConvert because
    the values are bounded by per-good caps in food_payment_frontier, and
    (0,0,0,0,0) means "consume nothing" regardless of player state.

    The legality enumerator constructs CommitConvert by inverting the
    REMAINING-goods tuples returned by harvest_feed_frontier (consumed =
    player_max - remaining).

    Dispatched with `auto_pop=False`. After this commit, only Stop is legal
    on the pending — `conversion_done` is set True, and any remaining
    food_owed becomes begging markers (assigned by _execute_convert, not Stop,
    preserving the Stop-only-pops convention).
    """
    grain:  int
    veg:    int
    sheep:  int
    boar:   int
    cattle: int


@dataclass(frozen=True)
class CommitBreed(CommitSubAction):
    """Commit the final post-breed animal configuration at PendingHarvestBreed.

    Fields hold POST-BREED animal counts (matches the convention of
    CommitAccommodate). The triple must match a Pareto-optimal point from
    `breeding_frontier(player_state, rates[:3])`; the legality enumerator
    only emits frontier points.

    Dispatched with `auto_pop=False`: the effect sets the chosen counts and
    adds the frontier's `food_gained` to supply; Stop is the explicit exit.
    """
    sheep:  int
    boar:   int
    cattle: int


@dataclass(frozen=True)
class FireTrigger:
    """Fire a specific card trigger that's currently eligible at the top pending.

    Declining a trigger is implicit (player picks a commit or another trigger
    instead) — there is no SkipTrigger action.
    """
    card_id: str


@dataclass(frozen=True)
class Stop:
    """End the current non-atomic action (pop the top pending frame).

    Legal only at certain pending frames (currently: outer space pendings
    where at least one sub-action has been committed). Future cards may
    enable Stop at inner frames; in that case it still pops only the top.
    """


# The Action union. Dispatch in `_apply_action` is by `isinstance`.
# Concrete commit subclasses are listed individually (CommitSubAction base
# itself is intentionally not in the union — only concrete options are
# what an agent can pick).
Action = Union[
    PlaceWorker,
    ChooseSubAction,
    CommitSow,
    CommitBake,
    CommitPlow,
    CommitBuildStable,
    CommitBuildRoom,
    CommitBuildMajor,
    CommitRenovate,
    CommitAccommodate,
    CommitBuildPasture,
    CommitHarvestConversion,
    CommitConvert,
    CommitBreed,
    FireTrigger,
    Stop,
]
