"""Herbal Garden (minor improvement, E36; Ephipparius Expansion; cost 1 Wood; prereq
1 Pasture; printed 2 VP).

Card text: "From now on, at least one of your pastures must contain no animals."

A standing capacity RESTRICTION: one of the player's pastures must stay empty from now
on, which lowers effective animal capacity. It is registered as an "empty-pasture" card
(`register_empty_pasture`) whose qualifying predicate is "any pasture" — so `extract_slots`
reserves (drops) the smallest-capacity pasture from the accommodation capacity list
(dropping the smallest is optimal for the player: a larger remaining capacity multiset
never houses fewer animals). Because the caches downstream key on `extract_slots`' outputs,
the reduction can never serve a stale frontier.

Playing it can shrink a full farm's capacity mid-game (an animal now has nowhere to go if
every pasture was occupied), so `_on_play` flags the accommodation barrier — the engine
re-checks the fit at the next decision boundary and surfaces the keep-or-cook choice if the
animals no longer fit (the Milking Place idiom). The prerequisite (>= 1 pasture) and the
printed 2 VP are static.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_empty_pasture
from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "herbal_garden"


def _prereq(state: GameState, idx: int) -> bool:
    """At least one pasture (a HAVE-check at play time)."""
    return len(state.players[idx].farmyard.pastures) >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    """Capacity just shrank (one pasture must now be empty): flag the accommodation
    barrier so the engine re-checks the fit and evicts if the animals no longer fit."""
    p = state.players[idx]
    if p.animals != Animals():   # Animals has no __bool__ — compare, don't truth-test
        p = fast_replace(p, animals_need_accommodation=True)
        state = fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))
    return state


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), prereq=_prereq, vps=2,
               on_play=_on_play)
register_empty_pasture(CARD_ID, lambda pasture: True)   # any pasture may be the empty one
