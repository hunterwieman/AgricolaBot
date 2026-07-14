"""Pavior (occupation, B110; Bubulcus Expansion; players 1+).

Card text: "At the end of each preparation phase, if you have at least 1 stone in
your supply, you get 1 food. In round 14, you get 1 vegetable instead."

"At the end of each preparation phase" → the preparation ladder's `before_work`
window (user ruling 2026-07-14): post-replenishment, immediately before the work
phase — the preparation phase's last instant. A MANDATORY, choice-free income
gated on holding at least 1 stone → an automatic effect (`register_auto`), fired
mechanically by the walk for the owner. By this window `round_number` already
names the round being entered, so `state.round_number` is the current round. The
stone-supply condition (>= 1 stone) is re-checked each round in the eligibility,
so the income stops in any round the player holds no stone. In the final round
(round 14, NUM_ROUNDS) the grant is 1 vegetable instead of 1 food.
See CARD_IMPLEMENTATION_PLAN.md Category 7.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import NUM_ROUNDS
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "pavior"


def _eligible(state: GameState, idx: int) -> bool:
    return state.players[idx].resources.stone >= 1   # at least 1 stone in supply


def _apply(state: GameState, idx: int) -> GameState:
    # Round 14 (the final round) grants a vegetable instead of food.
    gain = Resources(veg=1) if state.round_number == NUM_ROUNDS else Resources(food=1)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + gain)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
# "at the end of each preparation phase" — the before_work window (user ruling
# 2026-07-14), the prep phase's last instant, distinct from start_of_round.
register_auto("before_work", CARD_ID, _eligible, _apply)
