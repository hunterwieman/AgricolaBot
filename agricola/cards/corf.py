"""Corf (minor improvement, B79; Bubulcus Expansion; cost 1 reed).

Card text: "Each time any player (including you) takes at least 3 stone from an
accumulation space, you get 1 stone from the general supply."

The only stone accumulation spaces are the two quarries (Western/Eastern Quarry),
both atomic. The threshold is read off the host frame's `taken` — the stone the
acting player actually obtained from the quarry (the Resources delta stamped across
the take at Proceed). `_resolve_building_accumulation` sweeps the entire `accumulated`
Resources on use (no partial take), so `top.taken.stone` is exactly the amount that
was taken. A bare "each time ... takes" fires on the **after**-phase, after the take.

This fires for its OWNER even on the OPPONENT's quarry turn, so it is an
any-player automatic effect AND requires `register_action_space_hook(...,
any_player=True)` — the quarries are atomic, so without the hook no host frame is
pushed on the opponent's placement and the after-auto would have nothing to fire
on. On-play is a no-op (the hook IS the effect). Stone has no capacity limit, so
the +1 stone grant is always safe. See CARD_IMPLEMENTATION_PLAN.md Category 9
(opponent-action hook) + Category 3 (action-space hook).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "corf"

# The only stone accumulation spaces are the two quarries (both atomic).
QUARRY_SPACES = frozenset({"western_quarry", "eastern_quarry"})


def _eligible(state: GameState, idx: int) -> bool:
    # idx is the OWNER (any player). The active use must be a quarry, and the stone
    # the acting player took from it (the host frame's `taken`) must be >= 3.
    top = state.pending_stack[-1]
    if top.space_id not in QUARRY_SPACES:
        return False
    return top.taken.stone >= 3


def _apply(state: GameState, idx: int) -> GameState:
    # Owner gets 1 stone from the general supply (no capacity limit on stone).
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(stone=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(reed=1)))
register_auto("after_action_space", CARD_ID, _eligible, _apply, any_player=True)
register_action_space_hook(CARD_ID, QUARRY_SPACES, any_player=True)
