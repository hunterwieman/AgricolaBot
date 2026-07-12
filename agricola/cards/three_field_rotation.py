"""Three-Field Rotation (minor improvement, B61; Base Revised; free, 3-occupation prereq).

Card text: "At the start of the field phase of each harvest, if you have at least
1 grain field, 1 vegetable field, and 1 empty field, you get 3 food." No cost, no
printed VPs. Prerequisite: 3 occupations.

Harvest-window auto. The printed timing is "At the start of the field phase of
each harvest", which maps to harvest window #4, `start_of_field_phase` (the
window opened just before the field phase's crop take, inside the per-player
FIELD segment — ruling 3, 2026-07-03: each player resolves their whole FIELD
segment before the other, starting player first). A MANDATORY, choice-free
income → an automatic effect (register_auto on the `start_of_field_phase` window
event), fired by the harvest walk (`_process_band_window`) for the player BEFORE
the mechanical crop take of window #5 — so the eligibility read sees the fields
still sown, matching the card's "at the start of the field phase" timing. A FIELD
cell counts as a grain field if it holds grain, a vegetable field if it holds
veg, and an empty field if it holds neither.

Card-fields count for all three flags. User ruling 45 (2026-07-12), verbatim:
""field TILES" means the plowed fields on the farmyard grid; "field" is the
BROADER category and includes card-fields. So a card-field counts for
field-count readers — the Fields scoring category and any "you need N fields"
requirement — while per-TILE readers still exclude it (ruling 32 unchanged)."
This card reads "grain field" / "vegetable field" / "empty field" (not "field
tile"), so a grain-holding card-field satisfies the grain flag
(`crop_card_field_count(p, "grain") >= 1`), a veg-holding one the veg flag,
and a card-field holding nothing the empty flag
(`unplanted_card_field_count(p) >= 1`) — each card counting once, however
many stacks (ruling 47, 2026-07-12). A wood/stone-holding card-field is NONE
of the three: it holds no crop (not a grain or vegetable field) and it holds
something (not empty).
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "three_field_rotation"


def _eligible(state: GameState, idx: int) -> bool:
    from agricola.cards.card_fields import (   # local import: load-order safe
        crop_card_field_count,
        unplanted_card_field_count,
    )
    p = state.players[idx]
    has_grain = has_veg = has_empty = False
    for row in p.farmyard.grid:
        for cell in row:
            if cell.cell_type != CellType.FIELD:
                continue
            if cell.grain > 0:
                has_grain = True
            elif cell.veg > 0:
                has_veg = True
            else:
                has_empty = True
    # Card-fields (ruling 45, 2026-07-12): a grain/veg-holding card is a
    # grain/vegetable field; one holding nothing is an empty field. A
    # wood/stone-holding card is none of the three.
    has_grain = has_grain or crop_card_field_count(p, "grain") >= 1
    has_veg = has_veg or crop_card_field_count(p, "veg") >= 1
    has_empty = has_empty or unplanted_card_field_count(p) >= 1
    return has_grain and has_veg and has_empty


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=3))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, min_occupations=3)
register_auto("start_of_field_phase", CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "start_of_field_phase")
