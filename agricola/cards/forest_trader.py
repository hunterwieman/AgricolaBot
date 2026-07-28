"""Forest Trader (occupation, Dulcinaria D125; players 1+).

Card text: "Each time you use a wood or clay accumulation space, you can also buy
exactly 1 building resource. Wood, clay, and reed cost 1 food each; stone costs 2
food."

An OPTIONAL trigger on the BEFORE window — "each time you use [space]" fires in the
before phase of the space per the standing Trigger-Timing ruling — surfaced WIDE as
play-variants (user decision 2026-07-14): the host enumerator expands the one trigger
into a distinct `FireTrigger("forest_trader", variant=<resource>)` per PAYABLE
purchase route.

PAYMENT (ruling 82, 2026-07-26; this card shipped with a plain food-on-hand gate
and was corrected 2026-07-27): each route's food price is payable by ANY legal
route — food on hand OR raised by the at-any-time crop/animal conversions, so
`_legal_variants` filters each of wood / clay / reed / stone on ITS OWN price
being raise-able (`_liquidatable_to`; an empty list means the trigger is simply
not offered). Firing a variant buys directly when the food is on hand; short of
it, the fire pushes the raise-only `PendingFoodPayment` (resume kind
`"forest_trader:<resource>"` — static variants ride the resume kind, the Canal
Boatman shape), and the resume debits the price and grants exactly 1 of that
building resource. Declining is just not firing — the host's Proceed is the
decline path (no decline variant, no SkipTrigger). The host's `triggers_resolved`
makes it fire at most once per use of the space ("exactly 1 building resource"),
handled automatically by the firing machinery.

At 2 players the wood accumulation space is Forest (`forest`) and the clay
accumulation space is Clay Pit (`clay_pit`) — both ATOMIC, so they are hosted via
`register_action_space_hook`. 3–4 players adds Copse/Grove (wood) and Hollow (clay);
the space set extends with the 4-player work.

No stranding concern: the space's mandatory work (taking the accumulated goods)
needs no resources, so spending food before it cannot strand it — and a mid-raise
pause leaves the host frame beneath the payment frame, so the take still lands at
the host's Proceed after the resume. Played via Lessons; its on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import (
    register_food_payment_resume,
    register_occupation,
)
from agricola.cards.triggers import (
    register,
    register_action_space_hook,
    register_play_variant_trigger,
)
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "forest_trader"

# 2-player: Forest (wood accumulation) + Clay Pit (clay accumulation). 3–4-player
# board extensions add Copse / Grove (wood) and Hollow (clay) — extend with the
# 4-player work.
SPACES = frozenset({"forest", "clay_pit"})

# Purchase price in food per 1 of the building resource ("Wood, clay, and reed cost
# 1 food each; stone costs 2 food").
PRICES = {"wood": 1, "clay": 1, "reed": 1, "stone": 2}


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The purchases currently payable: each building resource whose food price
    is raise-able — on hand or by the at-any-time conversions (ruling 82), each
    filtered on its OWN price. Empty list -> the trigger is not offered."""
    p = state.players[idx]
    return [r for r in ("wood", "clay", "reed", "stone")
            if _liquidatable_to(state, idx, p, Resources(food=PRICES[r]))]


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # "each time you use a wood or clay accumulation space" -> before_action_space
    # on the forest / clay_pit hosts. The host's triggers_resolved (handled by
    # _apply_fire_trigger) prevents re-firing within one use, giving the
    # buy-exactly-1-per-use semantics.
    top = state.pending_stack[-1]
    return (getattr(top, "space_id", None) in SPACES
            and bool(_legal_variants(state, idx)))


def _buy(state: GameState, idx: int, variant: str) -> GameState:
    """Buy exactly 1 of the chosen building resource: debit the food price,
    grant the resource. Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the raised food in
    supply to debit)."""
    price = PRICES[variant]
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(
        food=-price, **{variant: 1}))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one purchase. With the food on hand, buy directly; otherwise push
    the raise-only PendingFoodPayment — the resource is STATIC, so it rides the
    resume_kind itself ("forest_trader:<resource>", one registered resume per
    resource), and the buy reserves nothing (its only cost is the food)."""
    if state.players[idx].resources.food >= PRICES[variant]:
        return _buy(state, idx, variant)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=PRICES[variant],
        resume_kind=f"{CARD_ID}:{variant}", reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_action_space_hook(CARD_ID, SPACES)   # host Forest / Clay Pit when owned
# One resume per (static) resource: the raise-only food frame's resume_kind
# carries the chosen resource (ruling 82's payment shape).
for _v in PRICES:
    register_food_payment_resume(
        f"{CARD_ID}:{_v}", (lambda v: lambda state, idx: _buy(state, idx, v))(_v))
