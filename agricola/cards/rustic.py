"""Rustic (occupation, B111; Bubulcus Expansion; players 1+).

Card text: "For each clay room you build, you get 2 food and 1 bonus point. (this
does not apply to stone rooms and renovated wood rooms.)"

A per-room build hook. The card pays out per CLAY room *built* — not stone rooms,
and not the wood rooms a clay/stone house once had (those became clay/stone via
renovation, which the parenthetical explicitly excludes). Two things follow:

- **Per room, not per action.** The `after_build_rooms` event fires ONCE per
  build-rooms session, not once per room (Build Rooms is a single action — never
  fire between pieces). So a boolean "did the house build any room?" test (the
  Roughcaster shape) is not enough here: Rustic must know HOW MANY rooms this
  session built. We take a before/after snapshot of the room count (exactly the
  shape Shepherd's Crook uses for newly-enclosed pastures) and pay `n = after −
  before` times: +2 food and +1 point per room.

- **Clay rooms only.** Rooms always match the current house material at build
  time, so a session's new rooms are clay rooms iff the house is clay when they
  are built. Eligibility therefore reads `house_material == CLAY`. Stone-house
  rooms (built after a clay→stone renovate) and the original wood rooms a house
  was renovated *out of* are excluded exactly as the text demands — a renovated
  wood room is never re-counted because the count delta only ever sees rooms built
  *during* a build-rooms session, never the rooms the house already had.

The food is granted immediately at the hook. The bonus points have no immediate-VP
mechanism in the engine, so they are BANKED into the per-card CardStore (the Big
Country pattern: compute at play/hook time, store the running total, read it back
at scoring) and accumulated across every clay-room-building session over the game.

Mechanism — a before/after pair of AUTOMATIC effects on the build_rooms sub-action
host:

  - `before_build_rooms` (fires when PendingBuildRooms is pushed, before any room
    commit): snapshot the current room count into the per-card CardStore.
  - `after_build_rooms` (fires at the Proceed work-complete flip, after all room
    commits): if the house is clay, grant 2 food + bank 1 point for each room built
    this session (`current_count − snapshot`), then reset the snapshot to a
    canonical 0 (so two commit orders reaching the same farmyard converge).

Played via Lessons; its on-play is a no-op. Card-only state (the CardStore snapshot
+ banked VP) defaults empty, so the Family game is byte-identical and the C++ gates
are untouched. See CARD_IMPLEMENTATION_PLAN.md (build/renovate hook + banked VP) and
CARD_AUTHORING_GUIDE.md §4 (deferred snapshot / CardStore).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import CellType, HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "rustic"

FOOD_PER_ROOM = 2
POINTS_PER_ROOM = 1

# Two distinct CardStore keys: the per-session room-count snapshot (reset to 0 at
# the after-phase so commit orders converge) and the banked end-game points
# (accumulated across every clay-room session).
_SNAPSHOT_KEY = "rustic_snapshot"
_VP_KEY = "rustic_vp"


def _room_count(player) -> int:
    """Number of ROOM cells on the player's farmyard grid (mirrors scoring.py)."""
    grid = player.farmyard.grid
    return sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )


def _update_player(state: GameState, idx: int, p) -> GameState:
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _snapshot_before(state: GameState, idx: int) -> GameState:
    """before_build_rooms: record the pre-action room count so the after-hook can
    tell how many rooms this session built."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(_SNAPSHOT_KEY, _room_count(p)))
    return _update_player(state, idx, p)


def _eligible_after(state: GameState, idx: int) -> bool:
    # Rooms built this session are clay rooms iff the house is clay at build time.
    return state.players[idx].house_material == HouseMaterial.CLAY


def _grant_after(state: GameState, idx: int) -> GameState:
    """after_build_rooms (house is clay): pay 2 food + bank 1 point per room built
    this session, then reset the snapshot to a canonical 0."""
    p = state.players[idx]
    before = p.card_state.get(_SNAPSHOT_KEY, 0)
    n = _room_count(p) - before
    if n <= 0:
        # Defensive: no rooms recorded as new (cannot normally happen — the hook
        # only fires when a room was built). Reset the snapshot and grant nothing.
        p = fast_replace(p, card_state=p.card_state.set(_SNAPSHOT_KEY, 0))
        return _update_player(state, idx, p)
    banked = p.card_state.get(_VP_KEY, 0) + POINTS_PER_ROOM * n
    p = fast_replace(
        p,
        resources=p.resources + Resources(food=FOOD_PER_ROOM * n),
        card_state=p.card_state.set(_SNAPSHOT_KEY, 0).set(_VP_KEY, banked),
    )
    return _update_player(state, idx, p)


def _score(state: GameState, idx: int) -> int:
    # The banked bonus points (1 per clay room built over the game).
    return state.players[idx].card_state.get(_VP_KEY, 0)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_build_rooms", CARD_ID, lambda state, idx: True, _snapshot_before)
register_auto("after_build_rooms", CARD_ID, _eligible_after, _grant_after)
register_scoring(CARD_ID, _score)
