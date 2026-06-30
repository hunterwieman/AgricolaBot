"""Field Watchman (occupation, C90; Consul Dirigens Expansion; players 1+).

Card text: "Each time you use the 'Grain Seeds' action space, you can also plow
1 field."

Category 4 (action-space hook, granted sub-action). A grant is the player's
choice → an OPTIONAL trigger (register, not register_auto) whose apply_fn pushes
the existing PendingPlow primitive. Eligibility gates on a plow actually being
possible (a free, plowable cell), so we never grant a dead-end sub-action.

"Each time you use [space]" (no "after"/"immediately after") fires on the space's
BEFORE-phase — before Grain Seeds' own +1-grain effect (the Trigger-Timing
ruling). Grain Seeds is an ATOMIC space (in resolution.ATOMIC_HANDLERS), so it is
unhosted unless a hook claims it: register_action_space_hook is REQUIRED here, or
the before_action_space event would never fire. Once-per-use is enforced by the
host's triggers_resolved set (CARD_ID not in triggers_resolved). Mirrors Assistant
Tiller (the same grant on the Day Laborer space). Played via Lessons; on-play is a
no-op. See CARD_IMPLEMENTATION_PLAN.md Category 4.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.state import GameState

CARD_ID = "field_watchman"
SPACES = frozenset({"grain_seeds"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in SPACES
            and _can_plow(state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:field_watchman"))


register_occupation(CARD_ID, lambda state, idx: state)
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
