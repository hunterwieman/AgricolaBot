"""Same-worker movement machinery — the JUMP (ruling 81) and the move/return
notification registries.

**The jump** (Swagman A129, Full Peasant B130, Large-Scale Farmer B150, Junior Artist
B152, Job Contract C23): "use space Y with the same person, immediately after using
space X". Ruled shape (ruling 81 item 1, 2026-07-26): the jump is a trigger in the
SOURCE's `after_action_space` window — takeable before other after-window triggers —
and firing it moves the acting worker's board marker from source to destination and
runs the DESTINATION's full action (`engine.initiate_space_use`): the destination's
frames stack above the source's after-window host, resolve completely (its hosts,
sub-decisions, and card events — a relocation IS a use and fires the destination's
before/after events), and the walk returns to the source's after-window for any
remaining triggers. The user endorses this as the most faithful implementation of the
cards, not merely the convenient one.

Under the PHYSICAL ordinal (ruling 79): the move mints NO placement number — the worker
keeps the number of the placement that started the turn, which is still the current
`placements_this_round` value (the jump happens inside that worker's own turn), so
ordinal-reading cards on the destination read correctly with no extra state.

**The two notification registries** exist because a moved or returned worker can
invalidate ANOTHER card's stored state:

- `WORKER_RELOCATED_HOOKS` — fired by `relocate_and_use` with (from_space, to_space).
  Consumer: Henpecked Husband, whose CardStore record of "the first person you placed"
  is a SPACE; when that person jumps, the record follows the person (its printed
  effect targets the person, wherever it now stands).
- `WORKER_RETURNED_HOOKS` — fired by every effect that returns a placed worker home
  (Sheep Inspector's board return, Henpecked Husband's return, Tea Time). Consumer:
  Job Contract, whose Day-Laborer "considered occupied" marker must clear when the
  chained person is returned home from Lessons — ruling 81 item 3: a return frees
  BOTH spaces. **Convention: any future effect that returns a placed worker home must
  call `notify_worker_returned`** — the same single-chokepoint discipline as
  `grant_animals`.

Both registries are card-only and empty in the Family game (no Family card registers),
so every fire site is an O(1) no-op there.
"""
from __future__ import annotations

from typing import Callable

from agricola.replace import fast_replace
from agricola.state import GameState, get_space

# card_id -> fn(state, idx, from_space, to_space) -> state
WORKER_RELOCATED_HOOKS: list[tuple[str, Callable]] = []
# card_id -> fn(state, idx, space_id) -> state
WORKER_RETURNED_HOOKS: list[tuple[str, Callable]] = []


def register_worker_relocated(card_id: str, fn: Callable) -> None:
    """Register a reaction to one of the player's placed workers MOVING between
    spaces without going home (called at card-module import)."""
    WORKER_RELOCATED_HOOKS.append((card_id, fn))


def register_worker_returned(card_id: str, fn: Callable) -> None:
    """Register a reaction to one of the player's placed workers being returned
    HOME mid-round (called at card-module import)."""
    WORKER_RETURNED_HOOKS.append((card_id, fn))


def notify_worker_returned(state: GameState, idx: int, space_id: str) -> GameState:
    """Every return-a-worker-home effect calls this with the vacated space. Each
    registered fn self-gates on its own card's ownership/state."""
    for _card_id, fn in WORKER_RETURNED_HOOKS:
        state = fn(state, idx, space_id)
    return state


def _move_board_worker(state: GameState, idx: int, from_space: str,
                       to_space: str) -> GameState:
    """Move one of player `idx`'s board worker markers from `from_space` to
    `to_space`. The vacated source re-opens (occupancy is solely worker presence —
    the Tea Time ruling); the destination gains the worker even if occupied (a
    jump card that requires an unoccupied destination enforces that in its own
    eligibility — Swagman explicitly pierces)."""
    src = get_space(state.board, from_space)
    assert src.workers[idx] >= 1, (
        f"no worker of player {idx} on {from_space!r} to move")
    dst = get_space(state.board, to_space)

    def _bump(workers, i, delta):
        return tuple(w + (delta if j == i else 0) for j, w in enumerate(workers))

    spaces = list(state.board.action_spaces)
    from agricola.constants import SPACE_INDEX
    spaces[SPACE_INDEX[from_space]] = fast_replace(
        src, workers=_bump(src.workers, idx, -1))
    spaces[SPACE_INDEX[to_space]] = fast_replace(
        dst, workers=_bump(dst.workers, idx, +1))
    return fast_replace(state, board=fast_replace(
        state.board, action_spaces=tuple(spaces)))


def relocate_and_use(state: GameState, idx: int, from_space: str,
                     to_space: str) -> GameState:
    """The jump: move the acting worker `from_space` -> `to_space`, fire the
    relocated hooks (stored referents follow the person), then run the
    destination's full action. Mints no placement number (ruling 79 — the worker
    keeps its number). Callers (the jump cards' apply fns) have already verified
    eligibility: the destination's own action must be legal (never a dead-end) and
    any unoccupied-destination condition holds at the trigger time (ruling 81
    item 2)."""
    state = _move_board_worker(state, idx, from_space, to_space)
    for _card_id, fn in WORKER_RELOCATED_HOOKS:
        state = fn(state, idx, from_space, to_space)
    from agricola.engine import initiate_space_use   # local: avoid import cycle
    return initiate_space_use(state, to_space)
