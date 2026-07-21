"""Stone Company (minor improvement, A23; Artifex Expansion; Actions Booster).

Card text: "Immediately after each time you use a \"Quarry\" accumulation
space, you get a \"Major or Minor Improvement\" action during which you must
spend at least 1 stone."
Cost: 2 Clay, 1 Reed. 1 VP. No prerequisite.

Printed clarifications: "You may not decline an automatic stone discount in
order to trigger this card's effect, e.g. from Stonecutter A143. Improvement
action is not declinable in order to use Field Merchant B103."

Rulings (user ruling 2026-07-21):

1. "Immediately after each time you use a Quarry space" = the AFTER window of
   the quarry action-space host: an `after_action_space` trigger filtered to
   space_id in {"western_quarry", "eastern_quarry"}. (The literal id set, not
   `STONE_ACCUMULATION_SPACES`: the card names the "Quarry" spaces, a
   name-match — a future card changing what a space *accumulates* must not
   widen this filter.)
2. The granted action is the NAMED composite — firing pushes
   `PendingMajorMinorImprovement` (so Merchant / Small Trader interact
   correctly) with the minimum-spend constraint `min_spend=Resources(stone=1)`.
   The composite's choose-handler threads the constraint onto the child
   `PendingBuildMajor` / `PendingPlayMinor` frames, whose cost ctx carries it
   into the `effective_payments`/`can_pay` filter (`CostCtx.min_spend`): only
   payments spending >= 1 stone are offered.
3. The Cooking-Hearth return-a-Fireplace route spends no stone, so it never
   satisfies the constraint (the engine's min-spend seam already excludes
   improvement-return routes under a min_spend).
4. A Merchant repeat of this granted action is a fresh, UNconstrained
   composite: Merchant pushes its own `PendingMajorMinorImprovement`, whose
   `min_spend` defaults to None, so the repeat is automatically free of the
   constraint — nothing to do on this card's side.
5. The Stonecutter clarification falls out of the machinery: automatic cost
   reductions fold into the payment candidates BEFORE the min-spend filter, so
   if the discounted frontier no longer spends stone the improvement simply
   doesn't qualify — there is no "decline the discount" route to construct.

Firing kind: a granted ACTION is optional (only "you must" is mandatory, and
this card's "must" governs the payment *inside* the granted action, not taking
it) -> an OPTIONAL trigger (`register`, not `register_auto`); not firing IS the
decline (the host's Stop). Firing pushes the constrained composite with
provenance `"card:stone_company"` and fires the composite's before-autos at
the push — the Merchant/Angler granted-composite idiom.

Eligibility (never push a dead host): the constrained composite must have a
legal child right now — an affordable unowned major under the constraint
(`_can_afford_any_major_improvement(..., min_spend=...)`) or a playable hand
minor under it (`playable_minors(..., composite_only_ok=True, min_spend=...)`)
— the exact predicates the composite's own choose-enumerator uses. The host's
`triggers_resolved` latch makes the grant once per quarry use.

The quarries are ATOMIC accumulation spaces, so `register_action_space_hook`
is required — without it the host frame never pushes and the trigger never
fires. Neither quarry is ever hosted in the Family game (no hooking card), so
this after-window is card-only -> byte-identical, C++ gates untouched. Played
from hand as a normal minor; on-play is a no-op (the effect is the hook).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import (
    apply_auto_effects,
    register,
    register_action_space_hook,
)
from agricola.legality import _can_afford_any_major_improvement, playable_minors
from agricola.pending import PendingMajorMinorImprovement, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "stone_company"
SPACES = frozenset({"western_quarry", "eastern_quarry"})   # the "Quarry" spaces (ruling 1)
MIN_SPEND = Resources(stone=1)   # "you must spend at least 1 stone"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per quarry use
        return False
    top = state.pending_stack[-1]
    if getattr(top, "space_id", None) not in SPACES:
        return False
    # Never push a dead host: the granted composite must have a legal child NOW
    # under the min-spend constraint. Composite grant -> composite-only minors
    # (Wooden Shed) count as legal children.
    return (_can_afford_any_major_improvement(state, state.players[idx],
                                              min_spend=MIN_SPEND)
            or bool(playable_minors(state, idx, composite_only_ok=True,
                                    min_spend=MIN_SPEND)))


def _apply(state: GameState, idx: int) -> GameState:
    state = push(state, PendingMajorMinorImprovement(
        player_idx=idx, initiated_by_id="card:stone_company",
        min_spend=MIN_SPEND,
    ))
    # The composite is itself a host: fire its before-autos at the push
    # (mirrors the engine push sites and Merchant's granted-composite idiom).
    return apply_auto_effects(state, "before_major_minor_improvement", idx)


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=2, reed=1)), vps=1)
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
