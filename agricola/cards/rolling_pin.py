"""Rolling Pin (minor improvement, D52; Dulcinaria Expansion; players -).

Card text: "In the returning home phase of each round, if you have more clay
than wood in your supply, you get 1 food."
Cost: 1 Wood. Prerequisite: 1 Occupation. VPs: 0. Not passing.

Category: Food Provider. "In the returning home phase of each round" -> the
round-end ladder's ``returning_home`` window (ruling 49, 2026-07-12: the
returning-home phase is the round's LAST phase, distinct from and PRECEDING the
harvest). The text says "each round" with no exclusion, so the effect is
UNCONDITIONED on the round kind and fires on harvest rounds too, BEFORE the
harvest runs (the round-end ladder is walked before the WORK -> harvest detour)
-- exactly the Swimming Class window (this card is its simpler sibling: a flat
+1 food instead of banked points).

"you get 1 food" is mandatory and choice-free -> an automatic effect
(`register_auto` on the "returning_home" event), never a FireTrigger (ruling 21,
2026-07-05: a mandatory choice-free effect is an AUTO, never a forced offer). The
condition "more clay than wood in your supply" reads the player's own supply
(``PlayerState.resources``) at the pre-reset returning-home window; the
returning-home reset does not touch goods, so pre/post-reset supply is identical
and the window's firing point is unambiguous for this condition.

Played via an improvement space; the play itself is a no-op (the per-round window
effect is the whole card), so on_play stays the default. The "1 Occupation"
prerequisite is a ``min_occupations=1`` have-check (NOT a cost); the 1 Wood is
the spendable cost.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "rolling_pin"


def _eligible(state: GameState, idx: int) -> bool:
    """At the returning-home window: the player has more clay than wood in
    supply (``resources`` is the player's supply)."""
    r = state.players[idx].resources
    return r.clay > r.wood


def _apply(state: GameState, idx: int) -> GameState:
    """Grant 1 food to the owner."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)),
               min_occupations=1, vps=0)
register_auto("returning_home", CARD_ID, _eligible, _apply)
