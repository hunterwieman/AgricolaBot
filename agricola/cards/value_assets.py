"""Value Assets (minor improvement, B82; Bubulcus Expansion; Building Resource Provider).

Card text (verbatim): "After each harvest, you can buy exactly one of the
following goods: 1 Food → 1 Wood; 1 Food → 1 Clay; 2 Food → 1 Reed; 2 Food →
1 Stone"
No cost. No prerequisite. VPs: 0 (printed blank). Not passing.

A recurring, optional, once-per-harvest purchase: after every harvest the owner
may spend food to buy exactly one building resource — wood or clay for 1 food,
reed or stone for 2 food.

TIMING — the ``after_harvest`` window. The printed "after each harvest" maps to
the harvest ladder's ``after_harvest`` window
(``agricola/cards/harvest_windows.py``; design of record
``design_docs/cards/HARVEST_WINDOWS_DESIGN.md`` §1), OUTSIDE the harvest,
strictly after ``end_of_harvest``. Per user ruling 18 (2026-07-05),
"immediately after each harvest" and "after each harvest" name the SAME
instant — one window — so this card shares the window (and, for a player owning
both, the same per-player choice frame) with Elephantgrass Plant ("immediately
after each harvest": 1 reed → 1 bonus point). Within the shared frame the owner
fires the two cards in either order, and one card's proceeds can feed the
other: a reedless player may buy a reed here (2 food) and then swap it to
Elephantgrass Plant for the bonus point — a documented consequence of the
one-window ruling. The window also runs after the FINAL harvest (round 14,
before scoring): buying a building resource there is pointless but legal, and
the trigger fires like any other harvest's.

THE EFFECT — "you CAN buy" is optional, so this is a declinable TRIGGER
(``register`` on the ``after_harvest`` window event), not an automatic effect.
It surfaces as a ``FireTrigger`` on the per-player ``PendingHarvestWindow``
host; ``Proceed`` declines.

ONCE PER HARVEST — "buy EXACTLY ONE of the following goods" is a single
purchase per harvest. The per-player ``PendingHarvestWindow`` frame's
``triggers_resolved`` gives this for free: firing the trigger marks the card
resolved for this window, so it cannot fire again in the same harvest (and the
window itself fires once per harvest). No manual bookkeeping.

THE CHOICE — four purchase variants, one per output good, whose PRICES DIFFER:
wood and clay cost 1 food each, reed and stone cost 2 food each. It is modeled
as a play-variant optional trigger (mirroring ``farm_store.py``): the trigger
surfaces as one ``FireTrigger(card_id, variant)`` per PAYABLE output, and the
player fires exactly one (or ``Proceed`` declines).

PAYMENT — each variant's food price is payable by ANY legal route: food on hand
OR raised by the at-any-time crop/animal conversions (ruling 82, 2026-07-26: a
plain food-on-hand gate makes rules-legal moves unplayable; this card shipped
with that defect and was corrected 2026-07-27). Because the prices differ, a
variant is offered iff ITS OWN price is raise-able (``_liquidatable_to`` — with
1 food's worth of convertibles only wood and clay appear). Firing buys directly
when the food is on hand; short of it, the fire pushes the raise-only
``PendingFoodPayment`` (resume kind ``"value_assets:<good>"`` — static variants
ride the resume kind, the Canal Boatman shape), and the resume debits the price
and grants the good. Window #17 sits OUTSIDE the harvest conversion span (user
ruling 85, 2026-07-27: the converters close after the breed phase's last
conversion opportunity, immediately before ``end_of_harvest``), so the raise
draws on the plain crop/animal liquidation rates — and the same ruling RESOLVED
the open question this docstring used to flag about ruling 39's post-breed
cooking floors binding here: the floors lapse at the ``end_of_harvest`` moment,
so they do not bind at this window either, and a purchase may be paid by
cooking a just-bred animal.

Card-only state is empty in the Family game (this card is card-game only), so
the Family engine stays byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_food_payment_resume, register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "value_assets"
WINDOW_ID = "after_harvest"

# The four purchase variants, straight off the printed table. tag -> (food
# price, the resource bought). The prices differ per output — wood/clay cost
# 1 food, reed/stone cost 2 — so raise-ability is checked per variant.
_PURCHASES: dict[str, tuple[int, Resources]] = {
    "wood":  (1, Resources(wood=1)),
    "clay":  (1, Resources(clay=1)),
    "reed":  (2, Resources(reed=1)),
    "stone": (2, Resources(stone=1)),
}


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the purchase iff this player owns Value Assets AND at least one
    variant's price is raise-able (ruling 82 — food on hand or the at-any-time
    conversions; the cheapest price is 1 food).

    Ownership: registrations are global, so the minor-ownership check lives
    here (the window enumerator also gates on ownership, but keeping it here is
    explicit and matches the surrounding card idioms). The once-per-window
    limit is handled by the frame's ``triggers_resolved`` (checked by the
    enumerator, not here)."""
    p = state.players[idx]
    return CARD_ID in p.minor_improvements and bool(_variants(state, idx))


def _variants(state: GameState, idx: int) -> list[str]:
    """The payable purchase variants, in the printed table's order. The prices
    differ per output (wood/clay 1 food, reed/stone 2 food), so each variant is
    filtered on its OWN price being raise-able (ruling 82) — with 1 food's
    worth of convertibles only wood and clay are offered."""
    p = state.players[idx]
    return [tag for tag, (price, _) in _PURCHASES.items()
            if _liquidatable_to(state, idx, p, Resources(food=price))]


def _buy(state: GameState, idx: int, variant: str) -> GameState:
    """Pay the chosen variant's food price and gain the bought resource (net
    −price food + 1 of the good). Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the raised food in
    supply to debit)."""
    price, bought = _PURCHASES[variant]
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=price) + bought)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one purchase. With the food on hand, buy directly; otherwise push
    the raise-only PendingFoodPayment — the good is STATIC, so it rides the
    resume_kind itself ("value_assets:<good>", one registered resume per good),
    and the buy reserves nothing (its only cost is the food)."""
    price, _ = _PURCHASES[variant]
    if state.players[idx].resources.food >= price:
        return _buy(state, idx, variant)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=price,
        resume_kind=f"{CARD_ID}:{variant}", reserved=Cost(),
    ))


# No cost, no prerequisite, printed VP blank (0).
register_minor(CARD_ID, vps=0)

# Optional play-variant trigger on the after_harvest window ("after each
# harvest" — one window shared with the "immediately after" cards per user
# ruling 18, 2026-07-05): buy exactly one building resource per harvest, at
# the printed per-good food price (the frame's triggers_resolved gives
# once-per-window).
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
# One resume per (static) good: the raise-only food frame's resume_kind carries
# the chosen good (ruling 82's payment shape).
for _v in _PURCHASES:
    register_food_payment_resume(
        f"{CARD_ID}:{_v}", (lambda v: lambda state, idx: _buy(state, idx, v))(_v))
