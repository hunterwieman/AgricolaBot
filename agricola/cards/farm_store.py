"""Farm Store (minor improvement, C41; Consul Dirigens Expansion; Goods Provider).

Card text (verbatim): "After the feeding phase of each harvest, you can exchange
exactly 1 food for 2 different building resources of your choice or 1 vegetable."
Cost: 2 Wood, 2 Clay. VPs: 0 (printed blank). No prerequisite. Not passing.

TIMING — the ``after_feeding`` window. The printed "after the feeding phase of
each harvest" maps to the harvest ladder's ``after_feeding`` window
(``agricola/cards/harvest_windows.py``; design of record
``design_docs/cards/HARVEST_WINDOWS_DESIGN.md`` §1). Per the user ruling of
2026-07-05, "immediately after the feeding phase" (Social Benefits) is the SAME
instant — one window — and the ruled ordering is Social Benefits FIRST, carried
by the standing autos-before-triggers convention (Social Benefits is an
automatic effect; this card is an optional trigger). The anti-food-laundering
property holds: the effect fires post-payment, so the food it spends can never
pay a feeding cost that has already resolved, and Social Benefits' "if you have
no food left" check runs before this exchange can spend the last food. This is
the timing home the card was originally shelved for lacking; the
previously-sketched "``PendingHarvestFeed`` after-phase" is realized as this
ladder window (design doc §5, 2026-07-05 un-archival).

THE EFFECT — "you CAN exchange" is optional, so this is a declinable TRIGGER
(``register`` on the ``after_feeding`` window event), not an automatic effect.
It surfaces as a ``FireTrigger`` on the per-player ``PendingHarvestWindow`` host;
``Proceed`` declines.

ONCE PER HARVEST — "exchange EXACTLY 1 food" is a single exchange per harvest.
The per-player ``PendingHarvestWindow`` frame's ``triggers_resolved`` gives this
for free: firing the trigger marks the card resolved for this window, so it
cannot fire again in the same harvest (and the window itself fires once per
harvest). No manual bookkeeping.

THE CHOICE — "2 different building resources of your choice OR 1 vegetable" is a
choice of OUTPUT (the input is always exactly 1 food). The building resources are
the four building materials {wood, clay, reed, stone} (scoring.py's
building-resource set); "2 DIFFERENT" rules out doubles (no wood+wood), so the
building-resource option is exactly the six distinct unordered pairs C(4,2) over
{wood, clay, reed, stone}. With the single-vegetable option that is seven output
variants. It is modeled as a play-variant optional trigger (mirroring
``home_brewer.py``): the trigger surfaces as one ``FireTrigger(card_id, variant)``
per output, and the player fires exactly one (or ``Proceed`` declines).

PAYMENT — the 1 food is payable by ANY legal route: food on hand OR raised by
the at-any-time crop/animal conversions (ruling 82, 2026-07-26: a plain
food-on-hand gate makes rules-legal moves unplayable; this card shipped with
that defect and was corrected 2026-07-27). The variants are offered iff the
1-food price is raise-able (``_liquidatable_to`` — this window sits INSIDE the
harvest conversion span, where the gate delegates to the same frontier the
raise frame enumerates, once-per-harvest span converters and the ruling-39
post-breed floors included). Firing exchanges directly when the food is on
hand; short of it, the fire pushes the raise-only ``PendingFoodPayment``
(resume kind ``"farm_store:<output>"`` — static variants ride the resume kind,
the Canal Boatman shape), and the resume debits the 1 food and grants the
chosen output. Either way the player only ever spends value they still hold
after feeding — the window is post-payment.

Card-only state is empty in the Family game (this card is card-game only), so the
Family engine stays byte-identical and the C++ gates are untouched.
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

CARD_ID = "farm_store"
WINDOW_ID = "after_feeding"

# The seven output variants: the six distinct unordered building-resource pairs
# over {wood, clay, reed, stone} ("2 different building resources"), plus the
# single-vegetable option. tag -> the goods granted for spending 1 food.
_OUTPUTS: dict[str, Resources] = {
    "wood_clay":  Resources(wood=1, clay=1),
    "wood_reed":  Resources(wood=1, reed=1),
    "wood_stone": Resources(wood=1, stone=1),
    "clay_reed":  Resources(clay=1, reed=1),
    "clay_stone": Resources(clay=1, stone=1),
    "reed_stone": Resources(reed=1, stone=1),
    "veg":        Resources(veg=1),
}


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Usable iff the 1-food input is raise-able — on hand or by the at-any-time
    conversions (ruling 82). Ownership and the once-per-window guard are enforced
    by the host enumerator (via ``_owns`` and the frame's ``triggers_resolved``);
    firing marks the card resolved for this window, so it exchanges at most once
    per harvest."""
    p = state.players[idx]
    return _liquidatable_to(state, idx, p, Resources(food=1))


def _variants(state: GameState, idx: int) -> list[str]:
    """The seven output choices. The input is always exactly 1 food, so every
    variant shares the same raise-ability gate; re-check here so the enumerator
    never surfaces an unpayable variant."""
    if not _eligible(state, idx, frozenset()):
        return []
    return list(_OUTPUTS)


def _exchange(state: GameState, idx: int, variant: str) -> GameState:
    """Spend exactly 1 food and grant the chosen output's goods (net −1 food +
    the chosen goods). Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the raised food in
    supply to debit)."""
    out = _OUTPUTS[variant]
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=1) + out)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one exchange. With the food on hand, exchange directly; otherwise
    push the raise-only PendingFoodPayment — the output is STATIC, so it rides
    the resume_kind itself ("farm_store:<output>", one registered resume per
    output), and the exchange reserves nothing (its only cost is the food)."""
    if state.players[idx].resources.food >= 1:
        return _exchange(state, idx, variant)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=1,
        resume_kind=f"{CARD_ID}:{variant}", reserved=Cost(),
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2, clay=2)), vps=0)

# Optional play-variant trigger on window #11 (after_feeding): spend exactly 1
# food for one of seven outputs, once per harvest (the frame's triggers_resolved
# gives once-per-window).
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
# One resume per (static) output: the raise-only food frame's resume_kind
# carries the chosen output (ruling 82's payment shape).
for _v in _OUTPUTS:
    register_food_payment_resume(
        f"{CARD_ID}:{_v}",
        (lambda v: lambda state, idx: _exchange(state, idx, v))(_v))
