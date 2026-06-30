"""Hod (minor improvement, A77; Artifex Expansion; cost 1 wood).

Card text: "When you play this card, you immediately get 1 clay. Each time any
player (including you) uses the 'Pig Market' accumulation space, you immediately
get 2 clay."

Two effects:
- on-play: +1 clay (immediate; Category 2 one-shot) — the rammed_clay shape.
- an opponent-action hook (Category 9): each time ANY player uses Pig Market, the
  owner gets 2 clay. Registered as an `any_player=True` automatic effect so it
  fires for its OWNER even on the opponent's Pig Market turn (owner routing lives
  in apply_auto_effects, which passes the OWNER as `idx`). Unlike Milk Jug, Hod
  gives nothing to the active/other player — only the owner gains; the boar from
  Pig Market still goes to the active player via normal resolution.

Pig Market is non-atomic, so its host frame (PendingPigMarket) is always present
— no `register_action_space_hook` is needed (that index only gates conditional
hosting of ATOMIC spaces). The hook fires on the **before**-phase: the ruling is
that "each time you use [a space]" resolves *before* the space's action, and the
before-auto firing is the host frame's push (SPACE_HOST_REFACTOR.md §11.1),
matching Milk Jug. See CARD_IMPLEMENTATION_PLAN.md Category 9.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "hod"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(clay=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int) -> bool:
    # idx is the OWNER (any player). Fire whenever the active use is Pig Market.
    return state.pending_stack[-1].space_id == "pig_market"


def _apply(state: GameState, idx: int) -> GameState:
    # Only the OWNER gains 2 clay (no opponent gain — unlike Milk Jug).
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(clay=2))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play)
register_auto("before_action_space", CARD_ID, _eligible, _apply, any_player=True)
