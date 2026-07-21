"""Fatstock Stretcher (minor improvement, D56; Dulcinaria Expansion; players -).

Card text: "Each time you turn a sheep or wild boar into food using a cooking
improvement, you get 1 additional food."

Cost: 1 Wood. Printed VPs: 0. No prerequisite, kept (not passing).
Category: Food Provider.

Implemented as **+1 to the cooking rates for sheep and wild boar** (user ruling
2026-07-21): every site that cooks an animal via a cooking improvement — the
harvest feeding payment frontier, food-liquidation for card play costs, the
animal-market overflow conversion, and the breeding make-room conversion —
reads `helpers.cooking_rates`, so a +1 on the sheep/boar components there IS
"+1 food each time you turn a sheep or wild boar into food using a cooking
improvement", uniformly across all of them with no per-site wiring. The bonus
is injected through `register_cooking_rate_bonus` (agricola/cards/
cooking_mods.py), folded at the end of `cooking_rates` for the card's owner.

**Only where the conversion already exists** (user ruling 2026-07-21): the +1
applies per-component iff that component's base rate > 0 — no cooking
improvement means no cook, so no bonus. The user's worked rate examples, on
the (sheep, boar, cattle) triple:

    (2, 2, 3) -> (3, 3, 3)     # Fireplace: both conversions exist, both +1
    (0, 0, 0) -> (0, 0, 0)     # no improvement: no cook, no bonus
    (3, 0, 5) -> (4, 0, 5)     # hypothetical boar-less cooker: sheep-only +1

Scope (user ruling 2026-07-21): the bonus attaches ONLY to cooking-improvement
conversions — the `cooking_rates` table. A card's own exchange of an animal for
food (not via a cooking improvement) gets nothing; that is automatic, since
such exchanges do not read `cooking_rates`. The cattle and veg components are
never modified.
"""
from __future__ import annotations

from agricola.cards.cooking_mods import register_cooking_rate_bonus
from agricola.cards.specs import register_minor
from agricola.resources import Cost, Resources

CARD_ID = "fatstock_stretcher"


def _bonus(state, owner_idx: int, base: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """+1 sheep and +1 boar rate, each only where the base conversion exists
    (base rate > 0 — user ruling 2026-07-21); cattle and veg untouched."""
    return (1 if base[0] > 0 else 0, 1 if base[1] > 0 else 0, 0, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_cooking_rate_bonus(CARD_ID, _bonus)
