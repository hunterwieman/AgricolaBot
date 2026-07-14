"""Recluse (occupation, E111; Ephipparius Expansion; players 1+).

Card text: "As long as you have no minor improvements in front of you, you get 1
food at the start of each round and 1 wood at the start of each harvest."

No structured cost / prerequisite (occupations carry none in the data). Category:
Food Provider. No on-play effect.

TWO independent income effects, both governed by the same standing condition
"as long as you have no minor improvements in front of you", each MANDATORY and
choice-free ("you get", not "you can") -> two automatic effects:

  1. `start_of_round` — +1 food at the start of each round (the preparation ladder's
     start_of_round window: `register_auto("start_of_round", …)`, fired mechanically
     by the walk for the owner, exactly as Scullery / Civic Facade). By the time it
     fires the walk has already incremented `round_number` to the round being
     entered; the food grant is round-independent, so that is fine.
  2. `start_of_harvest` — +1 wood at the start of each harvest (harvest window #2,
     the window opening the whole harvest before the field phase:
     `register_auto("start_of_harvest", …)` + `register_harvest_window_hook`,
     fired by the harvest walk per owner). It credits wood only and never touches
     the grid, so the mechanical field-phase take is unaffected.

On a harvest round BOTH fire: the start-of-round food during preparation, then the
start-of-harvest wood when the harvest opens — matching the two independent printed
clauses.

Eligibility — "as long as you have no minor improvements in front of you" (quoted
verbatim): "in front of you" is the played tableau, so this gates on the player's
PLAYED minor-improvement set being EMPTY (`len(minor_improvements) == 0`). The
condition names ONLY minor improvements — majors and occupations "in front of you"
do NOT disqualify. Re-evaluated at every firing, so playing any minor improvement
immediately turns both incomes off; a played major or another occupation leaves
them on. The same `_eligible` predicate gates both events.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "recluse"


def _eligible(state: GameState, idx: int) -> bool:
    """True iff the player has NO minor improvements in their played tableau
    ("no minor improvements in front of you"). Majors / occupations do not
    count — the text names only minor improvements."""
    return len(state.players[idx].minor_improvements) == 0


def _apply_food(state: GameState, idx: int) -> GameState:
    """+1 food at the start of each round (while no minor improvements are played)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _apply_wood(state: GameState, idx: int) -> GameState:
    """+1 wood at the start of each harvest (while no minor improvements are
    played). Credits wood only; never touches the grid, so the mechanical
    field-phase take is unaffected."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
# Clause 1: +1 food at the start of each round.
register_auto("start_of_round", CARD_ID, _eligible, _apply_food)
# Clause 2: +1 wood at the start of each harvest.
register_auto("start_of_harvest", CARD_ID, _eligible, _apply_wood)
register_harvest_window_hook(CARD_ID, "start_of_harvest")
