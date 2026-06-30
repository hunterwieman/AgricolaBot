"""Pan Baker (occupation, A122; Artifex Expansion; players 1+).

Card text: "Each time you use the 'Grain Utilization' action space, you also get
2 clay and 1 wood."

Category 3 (action-space hook, automatic income). A mandatory, choice-free
grant -> an automatic effect (register_auto), not a FireTrigger. "Each time you
use [space]" has no "immediately after" qualifier, so by the trigger-timing
ruling it fires on the `before_action_space` event; order is irrelevant here
since +clay/+wood is independent of the space's own sow/bake effects (same
rationale Wood Cutter documents).

grain_utilization is a NON-atomic space, so unlike the Wood Cutter template we do
NOT call register_action_space_hook (that index only governs whether ATOMIC
spaces get a host frame). `_initiate_grain_utilization` always pushes
PendingGrainUtilization and fires apply_auto_effects("before_action_space", ...)
at the push, so the auto already fires. Played via Lessons; its on-play is a
no-op. See CARD_BATCH_TRIAGE.md A122 / CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "pan_baker"


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at a before_action_space host frame; read the space uniformly via
    # the host frame's `space_id` (the grain_utilization parent frame's space_id
    # is "grain_utilization", from initiated_by_id="space:grain_utilization").
    return state.pending_stack[-1].space_id == "grain_utilization"


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(clay=2, wood=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
