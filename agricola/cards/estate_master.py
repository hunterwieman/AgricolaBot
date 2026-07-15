"""Estate Master (occupation, B132; Bubulcus Expansion; players 3+).

Card text (verbatim): "Once you have no unused farmyard spaces left, you get 1 bonus
point for each vegetable that you harvest."
Clarification (verbatim): "If you have no unused spaces after playing this card and
then later change your farmyard arrangement (e.g. with Overhaul C001,) you still
receive bonus points for all future harvested vegetables."

Two seams plus a scoring readback:

- **The activation latch (a boundary one-shot).** "Once you have no unused farmyard
  spaces left" activates the card PERMANENTLY. The clarification is explicit: once
  the farm has been full, later un-filling it does NOT deactivate — so activation is
  a one-way `fired_once` latch. It registers on the decision-BOUNDARY sweep
  (`register_boundary_one_shot`, run at every agent-decision boundary after
  accommodation), whose condition is "every farmyard space is used". A space is used
  when it is a ROOM/FIELD/STABLE cell OR a fenced pasture cell — a fenced-but-empty
  pasture cell keeps `cell_type == EMPTY` yet IS used, so the check consults the
  fences too (the `big_country.py` `_all_farmyard_spaces_used` reference; checking
  `cell_type` alone would wrongly undercount empty pasture cells).

- **The banking (a harvest-occasion auto).** "1 bonus point for each vegetable that
  you harvest" — harvesting happens in the field phase; each vegetable UNIT taken
  from a field there earns 1 point. This mirrors Crack Weeder's veg-unit counting
  over the occasion manifest (`register_harvest_occasion_auto`, scoped to
  `Phase.HARVEST_FIELD`), but gated on the card being activated and accumulating VP
  instead of granting food. Points are BANKED (they cannot be derived at end-game —
  past harvests are not reconstructable) and read by the scoring term.

State: one CardStore entry per owner, a `(activated: bool, banked_points: int)`
tuple (default `(False, 0)`). Empty in the Family game -> byte-identical, C++ gates
untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_occasion_auto
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_boundary_one_shot
from agricola.constants import CellType, Phase
from agricola.helpers import enclosed_cells
from agricola.replace import fast_replace
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "estate_master"


def _entry(state: GameState, idx: int) -> tuple[bool, int]:
    """This owner's (activated, banked_points), defaulting to (False, 0)."""
    return state.players[idx].card_state.get(CARD_ID, (False, 0))


# --- 1. The activation latch (boundary one-shot) ---------------------------

def _all_farmyard_spaces_used(state: GameState, idx: int) -> bool:
    """Every farmyard space is used — a room/field/stable cell, or a fenced pasture
    cell (which keeps `cell_type == EMPTY` but IS used). Mirrors `big_country.py`."""
    fy = state.players[idx].farmyard
    grid = fy.grid
    enclosed = enclosed_cells(fy)
    return all(
        grid[r][c].cell_type is not CellType.EMPTY or (r, c) in enclosed
        for r in range(3)
        for c in range(5)
    )


def _activate(state: GameState, idx: int) -> GameState:
    """Latch the card ON, preserving any already-banked points."""
    _activated, banked = _entry(state, idx)
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, (True, banked)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# --- 2. The banking (harvest-occasion auto) --------------------------------

def _veg_taken(occasion) -> int:
    """Vegetable UNITS this occasion harvested (Crack Weeder's unit counting)."""
    return sum(e.amount for e in occasion.entries if e.crop == "veg")


def _bank_eligible(state: GameState, idx: int, occasion) -> bool:
    """Bank only once activated, in the FIELD PHASE, on an occasion that took veg."""
    activated, _banked = _entry(state, idx)
    return (
        activated
        and state.phase == Phase.HARVEST_FIELD
        and _veg_taken(occasion) > 0
    )


def _bank(state: GameState, idx: int, occasion) -> GameState:
    """+1 banked point per vegetable UNIT harvested this occasion."""
    activated, banked = _entry(state, idx)
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, (activated, banked + _veg_taken(occasion)))
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    return _entry(state, idx)[1]


# Pure recurring occupation: played via Lessons, on-play is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_boundary_one_shot(CARD_ID, _all_farmyard_spaces_used, _activate)
register_harvest_occasion_auto(CARD_ID, _bank_eligible, _bank)
register_scoring(CARD_ID, _score)
