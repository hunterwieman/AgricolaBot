"""Oven Firing Boy (occupation, B108; Base Revised; players 1+).

Card text: "Each time you use a wood accumulation space, you get an additional
'Bake Bread' action." In the 2-player game the only wood accumulation space is
Forest.

Category 4 (action-space hook, granted sub-action). An OPTIONAL trigger whose
apply_fn pushes the existing PendingBakeBread primitive — including Potter
Ceramics firing inside it for free, since the bake-bread machinery is unchanged.
Eligibility gates on a bake actually being usable (`_can_bake_bread`: a baking
improvement + grain, or a card extension), so it never grants an unresolvable
bake. Fires on the wood space's BEFORE-phase: "each time you use [space]" fires
before the space's own effect (the Trigger-Timing ruling). The bake needs grain,
not the space's wood, so before is observationally correct; the wood-consuming
"immediately after" cards (Mushroom Collector, Basket) stay on the after-phase.
On-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md Category 4.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.legality import _can_bake_bread
from agricola.pending import PendingBakeBread, push
from agricola.state import GameState

CARD_ID = "oven_firing_boy"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in WOOD_ACCUMULATION_SPACES
            and _can_bake_bread(state, state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingBakeBread(player_idx=idx, initiated_by_id="card:oven_firing_boy"))


register_occupation(CARD_ID, lambda state, idx: state)
register("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
