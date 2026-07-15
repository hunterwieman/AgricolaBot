"""Animal Tamer's Apprentice (occupation, E168; Ephipparius Expansion; players 4+).

Card text (verbatim): "At the start of each round, you get 1 sheep/wild
boar/cattle for each unoccupied wood/clay/stone room in your house."
No cost / prerequisite / passing / printed VPs.

TIMING — "At the start of each round" → the preparation ladder's
``start_of_round`` window (preparation.py position 6; Scullery / Plow Driver are
the exemplars of this rung).

FIRING KIND — "you get ..." is mandatory and choice-free (the animal TYPE is
fixed by the house material and the COUNT by the rooms — no player decision) → an
automatic effect (``register_auto``).

THE MAPPING — all of a player's rooms share the house material (WOOD → CLAY →
STONE), so "wood/clay/stone room" selects the animal by the current house
material: wood house → sheep, clay house → wild boar, stone house → cattle. An
"unoccupied room" is a room with no family member living in it; every person
occupies exactly one room, so the count of unoccupied rooms is
``num_rooms - people_total`` (people_total counts placed AND home members — a
member away working still owns their room). The grant is therefore N animals of
one type, N = unoccupied rooms.

ACCOMMODATION — the animals are handed over through ``helpers.grant_animals``
(add + flag), so an over-capacity grant reconciles through the standard
accommodation barrier at the round's first worker placement (the same path
scheduled round-start animals take — engine._collect_future_rewards); the player
chooses which to keep, the rest cook to food. Never a raw ``p.animals + ...``.

Card-game only (ownership-gated registry; grant_animals' card-only flag is
default-skipped): the Family game is byte-identical and the C++ gates are
untouched. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import CellType, HouseMaterial
from agricola.helpers import grant_animals
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "animal_tamers_apprentice"

# House material → the animal type its rooms yield.
_ANIMAL_BY_MATERIAL = {
    HouseMaterial.WOOD: "sheep",
    HouseMaterial.CLAY: "boar",
    HouseMaterial.STONE: "cattle",
}


def _num_rooms(state: GameState, idx: int) -> int:
    grid = state.players[idx].farmyard.grid
    return sum(1 for row in grid for cell in row if cell.cell_type is CellType.ROOM)


def _unoccupied_rooms(state: GameState, idx: int) -> int:
    # Every family member (placed or home) occupies one room, so occupied rooms
    # == people_total and unoccupied == num_rooms - people_total.
    return _num_rooms(state, idx) - state.players[idx].people_total


def _eligible(state: GameState, idx: int) -> bool:
    return _unoccupied_rooms(state, idx) > 0


def _apply(state: GameState, idx: int) -> GameState:
    n = _unoccupied_rooms(state, idx)
    animal = _ANIMAL_BY_MATERIAL[state.players[idx].house_material]
    return grant_animals(state, idx, Animals(**{animal: n}))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("start_of_round", CARD_ID, _eligible, _apply)
