"""Firewood Collector (occupation, A119; Base Revised; players 1+).

Card text: "Each time you use the 'Farmland', 'Grain Seeds', 'Grain Utilization',
or 'Cultivation' action space, at the end of that turn, you get 1 wood."

Category 3 (action-space hook, automatic income) on the dedicated **end_of_turn**
event ("at the end of that turn") — a mandatory, choice-free effect → an automatic
effect. The end_of_turn event fires at the worker-placement turn's completion
boundary (engine._apply_stop, when the OUTERMOST space-host frame is about to be
popped and the stack empties); at that moment the host frame is still on top, so the
eligibility reads its `space_id`. Grain Seeds is atomic, so it must be HOSTED when
this card is owned (register_action_space_hook) for the turn-end frame to exist; the
other three are non-atomic and always hosted. Played via Lessons; on-play is a
no-op. See CARD_IMPLEMENTATION_PLAN.md Category 3 / Unit 4 (end-of-turn event).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "firewood_collector"
SPACES = frozenset({"farmland", "grain_seeds", "grain_utilization", "cultivation"})


def _eligible(state: GameState, idx: int) -> bool:
    # The end_of_turn firing leaves the just-completed turn's outermost space-host
    # frame on top (popped right after); read its space_id.
    top = state.pending_stack[-1]
    return getattr(top, "space_id", None) in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(wood=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)
register_auto("end_of_turn", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)   # required so atomic Grain Seeds is hosted
