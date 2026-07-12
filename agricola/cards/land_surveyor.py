"""Land Surveyor (occupation, E107; Ephipparius Expansion; players 1+).

Card text (verbatim): "In the field phase of each harvest, if you have at least
2/4/6/7 fields, you get 1/2/3/4 food."

A during-window flat state-reader. "Fields" here are the player's FIELD tiles on
the farmyard grid (`cell_type == CellType.FIELD` — the scoring.py `num_fields`
idiom) PLUS their owned card-fields (`card_field_count`, agricola/cards/
card_fields.py) — both count whether or not they currently hold a crop, and the
count is independent of what the crop take harvested. Ruling 45 (2026-07-12),
verbatim: '"field TILES" means the plowed fields on the farmyard grid; "field" is
the BROADER category and includes card-fields. So a card-field counts for
field-count readers — the Fields scoring category and any "you need N fields"
requirement — while per-TILE readers still exclude it (ruling 32 unchanged).'
Per ruling 47 (2026-07-12) a multi-stack card-field (Wood Field: 2 stacks, Rock
Garden: 3) is "considered 1 field" — it moves this count by exactly 1, however
many stacks it has.

Slash template — a single graduated income (not four parallel gains): the highest
threshold the player meets sets the payout.
  >= 7 fields -> 4 food
  >= 6 fields -> 3 food
  >= 4 fields -> 2 food
  >= 2 fields -> 1 food
  <  2 fields -> 0 food

Timing — "in the field phase of each harvest". Because the income reads standing
farm state (owner's field tiles), not what the crop take harvested, it is a plain
"field_phase" window auto (HARVEST_WINDOWS_DESIGN.md §4d — flat state-readers are
order-insensitive and anchored pre-take; the take never adds/removes field tiles).
A MANDATORY, choice-free income -> an automatic effect (`register_auto` on the
"field_phase" window event), fired by `engine._field_phase_step` via
`apply_auto_effects` before the mechanical crop take, once per player per harvest.
The gate is scoped to the harvest field phase by riding the "field_phase" window
event itself (ruling 12: "in the field phase OF EACH HARVEST" gates on the harvest
field phase); a card-played field phase does not fire window autos.

Played via Lessons; on-play is a no-op (a pure recurring-income occupation).
Stateless — no CardStore — so the Family game is byte-identical and the C++ gates
are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "land_surveyor"


def _num_fields(state: GameState, idx: int) -> int:
    """Count player `idx`'s fields (crop-agnostic): FIELD tiles on the farmyard
    grid plus owned card-fields (ruling 45, 2026-07-12: "field" includes
    card-fields; ruling 47: a multi-stack card-field counts exactly 1)."""
    from agricola.cards.card_fields import card_field_count  # local: load-order safe
    p = state.players[idx]
    grid = p.farmyard.grid
    return sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    ) + card_field_count(p)


def _food(n_fields: int) -> int:
    """The graduated payout for `n_fields` field tiles (highest met threshold)."""
    if n_fields >= 7:
        return 4
    if n_fields >= 6:
        return 3
    if n_fields >= 4:
        return 2
    if n_fields >= 2:
        return 1
    return 0


def _eligible(state: GameState, idx: int) -> bool:
    return _food(_num_fields(state, idx)) > 0


def _apply(state: GameState, idx: int) -> GameState:
    food = _food(_num_fields(state, idx))
    if food == 0:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)  # no on-play effect
register_auto("field_phase", CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "field_phase")
