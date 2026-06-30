"""Cooperative Plower (occupation, B90; Bubulcus Expansion; players 1+).

Card text: "Each time you use the 'Farmland' action space while the 'Grain Seeds'
action space is occupied, you can plow 1 additional field."

Category 4 (action-space hook, granted sub-action), with an extra board-state
condition. A grant is the player's choice -> an OPTIONAL trigger (register, not
register_auto) whose apply_fn pushes the existing PendingPlow primitive on top of
the Farmland host. The grant is gated on TWO things beyond once-per-use:

  - the "Grain Seeds" action space is OCCUPIED — checked directly as
    `get_space(board, "grain_seeds").workers != (0, 0)`. (NOT `not _is_available(...)`,
    which is also False when a space is UNREVEALED; grain_seeds is a permanent space
    revealed from setup, so in practice it is always revealed, but the workers-check is
    the robust occupancy predicate.)
  - a plow is actually possible (`_can_plow`), so we never grant a dead-end sub-action.

"Each time you use [space]" fires in the BEFORE phase, before Farmland's own plow
(the Trigger-Timing ruling). Once-per-use via the host's `triggers_resolved`.
Farmland is non-atomic (always hosted by PendingSubActionSpace), so no
`register_action_space_hook` is needed. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.state import GameState, get_space

CARD_ID = "cooperative_plower"


def _grain_seeds_occupied(state: GameState) -> bool:
    return get_space(state.board, "grain_seeds").workers != (0, 0)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id == "farmland"
            and _grain_seeds_occupied(state)
            and _can_plow(state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
