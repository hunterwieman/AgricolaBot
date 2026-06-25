"""Wood Cutter (occupation, A116; Base Revised; players 1+).

Card text: "Each time you use a wood accumulation space, you get 1 additional
wood." In the 2-player game the only wood accumulation space is Forest.

Category 3 (action-space hook, automatic income). A mandatory, choice-free
effect → an automatic effect (register_auto), not a FireTrigger. Order is
irrelevant (+1 wood is independent of the space's own wood pickup), so it rides
the `before_action_space` event. Played via Lessons; its on-play is a no-op.
See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "wood_cutter"

# Wood accumulation spaces this card fires on. 2-player: Forest only (Copse /
# Grove are 3–4-player board-extension spaces, never on the 2-player board).
WOOD_SPACES = frozenset({"forest"})


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at a before_action_space host frame; read the space uniformly via
    # the host frame's `space_id` (works for atomic and non-atomic hosts alike).
    return state.pending_stack[-1].space_id in WOOD_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(wood=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_SPACES)
