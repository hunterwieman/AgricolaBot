"""Plant Fertilizer (minor improvement, C8; Corbarius Expansion; traveling).

Card text: "In each field with exactly 1 good, you can immediately place 1
additional good of the same type."
Cost: none. Prerequisite: none. VPs: 0. TRAVELING (passing) card.

Clarification (card): "Boar held on unplanted fields (from Mud Patch A011) do not
apply for this effect." Mud Patch is not implemented and not in the current pool,
so no boar-on-field handling is needed — only FIELD cells holding a crop count are
ever touched here.

Category 2 (on-play one-shot) + passing. The effect is applied automatically at
play time: it is a guaranteed-beneficial pure-goods grant with no choice or
downside, so it needs no declinable FireTrigger frame (the project's "pure-goods
you-can grant with no downside may stay automatic" convention, matching Calcium
Fertilizers).

THE THRESHOLD: "a field with exactly 1 good" means a FIELD cell holding EXACTLY
ONE crop token of a single type — grain == 1 (and veg == 0), XOR veg == 1 (and
grain == 0). This is stricter than "a field growing a single crop type" (which
would be grain > 0 XOR veg > 0): a freshly-sown field holds 3 grain or 2 veg and
does NOT qualify. Only a field harvested down to its last token does (each
harvest_field decrements a planted crop by 1). A field carrying both grain and veg
is two types and is also skipped (the XOR guards handle it). The result of
fertilizing is 2 of that crop type.

Crops live on Cell.grain / Cell.veg (NOT player.resources). Fields never lie inside
a pasture, so the cached pasture decomposition rides along on the grid fast_replace
(mirrors Calcium Fertilizers / the mechanical harvest take).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.state import GameState

CARD_ID = "plant_fertilizer"


def _on_play(state: GameState, idx: int) -> GameState:
    """For each FIELD holding exactly 1 crop token of one type, add a second.

    grain == 1 (xor) veg == 1 is the eligibility; the matched crop goes to 2. Any
    other field — unplanted, >1 token, or two crop types — is left untouched.
    """
    p = state.players[idx]
    new_grid = []
    changed = False
    for row in p.farmyard.grid:
        new_row = []
        for cell in row:
            if cell.cell_type is CellType.FIELD:
                if cell.grain == 1 and cell.veg == 0:
                    new_row.append(fast_replace(cell, grain=2))
                    changed = True
                    continue
                if cell.veg == 1 and cell.grain == 0:
                    new_row.append(fast_replace(cell, veg=2))
                    changed = True
                    continue
            new_row.append(cell)
        new_grid.append(tuple(new_row))
    if not changed:
        return state
    new_fy = fast_replace(p.farmyard, grid=tuple(new_grid))
    p = fast_replace(p, farmyard=new_fy)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(), passing_left=True, on_play=_on_play)
