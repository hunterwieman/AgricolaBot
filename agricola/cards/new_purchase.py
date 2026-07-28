"""New Purchase (minor improvement, B70; Bubulcus Expansion; free).

Card text (verbatim): "Before the start of each round that ends with a harvest,
you can buy one of each of the following crops: 2 Food → 1 Grain; 4 Food → 1
Vegetable"

No cost, no prerequisite, not passing, no printed VPs.

Category: a preparation-ladder window trigger — an OPTIONAL `before_round`
play-variant trigger (the Forest Trader per-route shape, hosted on the
`before_round` window like Civic Facade's income).

- **Timing.** "Before the start of each round" → the preparation ladder's FIRST
  rung, `before_round` (user ruling 2026-07-14; Civic Facade). At that window
  `round_number` still names the just-completed round, so the round being entered
  is `round_number + 1`; "each round that ends with a harvest" gates eligibility on
  `round_number + 1 ∈ HARVEST_ROUNDS` (rounds 4/7/9/11/13/14).

- **Optional + a choice.** "you can buy one of each of the following crops" — up to
  one grain AND up to one vegetable, in a single decision. Modeled as a
  play-variant trigger (declined by the window host's Proceed), with the routes:
    - `grain` — 2 food → 1 grain,
    - `veg`   — 4 food → 1 vegetable,
    - `both`  — 6 food → 1 grain + 1 vegetable.
  The `both` route is what makes "one of EACH" reachable: the window frame's
  `triggers_resolved` allows only one fire per round, so buying both crops must be
  a single combined route. Goods-only (food → crops); nothing to accommodate.

- **Payment.** Each route's food price is payable by ANY legal route — food on
  hand OR raised by the at-any-time crop/animal conversions (ruling 82,
  2026-07-26: a plain food-on-hand gate makes rules-legal moves unplayable; this
  card shipped with that defect and was corrected 2026-07-27). A route is
  offered iff ITS OWN price is raise-able (`_liquidatable_to` — with 2 food's
  worth of convertibles only `grain` appears). Firing buys directly when the
  food is on hand; short of food it pushes the raise-only `PendingFoodPayment`
  (resume kind `"new_purchase:<route>"` — static variants ride the resume kind,
  the Canal Boatman shape).

`PendingCardChoice` is deliberately NOT used — it has no decline, and this whole
option is declinable; the play-variant path carries the decline at the window's
Proceed. Card-only registries; the Family game is byte-identical.
"""
from __future__ import annotations

from agricola.cards.display import register_action_labeler
from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.constants import HARVEST_ROUNDS
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "new_purchase"

# route -> (food spent, resources gained)
_ROUTES = {
    "grain": Resources(food=-2, grain=1),
    "veg":   Resources(food=-4, veg=1),
    "both":  Resources(food=-6, grain=1, veg=1),
}

# route -> its food price (the printed table; `both` is the two prices summed).
_PRICES = {route: -delta.food for route, delta in _ROUTES.items()}


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The crop-buy routes whose OWN price is raise-able (food on hand or the
    at-any-time conversions — ruling 82). Empty -> the trigger is not offered."""
    p = state.players[idx]
    return [route for route in _ROUTES
            if _liquidatable_to(state, idx, p, Resources(food=_PRICES[route]))]


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # "each round that ends with a harvest": the round being ENTERED (round_number
    # + 1, since before_round precedes the round-number increment) is a harvest round.
    return ((state.round_number + 1) in HARVEST_ROUNDS
            and bool(_legal_variants(state, idx)))


def _buy(state: GameState, idx: int, variant: str) -> GameState:
    """Pay the route's food price, gain its crops. Reached directly (food on
    hand) and as the post-food-payment resume (the raise-only frame leaves the
    raised food in supply to debit)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + _ROUTES[variant])
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one route. With the food on hand, buy directly; otherwise push the
    raise-only PendingFoodPayment — the route is STATIC, so it rides the
    resume_kind itself ("new_purchase:<route>", one registered resume per
    route), and the buy reserves nothing (its only cost is the food)."""
    price = _PRICES[variant]
    if state.players[idx].resources.food >= price:
        return _buy(state, idx, variant)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=price,
        resume_kind=f"{CARD_ID}:{variant}", reserved=Cost(),
    ))


def _action_label(variant: str):
    return {
        "grain": "buy 1 grain (2 food)",
        "veg":   "buy 1 vegetable (4 food)",
        "both":  "buy 1 grain + 1 vegetable (6 food)",
    }.get(variant)


register_minor(CARD_ID)
register("before_round", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_action_labeler(CARD_ID, _action_label)
# One resume per (static) route: the raise-only food frame's resume_kind carries
# the chosen route (ruling 82's payment shape).
for _v in _ROUTES:
    register_food_payment_resume(
        f"{CARD_ID}:{_v}", (lambda v: lambda state, idx: _buy(state, idx, v))(_v))
