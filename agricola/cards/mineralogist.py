"""Mineralogist (occupation, B122; Bubulcus Expansion; players 1+).

Card text: "Each time you use a clay/stone accumulation space, you also get 1 of
the other good, stone/clay."

So using a *clay* accumulation space (Clay Pit) also yields 1 *stone*, and using a
*stone* accumulation space (Western Quarry / Eastern Quarry) also yields 1 *clay* —
the bonus is always the OTHER good. This is the space-dependent twin of Geologist
(whose bonus is always clay, space-independent): here `_apply` must branch on the
space being used.

Category 3 (action-space hook, automatic income) — fires on three atomic spaces.
Played via Lessons; on-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md Category 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "mineralogist"

# Clay Pit is the clay space; the two quarries are the only stone spaces.
MINERALOGIST_SPACES = frozenset({"clay_pit", "western_quarry", "eastern_quarry"})

# Each space grants the OTHER good: clay space -> +1 stone, stone spaces -> +1 clay.
_BONUS = {
    "clay_pit": Resources(stone=1),
    "western_quarry": Resources(clay=1),
    "eastern_quarry": Resources(clay=1),
}


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in MINERALOGIST_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    bonus = _BONUS[state.pending_stack[-1].space_id]
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + bonus)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, MINERALOGIST_SPACES)
