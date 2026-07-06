"""Craft Brewery (minor improvement, C63; Corbarius Expansion; Food Provider).

Card text (verbatim): "In the feeding phase of each harvest, you can use this
card to exchange 1 grain from your supply plus 1 grain from a field for 2 bonus
points and 4 food."
Cost: 2 Wood, 1 Clay. No prerequisite. VPs: none printed (the points are
earned, not printed). Not passing.

A recurring, optional, once-per-harvest goods-to-food conversion offered during
HARVEST_FEED — the HARVEST_CONVERSIONS seam, whose "in the feeding phase of each
harvest" timing is exactly the printed wording (Beer Keg, A62, is the same-worded
precedent). Firing it spends 1 grain from the SUPPLY plus 1 grain off a FIELD,
banks 2 bonus points, and adds 4 food to the supply. Because conversions fire
before the feeding payment (`CommitConvert`), the 4 food arrives in time to pay
this harvest's feeding cost — the printed in-feeding timing.

THE WHICH-FIELD CHOICE — per the user ruling of 2026-07-06, the choice of which
field the second grain comes off surfaces WIDE, encoded by FIELD HEIGHT: one
`CommitHarvestConversion(conversion_id, variant="h<X>")` per grain-count group
present among the player's FIELD cells (X in {1,2,3}), because fields holding the
same number of grain are interchangeable — the only strategically distinct
choices are the heights. The canonical field of the chosen group is the first in
row-major scan order. `_variants` returns the sorted height tags (e.g.
["h1","h3"]); an empty list (no planted grain field) withholds the conversion
entirely, and the seam's affordability gate on `input_cost` (1 supply grain)
withholds it when the supply half cannot be paid.

NOT A HARVEST — per the user ruling of 2026-07-03 (ruling 12's lexicon: a
"harvest" is a harvesting OCCASION), removing the grain from the field this way
is an exchange, not a harvest: no harvesting occasion is emitted, so no
harvest-consequence card (Grain Sieve etc.) reacts to it. The side effect
decrements the cell directly, never routing through `field_take`.

MECHANICS — one `HarvestConversionSpec` entry: `input_cost=Resources(grain=1)`
(the supply grain) and `food_out=4` are handled by the seam's executor
(`_execute_harvest_conversion` debits the cost and adds the food before invoking
the side effect); `_side_effect` handles ONLY the field grain (decrement the
first row-major field holding the chosen height) and the 2 banked points. The
once-per-harvest limit comes free from `harvest_conversions_used`; declining is
implicit (commit `CommitConvert` without firing — the seam has no explicit skip).

The bonus points cannot be granted immediately (there is no immediate-VP
mechanism), so each fire banks 2 points in a per-card CardStore counter (across
all six harvests) and the scoring term reads the count back at end-game — the
banked-VP idiom (Beer Keg / Elephantgrass Plant). Do NOT set vps= for them (that
would score a printed keep VP; these are earned).

Card-only state (the CardStore int + the variant-bearing registry entry) is
empty/unowned in the Family game, so it stays byte-identical and the C++ gates
are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "craft_brewery"


def _owns(state: GameState, idx: int) -> bool:
    return CARD_ID in state.players[idx].minor_improvements


def _variants(state: GameState, idx: int) -> list:
    """One variant tag per grain-height group present among the player's FIELD
    cells — "h<X>" = "take the field grain from a field holding X grain" (user
    ruling 2026-07-06: same-height fields are interchangeable, so the choice is
    surfaced by height, not by cell). Sorted ascending; empty when no field
    holds grain (the conversion is withheld — the printed exchange needs the
    field grain, not just the supply grain)."""
    heights = {
        cell.grain
        for row in state.players[idx].farmyard.grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain >= 1
    }
    return [f"h{h}" for h in sorted(heights)]


def _side_effect(state: GameState, idx: int, variant: str) -> GameState:
    """Remove 1 grain from the first row-major FIELD holding the chosen height
    (the group's canonical field — user ruling 2026-07-06) and bank 2 bonus
    points. The supply grain and the 4 food are the spec's input_cost/food_out,
    already applied by the seam's executor before this runs. NOT a harvest:
    the cell is decremented directly, no occasion is emitted (ruling 12's
    lexicon, 2026-07-03)."""
    height = int(variant[1:])
    p = state.players[idx]

    target = None
    for r, row in enumerate(p.farmyard.grid):
        for c, cell in enumerate(row):
            if cell.cell_type == CellType.FIELD and cell.grain == height:
                target = (r, c)
                break
        if target is not None:
            break
    assert target is not None, (
        f"craft_brewery: no field holding {height} grain (variant {variant!r})"
    )

    tr, tc = target
    grid = tuple(
        tuple(
            fast_replace(cell, grain=cell.grain - 1) if (r, c) == (tr, tc) else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p,
        farmyard=fast_replace(p.farmyard, grid=grid),
        card_state=p.card_state.set(CARD_ID, banked + 2),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    """Sum of bonus points banked across all harvests (2 per fire)."""
    return state.players[idx].card_state.get(CARD_ID, 0)


# Cost 2 wood + 1 clay; no prerequisite; no printed VP (points are earned).
register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2, clay=1)))

# The once-per-harvest exchange during HARVEST_FEED: 1 supply grain (input_cost)
# + 1 field grain (side effect, field chosen by height variant) -> 4 food
# (food_out) + 2 banked bonus points (side effect).
register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(grain=1),
    food_out=4,
    is_owned_fn=_owns,
    side_effect_fn=_side_effect,
    variants_fn=_variants,
))

register_scoring(CARD_ID, _score)
