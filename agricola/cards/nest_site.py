"""Nest Site (minor improvement, A49; Artifex Expansion; cost 1 food, prereq 1 occupation).

Card text: "Each time 1 reed is placed on a non-empty 'Reed Bank' accumulation
space during the preparation phase, you get 1 food."
Printed VPs: none. Prerequisite: 1 Occupation. Not a passing minor.

"… placed on [the Reed Bank] during the preparation phase" → the preparation
ladder's `replenishment` window (ruling 54, 2026-07-14), the reaction seam
immediately after the `__replenish__` sentinel runs the mechanical refill. The
Reed Bank accumulates +1 reed each preparation phase (its building-accumulation
rate); the card pays its owner 1 food only when that reed lands on a Reed Bank
that was ALREADY non-empty — i.e. when some reed was sitting on the space before
this round's refill.

The window fires right after the refill, so this auto sees the POST-refill
board. The Reed Bank's reed count after the refill is (pre-refill reed) + 1:
  - empty before refill  → post-refill reed == 1  → reed placed on an EMPTY bank → NO food.
  - non-empty before refill → post-refill reed >= 2 → reed placed on a NON-EMPTY bank → +1 food.
So `accumulated.reed >= 2` is exactly the "placed on a non-empty Reed Bank" condition.
It re-checks each round, so the income arms/disarms with the board automatically.

Round 1 is naturally excluded: setup returns the first WORK state without ever
running a preparation phase. A MANDATORY, choice-free income → `register_auto`.
See CARD_IMPLEMENTATION_PLAN.md Category 7; scullery.py is the template.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "nest_site"


def _eligible(state: GameState, idx: int) -> bool:
    # Post-refill: reed_bank.accumulated.reed >= 2 means the bank held >= 1 reed
    # BEFORE this round's +1 refill — i.e. the reed was placed on a non-empty bank.
    return get_space(state.board, "reed_bank").accumulated.reed >= 2


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(food=1)), min_occupations=1)
register_auto("replenishment", CARD_ID, _eligible, _apply)
