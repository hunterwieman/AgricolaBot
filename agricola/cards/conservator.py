"""Conservator (occupation, A87; Base Revised; players 1+).

Card text: "You can renovate your wooden house directly to stone without renovating it to
clay first."

A renovate-TARGET extension (COST_MODIFIER_DESIGN.md — the renovate-target model). It
makes WOOD→STONE a legal renovation target, skipping the clay tier. There is no special
cost on the card, so the cost *follows from the target* through the existing cost-modifier
chokepoint: a wood→stone renovation costs the stone tier (1 stone per room + 1 reed), and
`CommitRenovate.to_material` carries STONE so `_execute_renovate` upgrades straight to
stone. Modeling it as a target extension (rather than a cost formula + a flag) keeps the
target explicit on each commit and lets reductions/conversions compose per target without
any payment-provenance guessing. No on-play effect (the only effect is the extra target).
"""
from __future__ import annotations

from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.constants import HouseMaterial
from agricola.legality import register_renovate_target_extension

CARD_ID = "conservator"


def _wood_to_stone(state, idx: int, current_material) -> list:
    """Add STONE as a legal renovate target for a wood house when Conservator is owned."""
    if current_material is HouseMaterial.WOOD and CARD_ID in state.players[idx].occupations:
        return [HouseMaterial.STONE]
    return []


register_renovate_target_extension(_wood_to_stone)
register_occupation(CARD_ID, _noop_on_play)   # no on-play effect
