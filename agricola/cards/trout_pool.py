"""Trout Pool (minor improvement, D54; Dulcinaria Expansion; cost 2 clay, 1 VP).

Card text: "At the start of each work phase, if there are at least 3 food on the
'Fishing' accumulation space, you get 1 food from the general supply."
Printed VPs: 1. No prerequisite. Not a passing minor.

"At the start of each work phase" → the preparation ladder's `start_of_work`
window (ruling 54, 2026-07-14) — the ladder's last rung, after the
`__replenish__` sentinel has run this round's accumulation-space refill (Fishing
gains its +1 food). A MANDATORY, choice-free income gated on the public Fishing
accumulation bank → an automatic effect (`register_auto`), fired mechanically by
the walk for each owner. The threshold reads the POST-refill board, which is
precisely the board the player sees at the start of the work phase — so the
literal `fishing.accumulated_amount >= 3` is correct as-written with no
off-by-one adjustment (unlike Nest Site, whose condition is about the PRE-refill
bank and so uses `>= 2` to back out the +1). Fishing is a food/animal
accumulation space, so its food count is the scalar `accumulated_amount` (not
the `accumulated` Resources that only the building spaces use).

The condition is re-checked each round, so the income arms/disarms automatically as
the Fishing bank grows (when unharvested) or is emptied (when a worker fishes).
Round 1 is naturally excluded: setup returns the first WORK state without ever
running a preparation phase. See CARD_IMPLEMENTATION_PLAN.md Category 7; nest_site.py
and pavior.py are the templates.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "trout_pool"


def _eligible(state: GameState, idx: int) -> bool:
    # Post-refill Fishing bank: the board the player sees at the start of the work
    # phase. >= 3 food triggers the 1-food income from the general supply. Fishing is
    # a food/animal accumulation space, so its food count lives in the scalar
    # `accumulated_amount` (NOT `accumulated`, which only the building spaces use).
    return get_space(state.board, "fishing").accumulated_amount >= 3


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=2)), vps=1)
register_auto("start_of_work", CARD_ID, _eligible, _apply)
