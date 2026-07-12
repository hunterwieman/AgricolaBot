"""Gardener's Knife (minor improvement, A7; Artifex Expansion).

Card text: "You immediately get 1 food for each grain field you have and 1 grain
for each vegetable field you have."

Cost 1 wood, no prerequisite, no printed VPs. PASSING (traveling minor —
`passing_left='X'` in the catalog: after the on-play effect the card moves to
the opponent's hand).

Category 2 (on-play one-shot). A "grain field" / "vegetable field" is a field
that currently has grain / vegetables SOWN on it. On the grid that is counted by
what sits on the cell (``cell.grain > 0`` / ``cell.veg > 0``), not by
``cell_type`` alone: an unsown FIELD holds neither and counts as neither. A sown
field holds grain XOR veg (``_execute_sow`` fills a cell with 3 grain OR 2 veg,
never both), so the two counts never overlap. The grant is asymmetric — food per
grain-field, grain per veg-field — so the two outputs are not transposed.

Card-fields count too. User ruling 45 (2026-07-12), verbatim: ""field TILES"
means the plowed fields on the farmyard grid; "field" is the BROADER category
and includes card-fields. So a card-field counts for field-count readers — the
Fields scoring category and any "you need N fields" requirement — while
per-TILE readers still exclude it (ruling 32 unchanged)." This card reads
"grain field" / "vegetable field" (not "field tile"), so a card-field holding
grain adds 1 to the grain-field count and one holding vegetables adds 1 to the
vegetable-field count (`crop_card_field_count` — card-level, 1 per card
however many stacks, per ruling 47, 2026-07-12). A wood/stone-holding
card-field is neither a grain field nor a vegetable field.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "gardeners_knife"


def _on_play(state: GameState, idx: int) -> GameState:
    from agricola.cards.card_fields import (   # local import: load-order safe
        crop_card_field_count,
    )
    p = state.players[idx]
    grid = p.farmyard.grid
    # Grid fields + card-fields holding the crop (ruling 45, 2026-07-12:
    # "field" includes card-fields; 1 per card per ruling 47).
    grain_fields = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD and grid[r][c].grain > 0
    ) + crop_card_field_count(p, "grain")
    veg_fields = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD and grid[r][c].veg > 0
    ) + crop_card_field_count(p, "veg")
    p = fast_replace(
        p, resources=p.resources + Resources(food=grain_fields, grain=veg_fields)
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    passing_left=True,
    on_play=_on_play,
)
