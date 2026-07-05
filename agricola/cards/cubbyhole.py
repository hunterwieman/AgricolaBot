"""Cubbyhole (minor improvement, E52; Ephipparius Expansion; Food Provider).

Card text (verbatim): "For each room that you add to your house, place 1 food
from the general supply on this card. At the start of each feeding phase, you get
food equal to the amount on this card."
No clarifications printed.

Deck E, number 52. Cost "1 Reed,1 Wood/1 Clay" = 1 reed AND (1 wood OR 1 clay):
base `Cost(reed=1, wood=1)` with one `alt_costs` member `Cost(reed=1, clay=1)`
(the Barley Mill "X, Y/Z" idiom). Prerequisite: none. Printed VPs: 1. Not passing.

Two independent effects — a room-add BANK and a recurring feeding-phase PAYOUT:

- **"For each room that you add to your house, place 1 food ... on this card."**
  The food LIVES ON THE CARD — a persistent per-card bank held in the CardStore
  int `_FOOD_KEY`. "Add to your house" = a ROOM built during the game (never the
  two starting rooms, which are never inside a build session). Rooms are built
  through the multi-shot Build Rooms sub-action (Farm Expansion, and any future
  card grant), so this is the Rustic / Asparagus Gift before/after-snapshot idiom
  on the `build_rooms` sub-action host:
    - `before_build_rooms` (fires when PendingBuildRooms is pushed, before any
      room commit): snapshot the current ROOM count into the CardStore int
      `_SNAPSHOT_KEY`.
    - `after_build_rooms` (fires at the Proceed work-complete flip, after all room
      commits): add `n = current_room_count - snapshot` food to the on-card bank
      (`_FOOD_KEY += n`), then reset the snapshot to a canonical 0 (so two commit
      orders reaching the same farmyard converge). This delta only ever sees rooms
      built DURING a session — the starting rooms are excluded exactly as "add"
      requires. Both effects are mandatory, choiceless (a bank increment always
      fits), hence `register_auto`, not a declinable trigger.
  Placing food "from the general supply" onto the card is a pure bank increment —
  this engine models the supply as unbounded, so no supply pool is debited; only
  the CardStore counter grows.

- **"At the start of each feeding phase, you get food equal to the amount on this
  card."** A choice-free INCOME at harvest window #8 `start_of_feeding` (the
  window's defining phrase; HARVEST_WINDOWS_DESIGN.md §5 lists Cubbyhole's payout
  there). A mandatory, parameter-free food gain → `register_auto` on the
  `start_of_feeding` window event, fired by the harvest walk
  (`_process_simple_window`, window-major, starting player first) per owner — no
  frame. Window #8 resolves BEFORE the FEED payment (window #9), so the payout
  food is available to pay this harvest's feeding (the design-doc §5 "income
  before the payment decision" rule). The payout is RECURRING and NON-consuming:
  the printed text grants food equal to the on-card amount and never says to
  remove it, so the bank persists and pays out again every feeding phase (the
  amount only grows, as more rooms are added). Eligibility gates on the bank being
  > 0 so a 0-food no-op grant is never applied.

Played via a play-minor flow; no on-play effect (both effects are recurring /
event-driven). Card-only registries and the CardStore both default empty, so the
Family game is byte-identical and the C++ differential gates are untouched. See
CARD_AUTHORING_GUIDE.md §4 (deferred snapshot / CardStore) and rustic.py (the
room-count before/after idiom).
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "cubbyhole"
WINDOW_ID = "start_of_feeding"

# The per-session room-count snapshot (reset to 0 at the after-phase so commit
# orders converge) and the persistent on-card food bank (accumulated over the
# game, read by the feeding payout).
_SNAPSHOT_KEY = "cubbyhole_snapshot"
_FOOD_KEY = "cubbyhole_food"


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
    tell how many rooms this session added."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(_SNAPSHOT_KEY, _room_count(p)))
    return _update_player(state, idx, p)


def _bank_after(state: GameState, idx: int) -> GameState:
    """after_build_rooms: add 1 food to the on-card bank for each room built this
    session, then reset the snapshot to a canonical 0."""
    p = state.players[idx]
    before = p.card_state.get(_SNAPSHOT_KEY, 0)
    n = _room_count(p) - before
    banked = p.card_state.get(_FOOD_KEY, 0) + max(n, 0)
    p = fast_replace(
        p, card_state=p.card_state.set(_SNAPSHOT_KEY, 0).set(_FOOD_KEY, banked)
    )
    return _update_player(state, idx, p)


def _payout_eligible(state: GameState, idx: int) -> bool:
    """Only pay out when the on-card bank holds food (a 0-food grant is a no-op)."""
    return state.players[idx].card_state.get(_FOOD_KEY, 0) > 0


def _payout(state: GameState, idx: int) -> GameState:
    """start_of_feeding: gain food equal to the on-card amount. Non-consuming —
    the bank is unchanged, so it pays out again every feeding phase."""
    p = state.players[idx]
    amount = p.card_state.get(_FOOD_KEY, 0)
    p = fast_replace(p, resources=p.resources + Resources(food=amount))
    return _update_player(state, idx, p)


register_minor(
    CARD_ID,
    cost=Cost(Resources(reed=1, wood=1)),
    alt_costs=(Cost(Resources(reed=1, clay=1)),),
    vps=1,
)  # no on-play effect
register_auto("before_build_rooms", CARD_ID, lambda state, idx: True, _snapshot_before)
register_auto("after_build_rooms", CARD_ID, lambda state, idx: True, _bank_after)
register_auto(WINDOW_ID, CARD_ID, _payout_eligible, _payout)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
