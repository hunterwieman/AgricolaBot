"""Plumber (occupation, deck B #128; Bubulcus Expansion; players 3+).

Card text (verbatim): "Each time after you use the "Major Improvement" action
space, you can take a "renovation" action, paying 2 clay or 2 stone less for the
renovation."
Category: Farm Planner. No printed VPs.

The grant-scoped-renovate pattern proved by Master Renovator (E87), placed on the
Major Improvement action space's own after-window:

- **the window.** "Each time AFTER you use the 'Major Improvement' action space"
  is the explicit AFTER phase of THAT space. The space is hosted by a
  PendingSubActionSpace wrapper (initiated_by_id "space:major_improvement",
  space_id "major_improvement") that carries the space's own `action_space`
  surface ABOVE the composite's `major_minor_improvement` surface (resolution.py
  `_initiate_major_improvement` — the wrapper exists precisely to give Plumber
  this surface, distinct from Merchant riding the composite). So the grant is an
  OPTIONAL `after_action_space` trigger filtered to space_id == "major_improvement"
  (NOT House Redevelopment, NOT a card grant of the composite). Firing pushes a
  standard PendingRenovate with this card's provenance; declining is the host's
  Stop. Once per use via the host's `triggers_resolved`.

- **the discount.** "paying 2 clay or 2 stone less" is NOT a payment-time choice
  (unlike Master Renovator's "1 resource of your choice less"): a renovation's
  cost is in exactly ONE material — clay for wood->clay, stone for clay->stone —
  so the "2 clay OR 2 stone" is fixed by which renovation is performed. That is a
  choice-free REDUCTION, scoped to THIS card's grant via `CostCtx.granted_by` (the
  PendingRenovate enumerator threads the frame's `initiated_by_id` into the cost
  context; None for every space-initiated renovate). Reducing {clay:2, stone:2}
  floored at 0 subtracts 2 only from the material actually in the cost. A House
  Redevelopment / Farm Redevelopment renovate is never discounted.

ELIGIBILITY mirrors legality._can_renovate (a legal target exists; house not
stone; Mantlepiece's permanent ban respected) but resolves affordability through
the GRANT-scoped ctx (`_renovate_ctx(p, t, granted_by=_PROVENANCE)`), so the -2
discount can itself make the renovate affordable. Never a dead-end offer.

Played via Lessons; card-only registries (no CardStore) — the Family game is
byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.cards.triggers import register
from agricola.legality import _legal_renovate_targets, _renovate_ctx, can_pay
from agricola.pending import PendingRenovate, push
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "plumber"
_PROVENANCE = f"card:{CARD_ID}"
_SPACE = "major_improvement"


def _eligible(state: GameState, idx: int, _resolved) -> bool:
    """After a Major Improvement use, the player can actually renovate NOW.

    Filters to the Major Improvement action space's after-window (the
    PendingSubActionSpace wrapper, space_id "major_improvement"), then mirrors
    legality._can_renovate with affordability resolved through the grant-scoped
    ctx, so a renovate only the -2 discount makes payable still qualifies.
    Once-per-window comes from the frame's triggers_resolved."""
    if getattr(state.pending_stack[-1], "space_id", None) != _SPACE:
        return False
    p = state.players[idx]
    if "mantlepiece" in p.minor_improvements:   # renovation permanently forbidden
        return False
    return any(
        can_pay(state, idx, _renovate_ctx(p, t, granted_by=_PROVENANCE))
        for t in _legal_renovate_targets(state, p))


def _apply(state: GameState, idx: int) -> GameState:
    """Push the granted renovate carrying this card's provenance — what the
    enumerator threads into CostCtx.granted_by, scoping the reduction below to
    exactly this grant."""
    return push(state, PendingRenovate(
        player_idx=idx, initiated_by_id=_PROVENANCE))


def _reduce(state, idx, ctx, cost: Resources) -> Resources:
    """"pay 2 clay or 2 stone less": subtract 2 from BOTH clay and stone (the
    fold floors at 0), so only the material actually in the renovate cost is
    reduced. Scoped to this card's own grant via ctx.granted_by; every other
    renovate passes through unchanged."""
    if ctx.granted_by != _PROVENANCE:
        return cost
    return cost - Resources(clay=2, stone=2)


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect
register("after_action_space", CARD_ID, _eligible, _apply)
register_reduction("renovate", CARD_ID, _reduce)
