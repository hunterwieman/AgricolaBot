"""Cob (minor improvement, A76; Artifex Expansion; cost 1 food).

Card text: "At the start of each work phase, if you have at least 1 clay in your
supply, you can exchange exactly 1 grain for 2 clay and 1 food."
Printed VPs: none. Prerequisite: none. Not a passing minor.

Category 7 (start-of-round phase hook). The "start of each work phase" clause maps
to the engine's `start_of_round` event, which fires when a player enters the WORK
phase of a new round (the PendingPreparation host). The exchange is OPTIONAL
("you can"), so it is surfaced as a FireTrigger the owner may take or decline — the
host's Proceed is the decline path — NOT a choice-free automatic effect.

Firing applies the swap directly (no pending push): −1 grain, +2 clay, +1 food.
Eligibility requires BOTH the verbatim "at least 1 clay" gate (a real have-check,
even though the swap also *gives* clay) AND at least 1 grain to spend, and latches
`used_this_round` so the exchange fires at most once per round (II.3). The per-round
used-set is cleared at the start of each round, so the option re-arms every round.
See CARD_IMPLEMENTATION_PLAN.md Category 7.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_start_of_round_hook
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "cob"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and p.resources.clay >= 1
            and p.resources.grain >= 1)


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources + Resources(grain=-1, clay=2, food=1),
        used_this_round=p.used_this_round | {CARD_ID},
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(food=1)))
register("start_of_round", CARD_ID, _eligible, _apply)
register_start_of_round_hook(CARD_ID)
