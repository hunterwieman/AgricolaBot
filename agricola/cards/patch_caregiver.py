"""Patch Caregiver (occupation, B113; Bubulcus Expansion; players 1+).

Card text (verbatim): "When you play this card, you can choose to buy 1 grain
for 1 food, or 1 vegetable for 3 food. This card is a field."

Two independent pieces:

1. **The on-play buy — WIDE play variants (user ruling 17, 2026-07-05,
   generalized by ruling 24, 2026-07-06 for minors):** an on-play optional
   grant is a set of distinct `CommitPlayOccupation` variants, NOT an
   after-play trigger — so the granted choice cannot interleave with other
   after-play triggers in player-chosen order. Three routes: "buy_grain"
   (1-food surcharge -> +1 grain), "buy_veg" (3-food surcharge -> +1 veg),
   and "decline" (the bare play). Each buy's food price is the variant's
   SURCHARGE on top of the base play cost (FOOD_PAYMENT_DESIGN.md §8 — the
   Roof Ballaster mechanism): all three routes are returned unconditionally,
   and the play-occupation enumerator offers only those whose
   base-cost + surcharge is payable (liquidation-aware `_payable`), so a buy
   is offered exactly when the player can cover its food after the play
   route's own cost. `_execute_play_occupation` debits the surcharge (raising
   any food shortfall via the shared food-payment path) before this module's
   on_play grants the bought good — the on_play never touches the food.

2. **"This card is a field" — a registered card-field
   (`agricola/cards/card_fields.py`), unrestricted, 1 stack:** sowable with
   grain (plants 3) or vegetables (plants 2), harvested by the field-phase
   take, exactly like a plowed board field. Ruling 45 (2026-07-12): it counts
   as exactly 1 field for every field-count reader (the Fields scoring
   category, "N fields" requirements) — and is NEVER a field TILE
   (ruling 32, 2026-07-06: tile readers filter to "cell:" sources). Ruling 47
   (2026-07-12): stacks=1 — no "as though it were N fields" clause. Note this
   is an OCCUPATION that is a field: the card-field machinery's ownership
   check covers occupations (`owned_card_fields` reads both
   `minor_improvements` and `occupations`).
"""
from __future__ import annotations

from agricola.cards.card_fields import register_card_field
from agricola.cards.specs import (
    register_occupation,
    register_play_occupation_variant,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "patch_caregiver"


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """The three play routes, each declaring its food SURCHARGE on top of the
    base play cost (FOOD_PAYMENT_DESIGN.md §8). All returned unconditionally —
    affordability of base+surcharge (with liquidation) is filtered by the
    play-occupation enumerator, which knows the base play cost (the
    Roof Ballaster idiom; a pre-debit food check here could drive food
    negative on a costed play)."""
    return [
        ("decline", Resources()),
        ("buy_grain", Resources(food=1)),
        ("buy_veg", Resources(food=3)),
    ]


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Grant the bought good for a buy variant. The food surcharge is NOT
    debited here — it is folded into the play cost and debited by
    `_execute_play_occupation` (raising it via the shared food-payment path if
    short) before this runs (FOOD_PAYMENT_DESIGN.md §8)."""
    if variant == "buy_grain":
        bought = Resources(grain=1)
    elif variant == "buy_veg":
        bought = Resources(veg=1)
    else:
        return state                       # declined at the wide play choice
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + bought)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
register_card_field(CARD_ID, stacks=1, sow_amounts=(("grain", 3), ("veg", 2)))
