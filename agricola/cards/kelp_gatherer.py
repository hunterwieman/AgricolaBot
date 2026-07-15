"""Kelp Gatherer (occupation, E160; Ephipparius Expansion; players 4+).

Card text: "Each time another player uses the 'Fishing' accumulation space, they
get 1 additional food and you get 1 vegetable."

An opponent-action hook (the Milk Jug shape) on Fishing, restricted to ANOTHER
player's use: when the actor is not the owner, the actor gets +1 food and the owner
gets +1 vegetable. A bare "each time another player uses" → the BEFORE phase
(Trigger-Timing ruling); both rewards are flat, so before-timing is correct.
Mandatory and choiceless → an automatic effect (register_auto) with
``any_player=True`` so it runs for its owner on the opponent's Fishing turn.

Eligibility requires ``actor != owner`` (the owner's OWN use grants nothing — the
text is "another player"). The actor is the host frame's ``player_idx``; the owner
is the any-player index the effect runs for.

Fishing is ATOMIC (agricola/resolution.py ATOMIC_HANDLERS), so it must be hosted
even on the OPPONENT's turn — hence register_action_space_hook(..., any_player=True)
(routing to ANY_PLAYER_HOOK_CARDS so should_host_space wraps it on either player's
use). On-play is a no-op. Card-game only (ownership-gated registries), so the
Family trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "kelp_gatherer"


def _eligible(state: GameState, owner: int) -> bool:
    top = state.pending_stack[-1]
    # Only ANOTHER player's Fishing use fires this (owner's own use grants nothing).
    return top.space_id == "fishing" and top.player_idx != owner


def _apply(state: GameState, owner: int) -> GameState:
    actor = state.pending_stack[-1].player_idx   # != owner (eligibility guaranteed)
    players = list(state.players)
    players[actor] = fast_replace(
        players[actor], resources=players[actor].resources + Resources(food=1))
    players[owner] = fast_replace(
        players[owner], resources=players[owner].resources + Resources(veg=1))
    return fast_replace(state, players=tuple(players))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply, any_player=True)
# Fishing is atomic → host it on either player's use (any_player index).
register_action_space_hook(CARD_ID, {"fishing"}, any_player=True)
