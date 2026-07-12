"""Pipe Smoker (occupation, E117; Ephipparius Expansion; players 1+).

Card text: "At the start of each harvest, if you have at least 1 grain field, you
get 2 wood."

No structured cost / prerequisite (occupations carry none in the data). Category:
Building Resource Provider. No on-play effect.

Harvest-window auto. The printed timing "At the start of each harvest" maps to
harvest window #2, `start_of_harvest` (the window that opens the whole harvest,
before the field phase). The income is MANDATORY and choice-free ("you get", not
"you can") -> an automatic effect (`register_auto` on the `start_of_harvest`
window event), fired by the harvest walk (`_process_simple_window`) per owner,
window-major, starting player first, GATED by the printed condition.

Eligibility — "if you have at least 1 grain field": at least one of the player's
own FIELD cells currently holds grain (`cell.grain > 0`, `>= 1`) OR at least one
of their card-fields holds grain (`crop_card_field_count(p, "grain")`) — the same
"grain field" definition Sleeping Corner / Bale of Straw / Gardener's Knife use.
Ruling 45 (2026-07-12), verbatim: '"field TILES" means the plowed fields on the
farmyard grid; "field" is the BROADER category and includes card-fields. So a
card-field counts for field-count readers — the Fields scoring category and any
"you need N fields" requirement — while per-TILE readers still exclude it (ruling
32 unchanged).' Per ruling 47 a multi-stack card-field counts exactly once.
This window is BEFORE the field-phase crop take (window #5), so `_eligible` reads
the still-sown grid — exactly when "you have at least 1 grain field" should be
evaluated, since no grain has been removed yet. The reward is a flat 2 wood (not
per-field). The auto credits wood only and never touches the grid, so the
mechanical take is unaffected.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "pipe_smoker"

_THRESHOLD = 1
_WOOD = 2


def _grain_fields(state: GameState, idx: int) -> int:
    """Count the player's grain fields: grid FIELD cells with grain planted,
    plus grain-holding card-fields (ruling 45, 2026-07-12: "field" includes
    card-fields; ruling 47: each card counts exactly once)."""
    from agricola.cards.card_fields import crop_card_field_count  # local: load-order safe
    p = state.players[idx]
    return sum(
        1
        for row in p.farmyard.grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain > 0
    ) + crop_card_field_count(p, "grain")


def _eligible(state: GameState, idx: int) -> bool:
    return _grain_fields(state, idx) >= _THRESHOLD


def _apply(state: GameState, idx: int) -> GameState:
    """+2 wood at the start of the harvest when at least one grain field is
    present. Credits wood only; never touches the grid, so the mechanical
    field-phase take is unaffected."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=_WOOD))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("start_of_harvest", CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "start_of_harvest")
