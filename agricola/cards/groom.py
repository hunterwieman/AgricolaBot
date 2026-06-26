"""Groom (occupation, B89; Base Revised; players 1+).

Card text: "When you play this card, you immediately get 1 wood. Once you live in a
stone house, at the start of each round, you can build exactly 1 stable for 1 wood."

Category 2 on-play (+1 wood) + Category 7 (start-of-round phase hook). The
round-start clause is an OPTIONAL trigger: once in a stone house the owner may build
exactly 1 stable for 1 wood — a fixed-price granted sub-action. Surfaced as a
FireTrigger on the `start_of_round` event; firing it pushes the reusable
PendingBuildStables primitive with cost `Resources(wood=1)` and cap 1 (the build's
own affordability/empty-cell gate is enforced by that primitive's enumerator).
Once-per-round via `used_this_round` (II.3); eligibility requires a buildable stable
so it never grants a dead-end. See CARD_IMPLEMENTATION_PLAN.md Category 7.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_start_of_round_hook
from agricola.constants import HouseMaterial
from agricola.legality import _can_build_stable
from agricola.pending import PendingBuildStables, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "groom"
_STABLE_COST = Resources(wood=1)


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and p.house_material is HouseMaterial.STONE
            and _can_build_stable(p, _STABLE_COST))


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, used_this_round=p.used_this_round | {CARD_ID})
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return push(state, PendingBuildStables(
        player_idx=idx, initiated_by_id="card:groom",
        cost=_STABLE_COST, max_builds=1))


register_occupation(CARD_ID, _on_play)
register("start_of_round", CARD_ID, _eligible, _apply)
register_start_of_round_hook(CARD_ID)
