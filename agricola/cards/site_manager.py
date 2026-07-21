"""Site Manager (occupation, deck D #95; Dulcinaria Expansion; players 1+).

Card text (verbatim): "When you play this card, immediately build a major improvement.
When paying its cost, you can replace up to 1 building resource of each type with
1 food each."

Governing user rulings (2026-07-21, CARD_DEFERRED_PLANS.md):

- Ruling 74: the on-play major build is OPTIONAL ("let's not make it mandatory") —
  despite the imperative wording. The shape is the `PendingGrantedSubAction` wrapper
  (subactions=("build_major",)) pushed by `on_play`, with the wrapper's Stop as the
  decline — NOT a wide play-variant (the substitution is economics the card itself
  creates, so a pre-play variants_fn would read the wrong world).
- The build is a bare `PendingBuildMajor` — never the composite
  `PendingMajorMinorImprovement` (a card's own "build a major improvement" effect is
  not the named "Major or Minor Improvement" action; pushing the composite would
  wrongly fire Merchant / Small Trader). No menu restriction: all available majors
  (`major_allowed=None`, the full board).
- The cost substitution is a `register_conversion("build_major", ...)` in the
  cost-modifier registry, applying ONLY when the CostCtx's
  `granted_by == "card:site_manager"` (the grant-scoped pricing pattern — the
  `oven_site` shape: the wrapper threads its provenance into the build-major ctx via
  `_build_major_ctx(granted_by=...)`, so the substitution prices exactly this grant's
  build and a later normal Major Improvement action — `granted_by is None` — pays the
  printed cost with no substitution).

Two mechanisms:

- ON PLAY (`on_play`): push the generic `PendingGrantedSubAction` choose-or-decline
  wrapper for a single `build_major` granted category, full menu. Choosing pushes a
  bare `PendingBuildMajor` (provenance `"card:site_manager"`). The wrapper is pushed
  unconditionally (the oven_site pattern); its eligibility dispatch anticipates the
  grant-scoped, conversion-priced affordability through
  `can_pay(_build_major_ctx(i, granted_by="card:site_manager"))`, so when no major is
  unbuilt-and-payable under the substituted pricing only Stop is offered — never a
  dead-end.

- THE SUBSTITUTION ("replace up to 1 building resource of each type with 1 food
  each"): an internally-budgeted conversion generator `_expand` on `build_major`.
  For each building-resource type (wood/clay/reed/stone) with >=1 unit in the cost
  vector, up to 1 unit may be replaced by 1 food; `_expand` returns the unchanged
  cost plus every subset combination (<= 2^4 variants). The downstream Pareto
  frontier prunes dominated results; no pre-pruning beyond the generator contract.
  Gated inside the generator on `ctx.granted_by == "card:site_manager"` (the
  registry's `register_conversion` has no applies-fn parameter), so any other
  build-major — the space action, another card's grant — sees the unchanged cost
  only.
"""
from __future__ import annotations

from itertools import combinations

from agricola.cards.cost_mods import register_conversion
from agricola.cards.specs import register_occupation
from agricola.pending import PendingGrantedSubAction, push
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "site_manager"
FRAME_ID = "card:site_manager"      # the granted build-major frame's initiated_by_id

_BUILDING_RESOURCES = ("wood", "clay", "reed", "stone")


def _on_play(state: GameState, idx: int) -> GameState:
    # Push the optional build-major grant (ruling 74: optional despite "immediately
    # build"). Full menu (major_allowed=None). Unconditional push, mirroring oven_site:
    # the wrapper's eligibility gate anticipates the grant-scoped substitution pricing,
    # so an unaffordable/all-built board yields only Stop (never a dead-end).
    return push(state, PendingGrantedSubAction(
        player_idx=idx, initiated_by_id=FRAME_ID, subactions=("build_major",)))


def _expand(state, idx, ctx, cost: Resources) -> list[Resources]:
    """"When paying its cost, you can replace up to 1 building resource of each type
    with 1 food each." — the unchanged cost plus every replace-a-subset variant.

    Scoped to THIS card's own granted build (ctx.granted_by, the pushed frame's
    provenance): a normal Major Improvement action build (granted_by is None) or
    another card's granted build gets no substitution."""
    if ctx.granted_by != FRAME_ID:
        return [cost]
    present = [f for f in _BUILDING_RESOURCES if getattr(cost, f) >= 1]
    out = [cost]
    for r in range(1, len(present) + 1):
        for combo in combinations(present, r):
            out.append(cost
                       - Resources(**{f: 1 for f in combo})
                       + Resources(food=len(combo)))
    return out


register_occupation(CARD_ID, _on_play)
register_conversion("build_major", CARD_ID, _expand)
