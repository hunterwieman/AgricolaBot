"""Town Hall (minor improvement, E48; Ephipparius Expansion; players -).

Card text (verbatim): "In the feeding phase of each harvest, if you live in a
clay or stone house, you get 1 or 2 food, respectively."

Cost: 2 Wood, 2 Clay. Printed VPs: 2. No prerequisite. Not passing.
Category: Food Provider.

Feeding-income auto. "In the feeding phase of each harvest, you get X food" is a
choice-free INCOME, so it is an automatic effect (`register_auto`, not a
declinable trigger) on the ``"feeding"`` window. The feeding-income seam fires it
per player, starting player first, at the FEED entry — BEFORE the payment
decision — so the food it grants is payable (HARVEST_WINDOWS_DESIGN.md §5; the
``register_harvest_window_hook`` docstring names Town Hall as a member).

The amount is conditioned on house material, read at the FEED entry:
- WOOD house  -> the "if you live in a clay or stone house" condition is false ->
  no food (the effect is ineligible; the auto is a no-op).
- CLAY house  -> 1 food.
- STONE house -> 2 food ("1 or 2 food, respectively").

House material can only ever be raised (WOOD -> CLAY -> STONE via renovation), and
renovation happens in the WORK phase, never during a harvest, so the material is
fixed for the duration of a feeding phase — reading it at the FEED entry is exact.

Card-only state is empty in the Family game, so it stays byte-identical and the
C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "town_hall"

# Food granted per house material (WOOD grants nothing — the condition fails).
_FOOD_BY_MATERIAL = {
    HouseMaterial.CLAY: 1,
    HouseMaterial.STONE: 2,
}


def _food_amount(state: GameState, idx: int) -> int:
    return _FOOD_BY_MATERIAL.get(state.players[idx].house_material, 0)


def _eligible(state: GameState, idx: int) -> bool:
    """Eligible iff the player lives in a clay or stone house (a wood house gets
    nothing)."""
    return _food_amount(state, idx) > 0


def _apply(state: GameState, idx: int) -> GameState:
    """+1 food (clay house) or +2 food (stone house) at the FEED entry, before
    the payment decision."""
    food = _food_amount(state, idx)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2, clay=2)), vps=2)
register_auto("feeding", CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "feeding")
