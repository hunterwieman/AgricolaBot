"""Plow Driver (occupation, A90; Base Revised; players 1+).

Card text: "Once you live in a stone house, at the start of each round, you can pay
1 food to plow 1 field."

Category 7 (start-of-round phase hook). An OPTIONAL trigger (the "you can"): once in
a stone house, at round start the owner may pay 1 food to plow 1 field — a
fixed-price granted sub-action (not a cost-modifier). Surfaced as a FireTrigger on
the `start_of_round` event; firing it charges 1 food and pushes the reusable
PendingPlow primitive. Once-per-round via the `used_this_round` latch (II.3) so it
can't be fired twice in one preparation. Eligibility also requires a plowable cell
so it never grants a dead-end. See CARD_IMPLEMENTATION_PLAN.md Category 7 (canonical).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_start_of_round_hook
from agricola.constants import HouseMaterial
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "plow_driver"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and p.house_material is HouseMaterial.STONE
            and p.resources.food >= 1
            and _can_plow(p))


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=1),
                     used_this_round=p.used_this_round | {CARD_ID})
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:plow_driver"))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("start_of_round", CARD_ID, _eligible, _apply)
register_start_of_round_hook(CARD_ID)
