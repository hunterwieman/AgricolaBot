"""Supply Boat (minor improvement, D73; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "Each time after you use the 'Fishing' accumulation space,
you can choose to buy 1 grain for 1 food, or 1 vegetable for 3 food."

Cost: 1 Wood. Prerequisite: 1 Occupation. Printed 1 VP. Not a passing card.
(No errata or clarifications in the card data.)

An OPTIONAL play-variant trigger on the atomic 'Fishing' accumulation space — the
one card-shape that surfaces a *choice between two routes* (buy grain OR buy
vegetable) rather than a single grant.

TIMING — `after_action_space`. The text's "Each time AFTER you use Fishing" is the
explicit "immediately after" exception to the default "each time you use [space]" =
before ruling (the same exception Carpenter's Axe / Wood Cutter rely on), so it
rides the after-phase frame, firing only once Fishing's own pickup (+1 food) has
already happened. That ordering is correct: the food the player pays with may
include this turn's catch.

OPTIONALITY — `register` (NOT `register_auto`). "You can choose to buy" is a
declinable choice, so it is an optional FireTrigger; the decline path is the
host's after-phase `Stop` (reached by simply NOT firing the trigger). Because
declining must always be possible, the variant enumerator gates each route on its
price being PAYABLE (below) so a dead-end fire is never surfaced — with neither
route payable, no FireTrigger is offered and the after-phase `Stop` is the only
action.

PAYMENT (ruling 82, 2026-07-26; this card shipped with a plain food-on-hand gate
and was corrected 2026-07-27): each route's food price is payable by ANY legal
route — food on hand OR raised by the at-any-time crop/animal conversions — so a
route is offered iff ITS OWN price is raise-able (`_liquidatable_to`; 1 food for
grain, 3 for vegetable). Firing buys directly when the food is on hand; short of
it, the fire pushes the raise-only `PendingFoodPayment` (resume kind
`"supply_boat:<route>"` — static variants ride the resume kind, the Canal
Boatman shape), and the resume debits the price and grants the good.

THE OR — the "buy grain OR buy vegetable" choice is collapsed INTO the fire via
`register_play_variant_trigger` (like Cottager's room-vs-renovate, Scholar's
occupation-vs-minor): the after-phase host expands this card's one trigger into a
distinct `FireTrigger("supply_boat", variant="grain")` / `variant="vegetable"` per
currently-payable route, and `_apply` takes the chosen variant. This is a
play-variant in the trigger EFFECT, not a "/" alternative in the minor's purchase
cost (which is a flat 1 wood), so it is fully supported.

APPLY — a direct resource swap (buy exactly one good): grain route -1 food /
+1 grain; vegetable route -3 food / +1 vegetable. No sub-frame or resolver of its
own (mirroring Potter Ceramics' direct exchange, variant-threaded) — only the
food-short fire detours through the raise frame before the same swap runs.

"Each time" = at most once per Fishing use, enforced by the host frame's
`triggers_resolved` (handled by `_apply_fire_trigger`): each new Fishing use pushes
a fresh PendingActionSpace with an empty `triggers_resolved`, so the card
re-becomes eligible on the next use. Fishing is an ATOMIC accumulation space, so it
must be explicitly hosted (`register_action_space_hook`) to push a frame whose
after-phase surfaces this trigger. No on-play effect.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_minor
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

CARD_ID = "supply_boat"
SPACES = frozenset({"fishing"})

# Printed prices: 1 grain for 1 food; 1 vegetable for 3 food.
_GRAIN_PRICE = 1
_VEG_PRICE = 3

# route -> (its food price, the good bought).
_ROUTES: dict[str, tuple[int, Resources]] = {
    "grain":     (_GRAIN_PRICE, Resources(grain=1)),
    "vegetable": (_VEG_PRICE, Resources(veg=1)),
}


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The buy routes whose OWN price is raise-able — food on hand or the
    at-any-time conversions (ruling 82): 'grain' at 1 food, 'vegetable' at 3.
    Empty list -> nothing buyable this use (so no FireTrigger is offered and the
    host's after-phase Stop is the only action — i.e. declining is the sole
    option)."""
    p = state.players[idx]
    return [route for route, (price, _) in _ROUTES.items()
            if _liquidatable_to(state, idx, p, Resources(food=price))]


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # after_action_space on the fishing host. Ownership + once-per-use
    # (triggers_resolved) are already gated by _eligible_fire_triggers; here we only
    # check the space and that at least one route is payable.
    top = state.pending_stack[-1]
    return (getattr(top, "space_id", None) in SPACES
            and bool(_legal_variants(state, idx)))


def _buy(state: GameState, idx: int, variant: str) -> GameState:
    """Buy exactly one good — the chosen route's direct resource swap. Reached
    directly (food on hand) and as the post-food-payment resume (the raise-only
    frame leaves the raised food in supply to debit)."""
    price, bought = _ROUTES[variant]
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=price) + bought)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one buy. With the food on hand, buy directly; otherwise push the
    raise-only PendingFoodPayment — the route is STATIC, so it rides the
    resume_kind itself ("supply_boat:<route>", one registered resume per route),
    and the buy reserves nothing (its only cost is the food)."""
    price, _ = _ROUTES[variant]
    if state.players[idx].resources.food >= price:
        return _buy(state, idx, variant)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=price,
        resume_kind=f"{CARD_ID}:{variant}", reserved=Cost(),
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)),
               min_occupations=1, vps=1)
register("after_action_space", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_action_space_hook(CARD_ID, SPACES)
# One resume per (static) route: the raise-only food frame's resume_kind carries
# the chosen route (ruling 82's payment shape).
for _v in _ROUTES:
    register_food_payment_resume(
        f"{CARD_ID}:{_v}", (lambda v: lambda state, idx: _buy(state, idx, v))(_v))
