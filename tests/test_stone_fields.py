"""Engine-level tests for stone on board field tiles (Stone Clearing C6).

The card's errata (user ruling 2026-07-20): the stone-holding field is harvested
NORMALLY — 1 stone per field phase, to supply — and the field is "considered
planted until the stone is gone": it is NOT empty (not sowable, not an
"unplanted field" for any card prerequisite or effect) and IS planted for
"planted field" readers. `Cell.field_empty` / `Cell.field_planted` are the
single definitions both directions; this file pins the engine half (the model,
sow legality, the take, canonical byte-identity, and the swept reader helpers).
The producing card module (`stone_clearing.py`) carries its own on-play tests.
"""
from __future__ import annotations

import json

from agricola import canonical
from agricola.constants import CellType
from agricola.legality import _can_sow
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell


def _set_cell(state, idx, r, c, cell):
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    grid[r][c] = cell
    fy = fast_replace(p.farmyard, grid=tuple(tuple(row) for row in grid))
    p = fast_replace(p, farmyard=fy)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _with_resources(state, idx, res):
    p = fast_replace(state.players[idx], resources=res)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# ---------------------------------------------------------------------------
# The Cell predicates — the single definition of empty / planted
# ---------------------------------------------------------------------------

def test_cell_predicates():
    bare = Cell(cell_type=CellType.FIELD)
    assert bare.field_empty and not bare.field_planted
    stone = Cell(cell_type=CellType.FIELD, stone=1)
    assert not stone.field_empty and stone.field_planted
    grain = Cell(cell_type=CellType.FIELD, grain=2)
    assert not grain.field_empty and grain.field_planted
    # A non-field cell is neither, whatever it holds.
    empty_cell = Cell()
    assert not empty_cell.field_empty and not empty_cell.field_planted


# ---------------------------------------------------------------------------
# Sowing — a stone-holding field is not a sow target
# ---------------------------------------------------------------------------

def test_stone_field_blocks_sow():
    state = setup(0)
    state = _with_resources(state, 0, Resources(grain=2))
    # The player's only field holds stone: nothing is sowable.
    state = _set_cell(state, 0, 0, 4, Cell(cell_type=CellType.FIELD, stone=1))
    assert not _can_sow(state.players[0])
    # An additional genuinely-empty field restores sowability.
    state = _set_cell(state, 0, 1, 4, Cell(cell_type=CellType.FIELD))
    assert _can_sow(state.players[0])


# ---------------------------------------------------------------------------
# The field-phase take — stone harvests normally, with a manifest entry
# ---------------------------------------------------------------------------

def test_field_take_harvests_stone():
    state = setup(0)
    state = _set_cell(state, 0, 0, 4, Cell(cell_type=CellType.FIELD, stone=1))
    state = _set_cell(state, 0, 1, 4, Cell(cell_type=CellType.FIELD, grain=3))
    before = state.players[0].resources
    state, occasion = field_take(state, 0)
    after = state.players[0].resources
    assert after.stone == before.stone + 1
    assert after.grain == before.grain + 1
    by_source = {e.source: e for e in occasion.entries}
    stone_entry = by_source["cell:0,4"]
    assert (stone_entry.crop, stone_entry.amount, stone_entry.emptied) == ("stone", 1, True)
    grain_entry = by_source["cell:1,4"]
    assert (grain_entry.crop, grain_entry.amount, grain_entry.emptied) == ("grain", 1, False)
    # The stone field is emptied by the take and becomes sowable again.
    cell = state.players[0].farmyard.grid[0][4]
    assert cell.stone == 0 and cell.field_empty


# ---------------------------------------------------------------------------
# Canonical — Family byte-identity and the qualified skip
# ---------------------------------------------------------------------------

def test_canonical_family_cells_omit_stone():
    # A Family state's cells never carry stone, so the qualified "Cell.stone"
    # skip keeps every cell dict free of the key (Resources.stone must and
    # does keep serializing — the reason the entry is qualified).
    node = canonical.to_canonical(setup(3))
    for player in node["players"]:
        for row in player["farmyard"]["grid"]:
            for cell in row:
                assert "stone" not in cell
    assert '"stone"' in canonical.dumps(setup(3))  # Resources.stone still emits


def test_canonical_stone_cell_round_trips():
    state = setup(0)
    state = _set_cell(state, 0, 0, 4, Cell(cell_type=CellType.FIELD, stone=1))
    text = canonical.dumps(state)
    back = canonical.loads(text)
    assert back.players[0].farmyard.grid[0][4].stone == 1
    assert back == state
    # And a default cell in the same state still omits the key.
    node = json.loads(text)
    assert "stone" not in node["players"][0]["farmyard"]["grid"][0][0]


# ---------------------------------------------------------------------------
# Swept reader helpers — planted, not empty, for prerequisites and effects
# ---------------------------------------------------------------------------

def test_unplanted_readers_exclude_stone_fields():
    from agricola.cards.greening_plan import count_unplanted_fields

    state = setup(0)
    state = _set_cell(state, 0, 0, 4, Cell(cell_type=CellType.FIELD, stone=1))
    state = _set_cell(state, 0, 1, 4, Cell(cell_type=CellType.FIELD))
    assert count_unplanted_fields(state.players[0].farmyard) == 1  # only the bare one


def test_web_cell_dict_carries_stone():
    # The web UI's cell serialization emits stone only when present, so
    # Family/no-stone payloads are unchanged and a stone field renders.
    from play_web import _cell_to_dict

    assert "stone" not in _cell_to_dict(Cell(cell_type=CellType.FIELD))
    d = _cell_to_dict(Cell(cell_type=CellType.FIELD, stone=1))
    assert d["stone"] == 1


def test_planted_readers_count_stone_fields():
    import agricola.cards.field_clay as field_clay

    state = setup(0)
    state = _set_cell(state, 0, 0, 4, Cell(cell_type=CellType.FIELD, stone=1))
    state = _set_cell(state, 0, 1, 4, Cell(cell_type=CellType.FIELD, grain=2))
    state = _set_cell(state, 0, 2, 4, Cell(cell_type=CellType.FIELD))
    assert field_clay._planted_field_count(state, 0) == 2  # stone + grain, not the bare one
