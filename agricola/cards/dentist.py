"""Dentist (occupation, E110; Ephipparius Expansion; players 1+).

Card text (verbatim): "At the start of each harvest, you can place 1 wood from
your supply on this card, irretrievably. In each feeding phase, you get 1 food
for each wood on this card."

No prerequisite. Printed VPs: 0. Category: Food Provider.

Two effects, on two different harvest windows — a card may register in both, and
the harvest-window hook docstring cites Dentist as the precedent for this:

1. **The bank** — "At the start of each harvest, you can place 1 wood from your
   supply on this card, irretrievably." The word "can" makes this an OPTIONAL,
   declinable action, so it is a window TRIGGER (`register`, not `register_auto`)
   on window #2 ``start_of_harvest`` — the window that opens the whole harvest,
   before the field phase. It surfaces as a ``FireTrigger`` on a per-player
   ``PendingHarvestWindow`` frame; ``Proceed`` declines. "1 wood" (singular) is
   exactly one placement per harvest, which the once-per-window frame gives for
   free (its ``triggers_resolved`` records the fire, and the window fires once per
   harvest), so no quantity choice is needed — a plain trigger, not a play-variant.

   "irretrievably" = the wood leaves the player's supply permanently. It is
   modeled as: debit 1 wood from ``resources.wood`` and increment a wood-on-card
   counter in the per-card ``CardStore`` (II.7). The counter accumulates across
   harvests (one more wood may be banked each harvest). Because the wood is
   removed from supply and never returned, it cannot be spent, fed, or counted by
   any supply-reading effect — which is what "irretrievably" requires. Eligibility
   gates on holding at least 1 wood in supply, so the bank is offered only when
   the player can actually place a wood.

2. **The payout** — "In each feeding phase, you get 1 food for each wood on this
   card." Choice-free INCOME → an automatic effect (`register_auto`) on the
   ``"feeding"`` window (the FEED entry). The feeding-income seam fires this per
   player, starting player first, BEFORE the payment decision, so the food is
   payable (HARVEST_WINDOWS_DESIGN.md §5; the ``register_harvest_window_hook``
   docstring). The amount is the wood-on-card counter, so a Dentist that has
   banked N wood pays N food each feeding phase. It is eligible whenever at least
   1 wood has been banked; with 0 wood banked the payout is nothing (no-op).

Card-only state (the wood-on-card counter) is empty until a real Cards game plays
Dentist, so the Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "dentist"


def _wood_on_card(state: GameState, idx: int) -> int:
    """How many wood this player has banked on their Dentist (0 by default)."""
    return state.players[idx].card_state.get(CARD_ID, 0)


# --- 1. The bank (start_of_harvest optional trigger) -----------------------

def _bank_eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    """Offer the wood-placement iff the player owns Dentist AND holds >= 1 wood
    in supply. The once-per-harvest limit is the frame's ``triggers_resolved``
    (checked by the enumerator), so it is not re-checked here."""
    p = state.players[idx]
    return CARD_ID in p.occupations and p.resources.wood >= 1


def _bank(state: GameState, idx: int) -> GameState:
    """Place 1 wood from supply onto the card, irretrievably: debit 1 wood and
    increment the wood-on-card counter (the wood leaves the supply and is never
    returned)."""
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(wood=1),
        card_state=p.card_state.set(CARD_ID, _wood_on_card(state, idx) + 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# --- 2. The payout (feeding auto: 1 food per wood on the card) -------------

def _payout_eligible(state: GameState, idx: int) -> bool:
    return _wood_on_card(state, idx) >= 1


def _payout(state: GameState, idx: int) -> GameState:
    """+1 food per wood banked on the card, at the FEED entry (before payment)."""
    food = _wood_on_card(state, idx)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect

# The bank: optional wood-placement at the start of each harvest (window #2).
register("start_of_harvest", CARD_ID, _bank_eligible, _bank)
register_harvest_window_hook(CARD_ID, "start_of_harvest")

# The payout: 1 food per wood on the card, in each feeding phase (FEED entry).
register_auto("feeding", CARD_ID, _payout_eligible, _payout)
register_harvest_window_hook(CARD_ID, "feeding")
