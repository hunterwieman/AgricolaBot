"""Comb and Cutter (minor improvement, deck E #59; Ephipparius; cost 1 wood).

Card text: "Each time you use the \"Day Laborer\" action space, you get 1
additional food for each sheep on the \"Sheep Market\" accumulation space, up to
a maximum of 4 additional food." No prerequisite, no printed VPs.

Category 3 (action-space hook, automatic income) on the atomic Day Laborer
space. The reward scales with the sheep sitting on the Sheep Market accumulation
space at the moment Day Laborer is used, capped at +4 food. It is read in the
BEFORE window (fired at the host push, before Day Laborer's own 2-food effect
runs). Sheep Market stores its animals as the scalar `accumulated_amount`; if it
is unrevealed or empty the count is 0 -> +0 food (the auto still fires, adding
nothing). Because Day Laborer is atomic, the space must be explicitly hosted via
`register_action_space_hook` or no frame is pushed and the auto never fires.
Played via an improvement space; its effect is the hook, so on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "comb_and_cutter"
SPACES = frozenset({"day_laborer"})
MAX_BONUS = 4


def _eligible(state: GameState, idx: int) -> bool:
    # Fires on every Day Laborer use; the bonus is 0 when Sheep Market is empty.
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    sheep = get_space(state.board, "sheep_market").accumulated_amount
    bonus = min(sheep, MAX_BONUS)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=bonus))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
