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
    `PendingBuildStable`, not by the agent at commit time).
    """
    row: int
    col: int


@dataclass(frozen=True)
class CommitBuildMajor(CommitSubAction):
    """Commit a Major Improvement purchase.

    For Cooking Hearth (major_idx 2 or 3), `return_fireplace_idx` can be
    set to 0 or 1 to pay by returning the named Fireplace instead of
    paying clay. For all other majors, `return_fireplace_idx` must be None.

    Dispatched via a special-case branch in `_apply_action`, NOT via the
    generic commit dispatcher (the conditional oven-wrapper push for
    Clay/Stone Oven is incompatible with the dispatcher's unconditional
    pop). See engine.py `_apply_action`.
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
    CommitBuildMajor,
    CommitRenovate,
    CommitAccommodate,
    FireTrigger,
    Stop,
]
