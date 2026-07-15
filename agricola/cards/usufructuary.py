"""Usufructuary (occupation, E157; Ephipparius Expansion; players 4+).

Card text (verbatim): "When you play this card as your first occupation, you
immediately get 1 food for every other occupation in play (by any player), up to a
maximum of 7 food."

Category 2 (on-play one-shot), gated on being the owner's FIRST occupation. When
`on_play` runs the card is already in the owner's `occupations` frozenset (it is
moved to the tableau before `on_play`, see `resolution._execute_play_occupation` /
`tutor.py`), so "as your first occupation" means the owner has exactly ONE
occupation at this instant: `len(owner.occupations) == 1`. Played as a later
occupation (already holding others), the card grants nothing.

"1 food for every OTHER occupation in play (by any player)" counts every occupation
in both players' tableaus except this card itself. This card is one of the in-play
occupations (it is already in the owner's tableau), so the count is
`(total occupations across both players) - 1`, capped at a maximum of 7 food. Food
always fits, so this is a plain `on_play` grant, mirroring `consultant.py`.
"Immediately" names the standard card-play instant.

No stored state. Card-only registries default empty -> Family byte-identical, C++
gates untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "usufructuary"
_MAX_FOOD = 7


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    # Only fires as the owner's FIRST occupation (the card is already in the
    # tableau here, so "first" == exactly one occupation owned).
    if len(p.occupations) != 1:
        return state
    total_occupations = sum(len(pl.occupations) for pl in state.players)
    # "every OTHER occupation in play" excludes this card itself.
    food = min(_MAX_FOOD, total_occupations - 1)
    if food <= 0:
        return state
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
