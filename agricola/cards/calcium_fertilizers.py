"""Calcium Fertilizers (minor improvement, A72; Artifex Expansion).

Card text: "Each time you use a 'Quarry' accumulation space, add 1 additional good
of the respective type to each of your planted fields growing a single type of
crop."
Cost: none. Prerequisite: No Field Tiles. VPs: 0. Not passing.

Category 3 (action-space hook, automatic effect) on the two atomic 'Quarry'
accumulation spaces (western_quarry / eastern_quarry).

"Each time you use a 'Quarry'" = the before_action_space host phase (the project's
"each time you use [space]" ruling). Timing is harmless here either way: a quarry
only yields stone, which the effect never touches — it only edits the player's
planted fields.

"A planted field growing a single type of crop" = a FIELD cell with EXACTLY ONE of
{grain > 0, veg > 0} (XOR). An unplanted field (grain == 0 and veg == 0) is skipped;
a field carrying BOTH grain and veg (possible if Cultivation ever sows both onto one
cell) is growing two types and is also skipped. "The respective type" means +1 to the
crop that field already grows — never the other. Crops live on Cell.grain / Cell.veg
(NOT player.resources).

The apparent prereq/effect tension — you may PLAY this only with zero field tiles, yet
it rewards fields — is intentional: the prerequisite is a play-time have-check, while
the effect benefits fields plowed and sown later.

CARD-FIELDS (ruling 45, 2026-07-12: "field" is the broader category and includes
card-fields): each owned card-field growing exactly one type of CROP also gains +1 of
that crop, on the stack holding it. Wood and stone are not crops, so a wood/stone
card-field (Wood Field, Rock Garden, Cherry Orchard) gains nothing, an empty
card-field gains nothing, and a mixed grain+veg card is excluded ("a single type of
crop") — the same XOR test as a grid cell, applied to the card's totals.

The PREREQUISITE stays GRID-ONLY: its printed wording is "No Field TILES", and per
ruling 32 (2026-07-06) a card-field is never a "field tile" — owning (even a planted)
card-field does not break the prereq.

Implemented as an automatic effect (register_auto, never a FireTrigger): it is a
guaranteed-beneficial grant with no choice or downside.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.state import GameState

CARD_ID = "calcium_fertilizers"
QUARRY_SPACES = frozenset({"western_quarry", "eastern_quarry"})


def _no_field_tiles(state: GameState, idx: int) -> bool:
    """Prerequisite: the player has zero FIELD cells in their farmyard.

    Grid-only on purpose — the printed wording is "No Field TILES", and per
    ruling 32 (2026-07-06) a card-field is never a field tile."""
    return not any(
        cell.cell_type is CellType.FIELD
        for row in state.players[idx].farmyard.grid
        for cell in row
    )


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in QUARRY_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    """Add 1 to the crop count of each planted field growing a single crop type.

    A field grows a single type iff exactly one of (grain > 0, veg > 0) is true; in
    that case +1 to that same crop. Fields never lie inside pastures, so the pasture
    cache rides along on the grid fast_replace (mirrors scythe_worker / the mechanical
    harvest take). Card-fields join by the same XOR test on the card's totals
    (ruling 45, 2026-07-12) — wood/stone are not crops, so those cards never qualify.
    """
    from agricola.cards.card_fields import (
        GOODS, card_field_stacks, card_holds, owned_card_fields, stack_with,
        stacks_to_store)

    p = state.players[idx]
    new_grid = []
    changed = False
    for row in p.farmyard.grid:
        new_row = []
        for cell in row:
            if cell.cell_type is CellType.FIELD:
                grain, veg = cell.grain, cell.veg
                if grain > 0 and veg == 0:
                    new_row.append(fast_replace(cell, grain=grain + 1))
                    changed = True
                    continue
                if veg > 0 and grain == 0:
                    new_row.append(fast_replace(cell, veg=veg + 1))
                    changed = True
                    continue
            new_row.append(cell)
        new_grid.append(tuple(new_row))
    # Card-fields (ruling 45, 2026-07-12): growing exactly one type of crop
    # (grain XOR veg — wood/stone are not crops) → +1 of that crop on the
    # stack holding it.
    card_state = p.card_state
    for cid in owned_card_fields(p):
        grain = card_holds(p, cid, "grain")
        veg = card_holds(p, cid, "veg")
        if (grain > 0) == (veg > 0):
            continue   # empty, wood/stone-only, or mixed grain+veg
        good = "grain" if grain > 0 else "veg"
        gi = GOODS.index(good)
        stacks = list(card_field_stacks(p, cid))
        for i, stack in enumerate(stacks):
            if stack[gi] > 0:
                stacks[i] = stack_with(stack, good, 1)
                break
        card_state = stacks_to_store(card_state, cid, stacks)
        changed = True
    if not changed:
        return state
    new_fy = fast_replace(p.farmyard, grid=tuple(new_grid))
    p = fast_replace(p, farmyard=new_fy, card_state=card_state)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(), prereq=_no_field_tiles, vps=0)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, QUARRY_SPACES)
