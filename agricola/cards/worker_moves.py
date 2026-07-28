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
    registered fn self-gates on its own card's ownership/state.

    Also the chokepoint where a returned worker leaves the standing-worker ledger:
    returning home ANONYMIZES (ruling 79 item 2 — the number is voided; re-placing
    mints fresh), so the entry at the vacated location is dropped here. The
    single-chokepoint convention is what keeps the ledger correct for every future
    return effect with no per-card bookkeeping."""
    state = _drop_standing_worker(state, idx, space_id)
    for _card_id, fn in WORKER_RETURNED_HOOKS:
        state = fn(state, idx, space_id)
    return state


def _drop_standing_worker(state: GameState, idx: int, location: str) -> GameState:
    """Remove player `idx`'s standing-worker ledger entry at `location` (a return
    home voided its number). No-op when no entry exists (every Family call — the
    ledger is card-only and empty there); ≤1 entry by invariant (the only
    multi-marker case, a wish space's parent+newborn, holds one NUMBERED worker)."""
    p = state.players[idx]
    matches = [e for e in p.standing_workers if e[1] == location]
    if not matches:
        return state
    assert len(matches) == 1, (
        f"two numbered workers of player {idx} at {location!r}: {matches}")
    p = fast_replace(p, standing_workers=tuple(
        e for e in p.standing_workers if e != matches[0]))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _move_board_worker(state: GameState, idx: int, from_space: str,
                       to_space: str) -> GameState:
    """Move one of player `idx`'s board worker markers from `from_space` to
    `to_space`. The vacated source re-opens (occupancy is solely worker presence —
    the Tea Time ruling); the destination gains the worker even if occupied (a
    jump card that requires an unoccupied destination enforces that in its own
    eligibility — Swagman explicitly pierces).

    The mover's standing-worker ledger entry is rewritten to the destination —
    an on-board relocation PRESERVES the worker's number (ruling 79 item 3), and
    this chokepoint is what makes that true for every relocation effect (the
    jump family, Straw Hat, Archway) with no per-card bookkeeping."""
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
    state = fast_replace(state, board=fast_replace(
        state.board, action_spaces=tuple(spaces)))

    # Rewrite the ledger entry's location; the number is untouched (numbers stay
    # ascending, so the tuple order is preserved). ≤1 entry by invariant; 0 only
    # for an unnumbered marker (a wish space's newborn — no relocation source
    # today; harmless no-op if one ever moves).
    p = state.players[idx]
    matches = [e for e in p.standing_workers if e[1] == from_space]
    if matches:
        assert len(matches) == 1, (
            f"two numbered workers of player {idx} at {from_space!r}: {matches}")
        num = matches[0][0]
        p = fast_replace(p, standing_workers=tuple(
            (n, to_space if n == num else loc) for n, loc in p.standing_workers))
        state = fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(len(state.players))))
    return state


def relocation_destinations(state: GameState, idx: int) -> list:
    """The legal "an unoccupied action space" destinations for player `idx`'s
    relocation (rulings 83/86 item 5 — Straw Hat, Archway): every BOARD space
    that is strictly unoccupied (`legality.space_occupied` — the occupancy-
    READING definition; an exemption card never un-occupies) and legal per its
    own placement predicate probed as the mover, plus every reachable CARD
    space (owner-only = own cards; `for_all` = either player's; a toll gates
    the arrival — ruling 86 items 1/8) — one entry per placement variant, a
    plain space_id or a ("card:<id>", picks) pair for wide card spaces.
    Foreclosure (`last_use_committed`) is the CALLER's gate — each mover's
    ruling names its own suppressed branch."""
    from agricola.cards.card_spaces import (
        CARD_ACTION_SPACES, board_space_tolls_due, card_space_occupied,
        played_card_owner, toll_payable,
    )
    from agricola.legality import CARD_GAME_LEGALITY, space_occupied
    from agricola.resources import Cost, Resources

    def _board_tolls_ok(sid):
        due = board_space_tolls_due(state, idx, sid)
        if not due:
            return True
        total = Resources()
        for _c, _o, toll in due:
            total = total + toll.resources
        return toll_payable(state, idx, Cost(resources=total))

    probe = fast_replace(state, current_player=idx)
    out: list = [
        sid for sid, predicate in CARD_GAME_LEGALITY.items()
        if not space_occupied(state, sid) and predicate(probe)
        and _board_tolls_ok(sid)
    ]
    for card_id in sorted(CARD_ACTION_SPACES):
        spec = CARD_ACTION_SPACES[card_id]
        owner = played_card_owner(state, card_id)
        if owner is None:
            continue
        if owner != idx and not spec.for_all:
            continue
        if (owner != idx and spec.toll is not None
                and not toll_payable(state, idx, spec.toll)):
            continue
        if card_space_occupied(state, card_id):
            continue
        dest = f"card:{card_id}"
        for picks in spec.placeable_fn(state, idx, owner):
            out.append(dest if picks is None else (dest, picks))
    return out


def _clear_card_space_marker(state: GameState, idx: int, card_id: str) -> GameState:
    """Take player `idx`'s worker marker OFF a card space (a relocation is
    leaving — no `people_home` credit, unlike a return home)."""
    p = state.players[idx]
    key = f"card_space_worker:{card_id}"
    n = p.card_state.get(key, 0)
    assert n >= 1, f"no worker of player {idx} on card space {card_id!r}"
    store = p.card_state.remove(key) if n == 1 else p.card_state.set(key, n - 1)
    p = fast_replace(p, card_state=store)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def relocate_and_use(state: GameState, idx: int, from_space: str,
                     to_space: str, picks=None) -> GameState:
    """The jump: move the acting worker `from_space` -> `to_space`, fire the
    relocated hooks (stored referents follow the person), then run the
    destination's full action. Mints no placement number (ruling 79 — the worker
    keeps its number). Callers (the jump cards' apply fns) have already verified
    eligibility: the destination's own action must be legal (never a dead-end) and
    any unoccupied-destination condition holds at the trigger time (ruling 81
    item 2).

    A `to_space` of the form "card:<id>" is a CARD action space destination
    (ruling 86 item 5 — Straw Hat / Archway may move onto card spaces): the
    worker leaves the board for the card's occupancy marker (the mover's
    CardStore), the ledger entry follows, and the use is hosted via
    `engine.initiate_card_space_use` — `picks` is that use's wide payload
    (Collector's goods choice), None for a plain card space and always None
    for a board destination."""
    if from_space.startswith("card:"):
        # CARD-space source (Archway's parked person): the marker leaves the
        # card and the ledger entry follows; the board never held this worker.
        state = _clear_card_space_marker(state, idx, from_space.split(":", 1)[1])
        p = state.players[idx]
        matches = [e for e in p.standing_workers if e[1] == from_space]
        if matches:
            assert len(matches) == 1
            num = matches[0][0]
            new_loc = to_space if to_space.startswith("card:") else to_space
            p = fast_replace(p, standing_workers=tuple(
                (n, new_loc if n == num else loc)
                for n, loc in p.standing_workers))
            state = fast_replace(state, players=tuple(
                p if i == idx else state.players[i]
                for i in range(len(state.players))))
        if not to_space.startswith("card:"):
            dst = get_space(state.board, to_space)
            workers = tuple(w + (1 if j == idx else 0)
                            for j, w in enumerate(dst.workers))
            from agricola.constants import SPACE_INDEX
            spaces = list(state.board.action_spaces)
            spaces[SPACE_INDEX[to_space]] = fast_replace(dst, workers=workers)
            state = fast_replace(state, board=fast_replace(
                state.board, action_spaces=tuple(spaces)))
        for _card_id, fn in WORKER_RELOCATED_HOOKS:
            state = fn(state, idx, from_space, to_space)
        from agricola.engine import initiate_card_space_use, initiate_space_use
        if to_space.startswith("card:"):
            return initiate_card_space_use(state, idx,
                                           to_space.split(":", 1)[1], picks)
        assert picks is None, "picks is a card-space-destination payload only"
        return initiate_space_use(state, to_space)
    if to_space.startswith("card:"):
        state = _move_board_worker_to_card(state, idx, from_space,
                                           to_space.split(":", 1)[1])
        for _card_id, fn in WORKER_RELOCATED_HOOKS:
            state = fn(state, idx, from_space, to_space)
        from agricola.engine import initiate_card_space_use   # avoid import cycle
        return initiate_card_space_use(state, idx,
                                       to_space.split(":", 1)[1], picks)
    assert picks is None, "picks is a card-space-destination payload only"
    state = _move_board_worker(state, idx, from_space, to_space)
    for _card_id, fn in WORKER_RELOCATED_HOOKS:
        state = fn(state, idx, from_space, to_space)
    from agricola.engine import initiate_space_use   # local: avoid import cycle
    return initiate_space_use(state, to_space)


def _move_board_worker_to_card(state: GameState, idx: int, from_space: str,
                               card_id: str) -> GameState:
    """Move one of player `idx`'s board worker markers onto a CARD action
    space: decrement the vacated board space (it re-opens — occupancy is
    solely worker presence) and rewrite the mover's standing-worker ledger
    entry to "card:<id>" (the number is preserved — ruling 79 item 3). The
    on-card occupancy marker itself is set by `initiate_card_space_use` (the
    same division as a card-space placement: bookkeeping here, marker+host
    there)."""
    src = get_space(state.board, from_space)
    assert src.workers[idx] >= 1, (
        f"no worker of player {idx} on {from_space!r} to move")

    def _bump(workers, i, delta):
        return tuple(w + (delta if j == i else 0) for j, w in enumerate(workers))

    spaces = list(state.board.action_spaces)
    from agricola.constants import SPACE_INDEX
    spaces[SPACE_INDEX[from_space]] = fast_replace(
        src, workers=_bump(src.workers, idx, -1))
    state = fast_replace(state, board=fast_replace(
        state.board, action_spaces=tuple(spaces)))

    p = state.players[idx]
    matches = [e for e in p.standing_workers if e[1] == from_space]
    if matches:
        assert len(matches) == 1, (
            f"two numbered workers of player {idx} at {from_space!r}: {matches}")
        num = matches[0][0]
        p = fast_replace(p, standing_workers=tuple(
            (n, f"card:{card_id}" if n == num else loc)
            for n, loc in p.standing_workers))
        state = fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(len(state.players))))
    return state
