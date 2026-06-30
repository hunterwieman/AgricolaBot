"""Heresy Teacher (occupation, A113; Artifex Expansion; players 1+).

Card text: "Each time you use a 'Lessons' action space, you get 1 vegetable in
each of your fields with at least 3 grain and no vegetable. Place the vegetable
below the grain."
Clarification: "Fields with both crops can count as a grain field or a vegetable
field, but not both simultaneously."

Category 3 (action-space hook, automatic field income) on the Lessons space.
Played via Lessons; its whole effect is the hook, so on-play is a no-op (the
default).

TIMING: the text says "each time you use" with no "immediately after" qualifier,
so by the Trigger-Timing ruling the hook fires in the BEFORE-phase
(`before_action_space`), not after. Behaviorally the before/after distinction is
near-invisible here (Lessons' own effect is just playing an occupation, which
never touches a field), but `before_action_space` honors the ruling and matches
the Corn Scoop precedent.

HOSTING: Lessons self-hosts as a `PendingSubActionSpace` (its single mandatory
sub-action is "play one occupation"), so NO `register_action_space_hook` is
needed — hooking it would be redundant (the hook index governs ATOMIC spaces
only). The before_action_space auto fires at the Lessons host's push.

EFFECT: a "field with at least 3 grain and no vegetable" is a FIELD cell with
`grain >= 3 and veg == 0`. Such a field gets `veg` set to 1 ("place the vegetable
below the grain" — the grain count is untouched). The literal `veg == 0` test
already excludes any field carrying vegetables, so the clarification (a mixed
grain+veg field is never counted here) is automatic — no behavior change. Only
the crop counts on the cell change; the grid's geometry (and so the cached
pasture decomposition) is unaffected.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.state import GameState

CARD_ID = "heresy_teacher"
SPACES = frozenset({"lessons"})


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at the Lessons host frame's before-phase; read the space via the
    # host frame's `space_id` ("space:lessons" -> "lessons").
    return state.pending_stack[-1].space_id in SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    grid = p.farmyard.grid
    new_grid_rows = []
    for r in range(3):
        new_row = []
        for c in range(5):
            cell = grid[r][c]
            if (cell.cell_type == CellType.FIELD
                    and cell.grain >= 3 and cell.veg == 0):
                new_row.append(fast_replace(cell, veg=1))
            else:
                new_row.append(cell)
        new_grid_rows.append(tuple(new_row))
    new_farmyard = fast_replace(p.farmyard, grid=tuple(new_grid_rows))
    p = fast_replace(p, farmyard=new_farmyard)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no-op on play
register_auto("before_action_space", CARD_ID, _eligible, _apply)
