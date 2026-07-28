"""Green Grocer (occupation, Corbarius C103; players 1+).

Card text: "At the start of each round, you can make exactly one of the following
exchanges: 1 Cattle → 1 Vegetable; 1 Vegetable → 1 Cattle; 2 Sheep → 1 Vegetable;
1 Vegetable → 2 Sheep; 2 Food → 1 Grain; 1 Grain → 2 Food"

User decision (2026-07-14): the six exchanges are surfaced WIDE — one
FireTrigger(card_id, variant=...) per currently-payable exchange (the standard
start-of-round play-variant expansion, Scholar's shape), not a nested choice frame.

A start-of-round OPTIONAL play-variant trigger on the preparation ladder's
`start_of_round` window (ruling 54, 2026-07-14): the window's choice host surfaces
one FireTrigger per payable exchange; "do none" = the host's Proceed. "Exactly
one" exchange per round = the host frame's `triggers_resolved` (one fire per host
visit — automatic) + the `used_this_round` latch (cleared at each round entry, so
next round offers again) — Scholar's once-per-round shape, mirrored.

PAYMENT. Five of the six exchanges spend goods/animals, which have no
raise-them-first route — their inputs must be on hand, the plain checks. The one
FOOD-priced exchange, `food2_to_grain` (2 Food → 1 Grain), is different: a food
price is payable by ANY legal route — food on hand OR raised by the at-any-time
crop/animal conversions (ruling 82, 2026-07-26: a plain food-on-hand gate makes
rules-legal moves unplayable; this card shipped with that defect and was
corrected 2026-07-27). It is therefore offered iff 2 food is raise-able
(`_liquidatable_to`); fired with the food on hand it exchanges directly, and
short of food it pushes the raise-only `PendingFoodPayment` (resume kind
`"green_grocer:food2_to_grain"` — a static variant rides the resume kind, the
Canal Boatman shape) whose resume runs the same exchange.

Spends are direct edits (animals straight off `p.animals` — discarding animals is
free at any time; goods off `p.resources`). Animal GAINS route through
`helpers.grant_animals` (veg_to_cattle: +1 cattle; veg_to_sheep2: +2 sheep) so the
accommodation barrier surfaces the keep-which choice when the farm can't house
them. On-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import (
    register_food_payment_resume,
    register_occupation,
)
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.helpers import grant_animals
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

CARD_ID = "green_grocer"

# The six printed exchanges, in card-text order. Each variant maps to
# (payability predicate, direct player edit, animal grant).
_VARIANTS = (
    "cattle_to_veg",   # 1 Cattle  → 1 Vegetable
    "veg_to_cattle",   # 1 Vegetable → 1 Cattle
    "sheep2_to_veg",   # 2 Sheep   → 1 Vegetable
    "veg_to_sheep2",   # 1 Vegetable → 2 Sheep
    "food2_to_grain",  # 2 Food    → 1 Grain
    "grain_to_food2",  # 1 Grain   → 2 Food
)


def _payable(state: GameState, idx: int, variant: str) -> bool:
    """Can `idx` pay the variant's input right now? Goods/animal inputs are
    plain on-hand checks (nothing raises a cattle or a vegetable); the one FOOD
    input (`food2_to_grain`) is raise-able — on hand or by the at-any-time
    conversions (ruling 82)."""
    p = state.players[idx]
    if variant == "cattle_to_veg":
        return p.animals.cattle >= 1
    if variant == "veg_to_cattle":
        return p.resources.veg >= 1
    if variant == "sheep2_to_veg":
        return p.animals.sheep >= 2
    if variant == "veg_to_sheep2":
        return p.resources.veg >= 1
    if variant == "food2_to_grain":
        return _liquidatable_to(state, idx, p, Resources(food=2))
    if variant == "grain_to_food2":
        return p.resources.grain >= 1
    raise ValueError(f"unknown Green Grocer variant {variant!r}")


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """The exchanges payable right now, in card-text order. Empty → nothing
    to exchange this round (the trigger is withheld)."""
    return [v for v in _VARIANTS if _payable(state, idx, v)]


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    p = state.players[idx]
    return (CARD_ID not in p.used_this_round
            and bool(_legal_variants(state, idx)))


def _exchange(state: GameState, idx: int, variant: str) -> GameState:
    """Latch once-per-round, pay the exchange's input directly, then grant the
    output — goods directly, animals via `grant_animals` (the accommodation
    barrier reconciles overflow at the next decision boundary). Reached directly
    and, for `food2_to_grain`, as the post-food-payment resume (the raise-only
    frame leaves the raised food in supply to debit)."""
    p = state.players[idx]
    p = fast_replace(p, used_this_round=p.used_this_round | {CARD_ID})
    if variant == "cattle_to_veg":
        p = fast_replace(p, animals=p.animals - Animals(cattle=1),
                         resources=p.resources + Resources(veg=1))
    elif variant == "sheep2_to_veg":
        p = fast_replace(p, animals=p.animals - Animals(sheep=2),
                         resources=p.resources + Resources(veg=1))
    elif variant == "food2_to_grain":
        p = fast_replace(p, resources=p.resources
                         - Resources(food=2) + Resources(grain=1))
    elif variant == "grain_to_food2":
        p = fast_replace(p, resources=p.resources
                         - Resources(grain=1) + Resources(food=2))
    elif variant in ("veg_to_cattle", "veg_to_sheep2"):
        p = fast_replace(p, resources=p.resources - Resources(veg=1))
    else:
        raise ValueError(f"unknown Green Grocer variant {variant!r}")
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))
    if variant == "veg_to_cattle":
        state = grant_animals(state, idx, Animals(cattle=1))
    elif variant == "veg_to_sheep2":
        state = grant_animals(state, idx, Animals(sheep=2))
    return state


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one exchange. Every non-food-input variant (and `food2_to_grain`
    with the 2 food on hand) exchanges directly; a food-short `food2_to_grain`
    pushes the raise-only PendingFoodPayment whose resume runs the same
    exchange (the latch rides the exchange, which the raise frame — offering
    only complete bundles, no abort — always reaches)."""
    if variant == "food2_to_grain" and state.players[idx].resources.food < 2:
        return push(state, PendingFoodPayment(
            player_idx=idx, food_needed=2,
            resume_kind=f"{CARD_ID}:food2_to_grain", reserved=Cost(),
        ))
    return _exchange(state, idx, variant)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("start_of_round", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
# The one food-priced exchange's resume (ruling 82's payment shape): the
# raise-only food frame's resume_kind names the (static) variant.
register_food_payment_resume(
    f"{CARD_ID}:food2_to_grain",
    lambda state, idx: _exchange(state, idx, "food2_to_grain"))
