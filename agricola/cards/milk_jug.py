"""Milk Jug (minor improvement, A50; Base Revised; cost 1 clay).

Card text: "Each time any player (including you) uses the 'Cattle Market'
accumulation space, you get 3 food, and each other player gets 1 food."

Category 9 (opponent-action hook) — the first card that fires on ANOTHER player's
action. An automatic effect registered with `any_player=True`, so it fires for its
OWNER even on the opponent's Cattle Market turn (owner routing lives in
apply_auto_effects). Cattle Market is non-atomic, so its host frame
(PendingCattleMarket) is always present — no `register_action_space_hook` needed
(that index only gates the conditional hosting of ATOMIC spaces). Fires on the
**before**-phase: the ruling is that "each time you use [a space]" resolves
*before* the space's action, and the before-auto firing is the host frame's push
(SPACE_HOST_REFACTOR.md §11.1 — corrected from after_action_space during the
space-host firing migration, which moved every host's after-auto to its
work-complete boundary). On-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md
Category 9.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "milk_jug"


def _eligible(state: GameState, idx: int) -> bool:
    # idx is the OWNER (any player). Fire whenever the active use is Cattle Market.
    return state.pending_stack[-1].space_id == "cattle_market"


def _apply(state: GameState, idx: int) -> GameState:
    other = 1 - idx
    players = list(state.players)
    players[idx] = fast_replace(players[idx],
                                resources=players[idx].resources + Resources(food=3))
    players[other] = fast_replace(players[other],
                                  resources=players[other].resources + Resources(food=1))
    return fast_replace(state, players=tuple(players))


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1)))
register_auto("before_action_space", CARD_ID, _eligible, _apply, any_player=True)
