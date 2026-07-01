"""Roof Ladder (minor improvement, D81; Dulcinaria Expansion; Building Resource Provider).

Card text: "Each time you renovate, you pay 1 fewer reed and, at the end of the action,
you get 1 stone."
Cost: 1 Wood. No prerequisite. 0 VPs. Kept (not traveling).

Two mandatory, choice-free clauses, both keyed on renovation:

- **pay 1 fewer reed** → a `renovate` cost REDUCTION (COST_MODIFIER_DESIGN.md §1.1). A
  reduction is a signed delta the fold (`apply_reductions`) floors at 0 after each card,
  so subtracting `Resources(reed=1)` removes one reed from the renovate cost wherever the
  cost prints reed, and is a harmless no-op where it does not. (A clay-house → clay-house
  renovate prints reed, so the discount bites; a clay → stone renovate prints no reed, so
  the −1 floors to 0 — a safe no-op.) The reduction is inert until a build routes its cost
  through the `effective_payments` chokepoint, which renovate does.

- **at the end of the action, you get 1 stone** → an `after_renovate` automatic effect
  (`register_auto`). This is a deferred, choiceless, pure-goods grant with no downside, so
  it is a MANDATORY auto (no FireTrigger / no declinable `register`); it fires once per
  renovate at the after-phase flip of the House-Redevelopment / Farm-Redevelopment host,
  AFTER the renovate has applied. Eligibility is unconditional — "each time you renovate"
  grants the stone for EVERY renovate (clay→clay, clay→stone, …), unlike Roughcaster's
  food which gates on the resulting house material. The grant adds stone directly (it is a
  raw resource gain, not an animal that needs accommodation).

A passive card otherwise — no on-play effect, no prerequisite, 0 VPs, dealt and played
via the minor-improvement entry points. Card-only registries are empty in the Family game
(no cards owned), so the Family game is byte-identical and the C++ differential gates are
untouched. See CARD_AUTHORING_GUIDE.md, COST_MODIFIER_DESIGN.md (the reduction), and
roughcaster.py / skillful_renovator.py (the `after_renovate` auto). Mirrors
straw_thatched_roof.py (the minor cost-reduction shape) + roughcaster.py (the
`after_renovate` grant).
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import _noop_on_play, register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "roof_ladder"


def _less_1_reed(state: GameState, idx: int, ctx, cost: Resources) -> Resources:
    """Pay 1 fewer reed — a signed −1 reed delta. The fold floors each component at 0,
    so a renovate that prints no reed (clay→stone) is left unchanged (a no-op)."""
    return cost - Resources(reed=1)


def _grant_stone(state: GameState, idx: int) -> GameState:
    """At the end of a renovate, the owner gets 1 stone (a raw resource gain)."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(stone=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),   # printed cost: 1 wood
    on_play=_noop_on_play,                     # no on-play effect
)
register_reduction("renovate", CARD_ID, _less_1_reed)
# Unconditional: the +1 stone applies to EVERY renovate (no house-material gate).
register_auto("after_renovate", CARD_ID, lambda state, idx: True, _grant_stone)
