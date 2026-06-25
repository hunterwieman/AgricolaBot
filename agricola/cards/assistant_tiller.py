"""Assistant Tiller (occupation, B91; Base Revised; players 1+).

Card text: "Each time you use the 'Day Laborer' action space, you can also plow
1 field."

Category 4 (action-space hook, granted sub-action). A grant is the player's
choice → an OPTIONAL trigger (register, not register_auto) whose apply_fn pushes
the existing PendingPlow primitive. Eligibility gates on a plow actually being
possible (a free, plowable cell), so we never grant a dead-end sub-action. Fires
on Day Laborer's after-phase (the +2 food first, then the optional plow). Played
via Lessons; on-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md Category 4.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.state import GameState

CARD_ID = "assistant_tiller"
SPACES = frozenset({"day_laborer"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in SPACES
            and _can_plow(state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:assistant_tiller"))


register_occupation(CARD_ID, lambda state, idx: state)
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
