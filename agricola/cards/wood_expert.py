"""Wood Expert (occupation, D117; Dulcinaria Expansion; players 1+).

Card text: "When you play this card, you immediately get 2 wood. Each improvement
costs you up to 2 wood less, if you pay 1 food instead."

Two effects:
- On play: +2 wood (Category 1, gain goods).
- A passive cost CONVERSION on every IMPROVEMENT build — majors and minors, NOT rooms or
  renovations: optionally pay 1 food in place of up to 2 wood of the cost. Registered on the
  `build_major` and `play_minor` action_kinds (COST_MODIFIER_DESIGN.md). The food this
  introduces into a build cost is raised, when short, by the shared food-payment path
  (FOOD_PAYMENT_DESIGN.md): play-minor already routes through it, and build-major's
  food-shortfall guard (`_execute_build_major`) now does too.

`_expand` offers the unchanged cost plus the single substitution (a Pareto-min over goods
keeps both — food and wood are incomparable, so neither dominates). The substitution removes
`min(2, cost.wood)` wood and adds 1 food, so a 1-wood improvement saves 1 wood and a
>=2-wood improvement saves 2 — each for 1 food. Reducing 2 dominates reducing 1 for the same
food, so only the max reduction is offered. See CARD_IMPLEMENTATION_PLAN.md /
FOOD_PAYMENT_DESIGN.md §9.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_conversion
from agricola.cards.specs import register_occupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "wood_expert"


def _on_play(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(wood=2))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _expand(state, idx, ctx, cost: Resources) -> list[Resources]:
    out = [cost]
    if cost.wood >= 1:
        out.append(cost - Resources(wood=min(2, cost.wood)) + Resources(food=1))
    return out


register_occupation(CARD_ID, _on_play)
register_conversion("build_major", CARD_ID, _expand)
register_conversion("play_minor", CARD_ID, _expand)
