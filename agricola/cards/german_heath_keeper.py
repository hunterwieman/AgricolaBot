"""German Heath Keeper (occupation, C164; Corbarius Expansion; players 4+).

Card text: "Each time any player (including you) uses the 'Pig Market' accumulation
space, you get 1 sheep from the general supply."

An any-player action hook (the Milk Jug shape) on Pig Market: fired for the OWNER
whenever ANY player (the owner included) uses the space. A bare "each time any
player uses" → the BEFORE phase (Trigger-Timing ruling); the reward is a flat
animal grant, so before-timing is correct. Mandatory and choiceless → an automatic
effect (register_auto) with ``any_player=True``.

The 1 sheep is granted through helpers.grant_animals — the single choke point for
decision-free animal gains — so it lands on the owner even over capacity and the
accommodation barrier (engine._reconcile_accommodation) surfaces the keep-which
choice on overflow. Adding directly to ``player.animals`` would bypass that barrier
and silently exceed capacity (CARD_AUTHORING_GUIDE.md §9).

Pig Market is NON-ATOMIC (its initiator always pushes a PendingPigMarket host and
fires before_action_space), so no register_action_space_hook is needed. On-play is
a no-op. Card-game only (ownership-gated registries), so the Family trace and the
C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.helpers import grant_animals
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "german_heath_keeper"


def _eligible(state: GameState, owner: int) -> bool:
    return state.pending_stack[-1].space_id == "pig_market"


def _apply(state: GameState, owner: int) -> GameState:
    return grant_animals(state, owner, Animals(sheep=1))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply, any_player=True)
# NO register_action_space_hook: Pig Market is non-atomic (always hosted).
