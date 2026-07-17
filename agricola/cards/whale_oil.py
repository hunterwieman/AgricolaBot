"""Whale Oil (minor improvement, E51; Ephipparius Expansion; Food Provider).

Card text: "Each time you use "Fishing", place 1 food from the general supply on
this card. Each time before you play an occupation, you get food equal to the
amount on this card."

Cost 1 wood. No prerequisite. No printed VPs.

The card holds a growing food count in its CardStore slot (an int). Two halves:

FISHING USE — "Each time you use "Fishing", place 1 food ... on this card": a
`before_action_space` automatic effect hooking the `fishing` accumulation space.
"Each time you use [a space]" is the BEFORE-phase hook (the Geologist / Interim
Storage precedent); the food comes from the general supply onto the card, so its
timing relative to the space's own food take is irrelevant. Always +1 to the
card. `register_action_space_hook` hosts the otherwise-atomic Fishing placement
so the before-phase auto can fire.

PLAY-OCCUPATION PAYOUT — "Each time before you play an occupation, you get food
equal to the amount on this card": a MANDATORY, choice-free
`before_play_occupation` automatic effect (Bookshelf's exact template) — each
occupation play, before its cost is paid, grants food equal to the card's stored
amount. Crucially the card is NOT consumed: the stored amount stays put, so the
card is a growing multiplier (feed the Fishing space, then harvest it on every
future occupation play). Gated on the amount being > 0 (0 stored → nothing to
grant).

Because that granted food is usable for the occupation's own food cost, Whale
Oil ALSO registers an OCCUPATION_FOOD_SOURCE (again mirroring Bookshelf): the
occupation-affordability GATE (Lessons / Scholar — `_payable_occupation`) runs
BEFORE the auto lands the food, so without this an occupation payable only via
Whale Oil's stored food would be wrongly un-offered. The source reports
`(stored_amount, no inputs)` when the card holds food, else None (nothing to
offer). No double-count: the source is consulted only at the offer-gate (a
hypothetical "could I pay if the food were here"), while the auto applies the
real food at frame-push — the same two distinct evaluation points Bookshelf
documents. See bookshelf.py; FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_occupation_food_source
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "whale_oil"


def _eligible_fishing(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id == "fishing"


def _apply_fishing(state: GameState, idx: int) -> GameState:
    # Place 1 food (from the general supply) onto the card.
    p = state.players[idx]
    held = p.card_state.get(CARD_ID, 0)
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, held + 1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible_play_occupation(state: GameState, idx: int) -> bool:
    # Only worth firing when the card holds food to grant.
    return state.players[idx].card_state.get(CARD_ID, 0) > 0


def _apply_play_occupation(state: GameState, idx: int) -> GameState:
    # Gain food equal to the amount on the card; the card KEEPS its amount.
    p = state.players[idx]
    amount = p.card_state.get(CARD_ID, 0)
    p = fast_replace(p, resources=p.resources + Resources(food=amount))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _food_source(state: GameState, idx: int, cost: Resources):
    """For the occupation-affordability gate: the card's stored amount, no inputs
    consumed (the payout is free). None when the card holds nothing to offer. The
    route's `cost` is ignored — the payout is whatever the card holds."""
    amount = state.players[idx].card_state.get(CARD_ID, 0)
    if amount <= 0:
        return None
    return (amount, Resources())


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
# Host the Fishing accumulation space so the before-phase auto can fire.
register_action_space_hook(CARD_ID, frozenset({"fishing"}))
register_auto("before_action_space", CARD_ID, _eligible_fishing, _apply_fishing)
register_auto(
    "before_play_occupation", CARD_ID, _eligible_play_occupation, _apply_play_occupation
)
register_occupation_food_source(CARD_ID, _food_source)
