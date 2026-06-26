"""Childless (occupation, B114; Base Revised; players 1+).

Card text: "At the start of each round, if you have at least 3 rooms but only 2
people, you get 1 food and 1 crop of your choice (grain or vegetable)"

Category 7 (start-of-round phase hook), the MANDATORY-WITH-CHOICE firing kind
(II.1): the income is not optional (you cannot decline it), but it carries a choice
(grain or vegetable), so it is a `mandatory`-tagged trigger rather than a plain
automatic effect. While eligible and unfired it gates the PendingPreparation host's
Proceed; firing it applies the +1 food immediately and pushes a PendingCardChoice for
the crop (a forced pick, no decline). The crop resolver applies the chosen crop and
pops the choice frame; the gate then reopens. Once-per-round via `used_this_round`
(II.3). See CARD_IMPLEMENTATION_PLAN.md Category 7 / II.1.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import (
    register,
    register_card_choice_resolver,
    register_start_of_round_hook,
)
from agricola.constants import CellType
from agricola.pending import PendingCardChoice, pop, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, PlayerState

CARD_ID = "childless"


def _num_rooms(p: PlayerState) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and _num_rooms(p) >= 3
            and p.people_total == 2)


def _apply(state: GameState, idx: int) -> GameState:
    # Apply the +1 food immediately, latch once-per-round, then push the crop choice.
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1),
                     used_this_round=p.used_this_round | {CARD_ID})
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return push(state, PendingCardChoice(
        player_idx=idx, initiated_by_id="card:childless",
        options=("grain", "veg")))


def _resolve(state: GameState, idx: int, chosen: str) -> GameState:
    p = state.players[idx]
    gain = Resources(grain=1) if chosen == "grain" else Resources(veg=1)
    p = fast_replace(p, resources=p.resources + gain)
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return pop(state)   # resolver owns the PendingCardChoice frame


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("start_of_round", CARD_ID, _eligible, _apply, mandatory=True)
register_start_of_round_hook(CARD_ID)
register_card_choice_resolver(CARD_ID, _resolve)
