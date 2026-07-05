"""Straw Manure (minor improvement, D70; Dulcinaria Expansion; Crop Provider).

Card text (verbatim): "Before the field phase of each harvest, you can pay 1
grain from your supply to add 1 vegetable to each of up to 2 vegetable fields."

Cost: none (card JSON cost=null). Printed VPs: 0 (vps=null). Prerequisite:
"2 Fields". Not passing.

TIMING — window #3 ``before_field_phase`` (HARVEST_WINDOWS_DESIGN.md §1 ladder
lists Straw Manure as the sole census member of window #3, and §11 "Fields mutate
outside the field phase" names it explicitly: "Straw Manure adds vegetables at
#3"). The printed "Before the field phase of each harvest" maps to the ladder's
``before_field_phase`` window, which opens inside the per-player FIELD segment
(ruling 3, 2026-07-03: the starting player resolves their WHOLE FIELD segment —
windows #3..#7 — before the other player's begins, so the two players' #3 frames
never coexist) and BEFORE window #5's mechanical crop take. Adding vegetables here
means they are on the fields when the take runs, so the take then harvests one
vegetable from each boosted field like any other planted field — exactly the
printed sequence.

DECLINABLE ("you can") — an optional trigger surfaced on the per-player
``PendingHarvestWindow`` frame; ``Proceed`` declines. Once per window is automatic
(the frame's ``triggers_resolved`` records the fire, so it cannot fire twice in
one harvest's window #3).

THE CHOICE — "add 1 vegetable to each of up to 2 vegetable fields" is a choice of
WHICH vegetable fields (and how many, 1 or 2) to boost; the grain cost is a flat 1
regardless of how many fields are chosen. The fields are NOT interchangeable — the
identity of the boosted cells changes the farmyard state (and what window #5's take
then reads per field) — so the choice is modeled as a play-VARIANT trigger
(``register_play_variant_trigger``) enumerating the actual target-cell subsets, not
merely a count. Each variant is one non-empty subset (size 1 or 2) of the player's
vegetable fields, encoded as ``"r-c"`` cells joined by ``"|"`` in row-major order.
Declining (adding to zero fields, which pays 1 grain for nothing) is never a
distinct variant — it is the frame's ``Proceed``, so no grain is spent when nothing
is added.

"Vegetable field" — a FIELD cell that currently holds at least 1 vegetable
(``cell.cell_type == FIELD and cell.veg > 0``); a grain field or an empty field is
not a legal target. "Add 1 vegetable" increments that cell's ``veg`` by 1 (fields
carry no hard crop cap in this engine; the 2-veg sowing limit bounds only the sow
action, not card effects that add crops).

"2 Fields" prerequisite — a play-time HAVE-check that the player owns at least 2
FIELD cells (any field tiles, planted or not; the same shape as Cesspit's "2
Fields"), never spent. Distinct from the veg-field targets the trigger reads at
harvest time.

Card-only state is untouched (no CardStore, no scoring term), so the Family game is
byte-identical and the C++ differential gates are unaffected.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "straw_manure"
WINDOW_ID = "before_field_phase"

_GRAIN_COST = 1
_MAX_TARGETS = 2


def _prereq_two_fields(state: GameState, idx: int) -> bool:
    """Prerequisite "2 Fields": at least 2 FIELD cells (any field tiles, planted
    or empty; the crop is irrelevant — matches Cesspit's "2 Fields")."""
    grid = state.players[idx].farmyard.grid
    fields = sum(
        1 for row in grid for cell in row if cell.cell_type is CellType.FIELD
    )
    return fields >= 2


def _veg_field_cells(state: GameState, idx: int) -> list[tuple[int, int]]:
    """The player's vegetable fields (FIELD cells holding >= 1 veg), row-major."""
    grid = state.players[idx].farmyard.grid
    return [
        (r, c)
        for r in range(len(grid))
        for c in range(len(grid[r]))
        if grid[r][c].cell_type is CellType.FIELD and grid[r][c].veg > 0
    ]


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Usable iff the player can pay the 1 grain AND has at least one vegetable
    field to add to (adding to zero fields is never worth 1 grain and is not a
    legal "use" — it is the frame's Proceed). Ownership and the once-per-window
    guard are enforced by the host enumerator (``_owns`` + ``triggers_resolved``)."""
    if state.players[idx].resources.grain < _GRAIN_COST:
        return False
    return len(_veg_field_cells(state, idx)) >= 1


def _variants(state: GameState, idx: int) -> list[str]:
    """Every non-empty subset (size 1 or up to 2) of the player's vegetable
    fields, encoded as ``"r-c"`` cells joined by ``"|"``. Empty when the grain is
    unaffordable or there is no vegetable field (the enumerator then surfaces no
    fire, only Proceed)."""
    if state.players[idx].resources.grain < _GRAIN_COST:
        return []
    cells = _veg_field_cells(state, idx)
    out: list[str] = []
    for a in cells:
        out.append(f"{a[0]}-{a[1]}")                      # boost exactly this one
    for i, a in enumerate(cells):
        for b in cells[i + 1:]:                           # boost this pair
            out.append(f"{a[0]}-{a[1]}|{b[0]}-{b[1]}")
    return out


def _parse(variant: str) -> list[tuple[int, int]]:
    cells = []
    for token in variant.split("|"):
        r, c = token.split("-")
        cells.append((int(r), int(c)))
    return cells


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Pay 1 grain from supply; add 1 vegetable to each chosen vegetable field.

    The chosen cells are always current vegetable fields (the variant enumerator
    only ever produced veg-field cells for this state), and there are at most 2 of
    them (``_MAX_TARGETS``). The grain cost is flat regardless of the target
    count."""
    targets = _parse(variant)
    assert 1 <= len(targets) <= _MAX_TARGETS, f"illegal straw_manure targets {variant!r}"
    p = state.players[idx]
    resources = p.resources - Resources(grain=_GRAIN_COST)
    grid = p.farmyard.grid
    target_set = set(targets)
    new_grid = tuple(
        tuple(
            fast_replace(cell, veg=cell.veg + 1) if (r, c) in target_set else cell
            for c, cell in enumerate(row)
        )
        for r, row in enumerate(grid)
    )
    p = fast_replace(
        p, resources=resources, farmyard=fast_replace(p.farmyard, grid=new_grid)
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(), prereq=_prereq_two_fields)
# Optional play-variant trigger on window #3 (before_field_phase): pay 1 grain,
# add 1 veg to each of up to 2 chosen vegetable fields; once per harvest.
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
