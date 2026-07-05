"""Farm Store (minor improvement, C41; Consul Dirigens Expansion; Goods Provider).

Card text (verbatim): "After the feeding phase of each harvest, you can exchange
exactly 1 food for 2 different building resources of your choice or 1 vegetable."
Cost: 2 Wood, 2 Clay. VPs: 0 (printed blank). No prerequisite. Not passing.

TIMING — window #11 ``after_feeding``. The printed "after the feeding phase of
each harvest" maps to the harvest ladder's ``after_feeding`` window
(``agricola/cards/harvest_windows.py``; design of record
``design_docs/cards/HARVEST_WINDOWS_DESIGN.md`` §1 row 11, which names this card
as the ``after_feeding`` member). ``after_feeding`` resolves AFTER the FEED
payment frames (the feeding phase) and after the ``immediately_after_feeding``
window (#10, Social Benefits) — the anti-food-laundering ordering (§1 open-
question #1, design doc §5): because the effect fires post-payment, the food it
spends can never pay a feeding cost that has already resolved, and it runs after
any "if you have no food left" check on the neighbouring window. This is the
timing home the card was originally shelved for lacking; the previously-sketched
"``PendingHarvestFeed`` after-phase" is realized as this ladder window
(design doc §5, 2026-07-05 un-archival).

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

COST — the harvest-window trigger machinery carries no cost layer (like
``winter_caretaker.py``), so ``_apply`` debits the 1 food and grants the chosen
goods in one step, and affordability (>= 1 food) is checked in ``_eligible`` /
``_variants`` so the exchange is offered only when the player can pay. The player
can therefore only ever spend food they still hold after feeding.

Card-only state is empty in the Family game (this card is card-game only), so the
Family engine stays byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
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
    """Usable iff the player holds at least 1 food to spend (the input is always
    exactly 1 food). Ownership and the once-per-window guard are enforced by the
    host enumerator (via ``_owns`` and the frame's ``triggers_resolved``); firing
    marks the card resolved for this window, so it exchanges at most once per
    harvest."""
    return state.players[idx].resources.food >= 1


def _variants(state: GameState, idx: int) -> list[str]:
    """The seven output choices, offered only when 1 food is affordable. The input
    is always exactly 1 food, so every variant shares the same eligibility;
    re-check here so the enumerator never surfaces an unaffordable variant."""
    if state.players[idx].resources.food < 1:
        return []
    return list(_OUTPUTS)


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Spend exactly 1 food and grant the chosen output's goods (net −1 food +
    the chosen goods). The window trigger carries no cost layer, so this debits
    the food and adds the goods in one step."""
    out = _OUTPUTS[variant]
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(food=1) + out)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2, clay=2)), vps=0)

# Optional play-variant trigger on window #11 (after_feeding): spend exactly 1
# food for one of seven outputs, once per harvest (the frame's triggers_resolved
# gives once-per-window).
register(WINDOW_ID, CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _variants)
register_harvest_window_hook(CARD_ID, WINDOW_ID)
