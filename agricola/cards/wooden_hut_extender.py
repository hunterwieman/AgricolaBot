"""Wooden Hut Extender (occupation, C #128; Corbarius Expansion; players 3+).

Card text: "Wood rooms now cost you 1 reed, and additionally 5 wood through round 5,
4 wood in rounds 6 and 7, and 3 wood in round 8 and later."

A passive cost-FORMULA card (COST_MODIFIER_DESIGN.md §1.1 / §4.2). It replaces the whole
printed cost of building a WOOD room (5 wood + 2 reed) with a cheaper, round-dependent
alternative:

  - reed always drops to 1, and
  - the wood amount is round-banded: 5 wood through round 5, 4 wood in rounds 6-7, and
    3 wood from round 8 on.

"Wood rooms" — the clause only applies when the player lives in a WOOD house, so the
`applies` predicate gates on `house_material == WOOD` (mirroring Carpenter's Parlor /
Clay Plasterer's per-material formulas). Formulas are mutually exclusive (the player uses
at most one); the chokepoint `effective_payments` surfaces this alternative beside the
printed base, lets reductions (e.g. Bricklayer) stack on each, and Pareto-min keeps the
cheaper. Since reed (1) is below the printed reed (2) and wood never exceeds the printed
5, the formula strictly dominates the printed base in every round, so it always survives
Pareto-min when applicable. In a clay/stone house the gate is False and only the printed
base survives — byte-identical to the Family game.

No on-play effect — the card's only effect is this passive room-cost formula.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_formula
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.constants import HouseMaterial
from agricola.resources import Resources

CARD_ID = "wooden_hut_extender"


def _in_wood_house(state, idx, ctx) -> bool:
    return state.players[idx].house_material == HouseMaterial.WOOD


def _wood_for_round(round_number: int) -> int:
    """5 wood through round 5, 4 wood in rounds 6-7, 3 wood from round 8 on."""
    if round_number <= 5:
        return 5
    if round_number <= 7:
        return 4
    return 3


def _wood_room_formula(state, idx, ctx) -> Resources:
    return Resources(wood=_wood_for_round(state.round_number), reed=1)


register_formula("build_room", CARD_ID, _in_wood_house, _wood_room_formula)
register_occupation(CARD_ID, _noop_on_play)   # passive cost card, no on-play
