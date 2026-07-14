"""Freemason (occupation, C123; Consul Dirigens Expansion; players 1+).

Card text: "As long as you live in a clay/stone house with exactly 2 rooms, at
the start of each work phase, you get 2 clay/stone."

Clarification: "Cards that provide room for a person do not count for this effect
unless they self-identify as a room." — so only true `CellType.ROOM` cells count
(no implemented card grants a non-room living space, so this needs no special
handling — exactly as Priest / Small-scale Farmer / Childless already count).

"At the start of each work phase" → the preparation ladder's `start_of_work`
window (ruling 54, 2026-07-14) — the ladder's last rung, post-replenishment,
distinct from and later than `start_of_round`. The income is a MANDATORY,
choice-free grant ("you get", not "you can") → an automatic effect
(`register_auto`), fired mechanically by the walk for each owner.

The grant is material-conditioned: a CLAY house yields +2 clay, a STONE house
yields +2 stone, and a WOOD house yields nothing. The "clay/stone" + "2 clay/stone"
notation is split by `house_material` inside `_apply`, with the wood case excluded
by `_eligible`. The condition (clay-or-stone house AND exactly 2 rooms) is
re-checked each round in `_eligible`, so the income auto-stops on a renovate to
wood or a room-count change. No once-per-round latch is needed: the engine fires
`start_of_work` exactly once per owner per round.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.constants import CellType, HouseMaterial
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, PlayerState

CARD_ID = "freemason"


def _num_rooms(p: PlayerState) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _eligible(state: GameState, idx: int) -> bool:
    p = state.players[idx]
    return _num_rooms(p) == 2 and p.house_material in (
        HouseMaterial.CLAY,
        HouseMaterial.STONE,
    )


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    gain = (
        Resources(clay=2)
        if p.house_material is HouseMaterial.CLAY
        else Resources(stone=2)
    )
    p = fast_replace(p, resources=p.resources + gain)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("start_of_work", CARD_ID, _eligible, _apply)
