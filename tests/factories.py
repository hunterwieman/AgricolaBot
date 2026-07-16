"""Test state factories.

Construct prefabricated GameState objects for testing, bypassing gameplay
constraints (round limits, unimplemented action spaces, etc.). Each helper
returns a NEW state — none mutate their input.

See TASK_5.md "Testing principle: prefabricated states" for rationale.
"""
from __future__ import annotations

import dataclasses
from typing import Optional

from agricola.constants import CellType, HouseMaterial, Phase
from agricola.pending import PendingDecision
from agricola.resources import Animals, Resources
from agricola.state import (
    ActionSpaceState,
    BoardState,
    Cell,
    Farmyard,
    GameState,
    PlayerState,
    get_space as _get_space,
    with_space as _board_with_space,
)


def with_resources(state, player_idx, **resource_kwargs):
    """Replace player_idx's resources with the given amounts (others zero).

    Example: with_resources(s, 0, grain=1, clay=2) sets player 0 to have
    exactly 1 grain and 2 clay, nothing else.
    """
    p = state.players[player_idx]
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, resources=Resources(**resource_kwargs)))


def add_resources(state, player_idx, **resource_kwargs):
    """Add to player_idx's existing resources (does not replace)."""
    p = state.players[player_idx]
    new_res = p.resources + Resources(**resource_kwargs)
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, resources=new_res))


def with_animals(state, player_idx, **animal_kwargs):
    """Replace player_idx's animals with the given amounts."""
    p = state.players[player_idx]
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, animals=Animals(**animal_kwargs)))


def with_house(state, player_idx, material: HouseMaterial):
    """Set player_idx's house material (does not change which cells are ROOMs)."""
    p = state.players[player_idx]
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, house_material=material))


def with_majors(state, *, owner_by_idx: dict):
    """Set major-improvement ownership.

    Keys are major-improvement indices (0..9); values are owning player_idx.
    Indices not in the dict keep their current value.

    Example: with_majors(s, owner_by_idx={0: 0}) gives player 0 a Fireplace.
    """
    owners = list(state.board.major_improvement_owners)
    for idx, player_idx in owner_by_idx.items():
        owners[idx] = player_idx
    new_board = dataclasses.replace(state.board, major_improvement_owners=tuple(owners))
    return dataclasses.replace(state, board=new_board)


def with_minors(state, player_idx, card_ids: frozenset):
    """Set player_idx's played minor improvements."""
    p = state.players[player_idx]
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, minor_improvements=card_ids))


def with_grid(state, player_idx, cell_overrides: dict):
    """Replace specific cells in player_idx's farmyard grid.

    Example: with_grid(s, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})
    plows a field at row 0, column 2 for player 0.

    Note: this helper does not change fences, so the pasture cache on
    Farmyard is unaffected.
    """
    p = state.players[player_idx]
    grid = p.farmyard.grid
    new_grid = tuple(
        tuple(cell_overrides.get((r, c), grid[r][c]) for c in range(5))
        for r in range(3)
    )
    new_farmyard = dataclasses.replace(p.farmyard, grid=new_grid)
    return _replace_player(state, player_idx,
                            dataclasses.replace(p, farmyard=new_farmyard))


def with_fields(state, player_idx, field_cells):
    """Plow the given cells (all become empty FIELDs)."""
    overrides = {(r, c): Cell(cell_type=CellType.FIELD) for (r, c) in field_cells}
    return with_grid(state, player_idx, overrides)


def with_sown_fields(state, player_idx, *,
                     grain_fields=(),
                     veg_fields=()):
    """Plow the given cells AND fill them with 3 grain or 2 veg respectively."""
    overrides = {}
    for (r, c) in grain_fields:
        overrides[(r, c)] = Cell(cell_type=CellType.FIELD, grain=3)
    for (r, c) in veg_fields:
        overrides[(r, c)] = Cell(cell_type=CellType.FIELD, veg=2)
    return with_grid(state, player_idx, overrides)


def with_space(state, space_id: str, **kwargs):
    """Replace fields on a specific action space.

    Example: with_space(s, "fishing", revealed=True, accumulated_amount=3)
    """
    new_action_space = dataclasses.replace(_get_space(state.board, space_id), **kwargs)
    new_board = _board_with_space(state.board, space_id, new_action_space)
    return dataclasses.replace(state, board=new_board)


def with_pending_stack(state, frames):
    """Replace the pending stack entirely.

    frames is a sequence of PendingDecision instances, bottom-to-top.
    """
    return dataclasses.replace(state, pending_stack=tuple(frames))


def with_phase(state, phase: Phase):
    return dataclasses.replace(state, phase=phase)


def with_round(state, round_number: int):
    return dataclasses.replace(state, round_number=round_number)


def with_current_player(state, player_idx: int):
    return dataclasses.replace(state, current_player=player_idx)


def with_people(state, player_idx, *, total=None, home=None, newborns=None, supply=None):
    """Set people counts for a player. Omitted args keep current value.

    When `total` is given (and `supply` is not), `workers_in_supply` is kept
    consistent with the 5-meeple, no-eviction invariant (`5 - total`) — so a test
    that sets `total=5` reaches the growth cap (`workers_in_supply == 0`), matching
    the pre-`workers_in_supply` behaviour where the cap read `people_total < 5`. Pass
    `supply` explicitly to model a Lodger-style eviction (meeples removed from play)."""
    p = state.players[player_idx]
    new_total = total if total is not None else p.people_total
    if supply is not None:
        new_supply = supply
    elif total is not None:
        new_supply = 5 - new_total
    else:
        new_supply = p.workers_in_supply
    return _replace_player(state, player_idx, dataclasses.replace(
        p,
        people_total=new_total,
        people_home=home if home is not None else p.people_home,
        newborns=newborns if newborns is not None else p.newborns,
        workers_in_supply=new_supply,
    ))


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _replace_player(state, player_idx, new_player):
    new_players = tuple(
        new_player if i == player_idx else state.players[i] for i in range(2)
    )
    return dataclasses.replace(state, players=new_players)
