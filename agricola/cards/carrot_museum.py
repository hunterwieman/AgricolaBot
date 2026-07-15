"""Carrot Museum (minor improvement, D79; Consul Dirigens Expansion;
Building Resource Provider).

Card text (verbatim): "At the end of rounds 8, 10, and 12, you get 1 stone for
each vegetable field you have and a number of wood equal to the number of
vegetables in your supply."
Cost: 1 Wood, 2 Clay. Prerequisite: "Play in Round 8 or Before". Printed VPs: 2.

TIMING — "at the end of rounds 8, 10, and 12" is the round-end ladder's
``end_of_round`` rung (user ruling 49, 2026-07-12: "the end of the round" is
the ladder's last, distinct instant, after the return-home reset;
``agricola/cards/round_end.py`` — the same rung Credit / Lifting Machine use).
Latched to the three named rounds by the bearer's own eligibility
(``round_number in {8, 10, 12}``); rounds 8/10/12 are all NON-harvest rounds,
so no harvest condition is needed.

FIRING KIND — "you get ..." is a MANDATORY, choice-free pure-goods gain, so it
is an AUTOMATIC effect (``register_auto``), never a FireTrigger button (the
Credit idiom). The ladder walk fires it per owner mechanically.

THE GRANT:

- "1 stone for each vegetable field you have" — a vegetable field is a grid
  FIELD cell currently holding >= 1 vegetable (``cell.veg > 0``), the same
  "<crop> field" definition Bumper Crop uses for a "grain field". +1 stone per
  such cell.
- "a number of wood equal to the number of vegetables in your supply" —
  ``p.resources.veg`` wood. Both are ordinary resources (no accommodation
  concern), added straight to supply.

Prerequisite "Play in Round 8 or Before" is a play-TIME have-check, never spent
(``state.round_number <= 8`` — the Foreign Aid "Play in Round N or Before"
idiom). Printed VPs 2 → ``vps=2``.

Card-game only (ownership-gated registries; no CardStore): the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "carrot_museum"
_ROUNDS = frozenset({8, 10, 12})


def _prereq(state: GameState, idx: int) -> bool:
    """"Play in Round 8 or Before" — a play-time have-check, never spent."""
    return state.round_number <= 8


def _veg_field_count(state: GameState, idx: int) -> int:
    """Vegetable fields: grid FIELD cells currently holding >= 1 vegetable (the
    Bumper Crop "<crop> field" definition)."""
    grid = state.players[idx].farmyard.grid
    return sum(
        1
        for row in grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.veg > 0
    )


def _eligible(state: GameState, idx: int) -> bool:
    """"At the end of rounds 8, 10, and 12" — the bearer's own round latch."""
    return state.round_number in _ROUNDS


def _apply(state: GameState, idx: int) -> GameState:
    """+1 stone per vegetable field, +1 wood per vegetable in supply."""
    p = state.players[idx]
    stone = _veg_field_count(state, idx)
    wood = p.resources.veg
    p = fast_replace(p, resources=p.resources + Resources(stone=stone, wood=wood))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1, clay=2)),
    prereq=_prereq,
    vps=2,
)

# The mandatory round-8/10/12 resource grant on the round-end ladder's
# end_of_round rung (ruling 49).
register_auto("end_of_round", CARD_ID, _eligible, _apply)
