"""Winter Caretaker (occupation, C113; Consul Dirigens Expansion; players 1+).

Card text (verbatim): "When you play this card, you immediately get 1 grain. At
the end of each harvest, you can buy exactly 1 vegetable for 2 food."

Category: Crop Provider. Two effects:

1. On play (via Lessons): immediately +1 grain. A one-shot resource grant, the
   same shape as Consultant's on-play.

2. A recurring, optional, once-per-harvest food-to-good buy: spend 2 food, get 1
   vegetable.

Timing — "at the end of each harvest" → window #16 ``end_of_harvest``. Under the
post-breeding-timeline ruling (2026-07-03, ``CARD_DEFERRED_PLANS.md`` → Harvest-
window redesign rulings), "at the end of each harvest" is the last moment INSIDE
the harvest — after the breeding phase and after-breeding effects, before the
immediately-after / after-harvest windows. This is window #16 on the harvest
ladder (``agricola/cards/harvest_windows.py``), so the buy is registered as an
OPTIONAL TRIGGER there (a ``PendingHarvestWindow`` ``FireTrigger``; declining is
the frame's ``Proceed``).

"buy EXACTLY 1": the once-per-window frame gives this for free — its
``triggers_resolved`` records the fire, so after buying, the trigger is no longer
offered for the rest of that window (and the window fires once per harvest). No
quantity/target choice is needed (exactly 1 veg for a fixed 2 food), so this is a
plain trigger, not a play-variant. The 2-food cost is debited and the vegetable
granted by ``_buy`` itself — the window machinery carries no cost layer — and
affordability (>= 2 food) is checked in ``_eligible`` so the buy is offered only
when the player can pay.

Mis-timing history: this card was previously registered on the
``HARVEST_CONVERSIONS`` seam (surfaced during the FEED sub-phase), which the old
docstring justified as "mechanically harmless." That home was a mis-timing — the
FEED phase is not the end of the harvest — and it has been migrated to window #16
per the printed text and the 2026-07-03 ruling. Because vegetable is never a
feeding or cooking input, the observable outcome (spend 2 food, hold +1 veg, once
per harvest) is unchanged by the move.

Registrations are global and the window's trigger enumerator checks ownership via
``_owns``, but the affordability/ownership shape still lives in ``_eligible`` (the
eligibility gate); ownership additionally short-circuits there so the buy is never
surfaced to a non-owner.

Card-only state is empty in the Family game, so it stays byte-identical and the
C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "winter_caretaker"


def _on_play(state: GameState, idx: int) -> GameState:
    """When you play this card, you immediately get 1 grain."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(grain=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the buy iff this player owns Winter Caretaker AND holds >= 2 food.

    Ownership: registrations are global, so the occupation-ownership check lives
    here (the trigger enumerator also gates on ownership, but keeping it here is
    explicit and matches the surrounding card idioms). Affordability: the window
    machinery has no cost layer, so the 2-food check that the old HARVEST_FEED
    enumerator performed must live here. The once-per-window limit is handled by
    the frame's ``triggers_resolved`` (checked by the enumerator, not here).
    """
    p = state.players[idx]
    return CARD_ID in p.occupations and p.resources.food >= 2


def _buy(state: GameState, idx: int) -> GameState:
    """Spend 2 food, gain 1 vegetable. The window trigger carries no cost layer,
    so this debits the cost and grants the good in one step."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=-2, veg=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# On-play: +1 grain.
register_occupation(CARD_ID, _on_play)

# Recurring once-per-harvest buy at the end of the harvest (window #16): an
# optional trigger — spend 2 food, get 1 vegetable.
register("end_of_harvest", CARD_ID, _eligible, _buy)
register_harvest_window_hook(CARD_ID, "end_of_harvest")
