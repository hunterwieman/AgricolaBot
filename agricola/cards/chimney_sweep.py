"""Chimney Sweep (occupation, D154; Dulcinaria Expansion; players 4+).

Card text: "Renovating to stone costs you 2 stone less. During scoring, you get 1 bonus
point for each other player living in a stone house."

Two effects, both on existing seams:
- A passive COST-REDUCTION (COST_MODIFIER_DESIGN.md §1.1) on renovate, gated on the
  renovation TARGET being stone (`ctx.to_material` — the field carried for exactly this,
  named for Clay Plasterer and Chimney Sweep): −2 stone off the stone-tier renovate cost.
  The chokepoint floors at 0.
- A `register_scoring` term: +1 point per OTHER player living in a stone house — a public,
  derivable quantity (each player's `house_material`). In the 2-player game the sum ranges
  over the single opponent.

This is a [4] occupation — not dealt in the 2-player game, but valid to implement and
unit-test now. No on-play effect.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.constants import HouseMaterial
from agricola.resources import Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "chimney_sweep"


def _less_2_stone_to_stone(state, idx, ctx, cost: Resources) -> Resources:
    # "Renovating to stone" — only when the renovation target material is STONE.
    if ctx.to_material is HouseMaterial.STONE:
        return cost - Resources(stone=2)
    return cost


def _score(state: GameState, idx: int) -> int:
    # +1 per OTHER player living in a stone house.
    return sum(
        1 for j in range(len(state.players))
        if j != idx and state.players[j].house_material is HouseMaterial.STONE
    )


register_reduction("renovate", CARD_ID, _less_2_stone_to_stone)
register_scoring(CARD_ID, _score)

register_occupation(CARD_ID, _noop_on_play)   # no on-play effect
