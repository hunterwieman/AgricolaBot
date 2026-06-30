"""Lumberjack (occupation, B119; Bubulcus Expansion; players 1+).

Card text: "You immediately get 1 wood. Additionally, place 1 wood on each of the
next round spaces, up to the number of fences you built. At the start of these
rounds, you get the wood."

Category 8 (deferred goods on round spaces) with an immediate on-play grant.
Played via Lessons; this is its on-play effect.

Two parts, in order:
1. **Immediate** +1 wood to the owner's supply.
2. **Deferred**: 1 wood on each of the next N round spaces, where N is the number
   of fence pieces the player has built (`helpers.fences_built`, each placed fence
   segment counts as one — NOT pastures, NOT buildable/in-supply). The "next round
   spaces" are rounds R+1, R+2, … (R = current round), so the range is
   `range(R+1, R+1+N)`; slot r-1 holds round r's goods (the engine's Well index
   convention). `schedule_resources` silently drops any round > 14, so a late-game
   play with many fences places wood on fewer than N spaces ("up to" / the
   remaining round spaces). N = 0 yields an empty range (the player still keeps the
   immediate +1 wood).

The immediate grant is applied first and the resulting state is fed into
`schedule_resources`, so the two on-card edits don't clobber each other
(`schedule_resources` reads `state.players[idx]` fresh).
"""
from __future__ import annotations

from agricola import helpers
from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "lumberjack"


def _on_play(state: GameState, idx: int) -> GameState:
    # 1. Immediate +1 wood.
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )

    # 2. Deferred: 1 wood on the next N round spaces (N = fences built).
    n = helpers.fences_built(p.farmyard)
    R = state.round_number
    return schedule_resources(state, idx, range(R + 1, R + 1 + n), Resources(wood=1))


register_occupation(CARD_ID, _on_play)
