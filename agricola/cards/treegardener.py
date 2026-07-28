"""Treegardener (occupation, A118; Artifex Expansion; players 1+).

Card text (verbatim): "In the field phase of each harvest, you get 1 wood and
you can buy up to 2 additional wood for 1 food each."

Clarification (verbatim): "《You may use this card to activate the Shaving Horse
A048 twice if and only if you have another decision during the field phase to
separate this card's effect into two distinct parts, e.g. paying wood and food
with Cube Cutter C098.》"

Category: Building Resource Provider. Occupation — no structured cost /
prerequisite / VPs (occupations carry none in the card data). Not passing.

TWO CLAUSES, both in the field phase (harvest window #5, "field_phase"; the
during-window). They are two distinct firing kinds:

1. **"you get 1 wood"** — a MANDATORY, choice-free income → an automatic effect
   (`register_auto("field_phase", …)`). Fired by `engine._field_phase_step` via
   `apply_auto_effects` before the mechanical crop take, once per owner per
   harvest. It only credits wood; it touches no crops, so it does not alter what
   the take then harvests.

2. **"you can buy up to 2 additional wood for 1 food each"** — an OPTIONAL choice
   → a free-ordered `"field_phase"` trigger on the `PendingFieldPhase` host
   (the Cube Cutter class — HARVEST_WINDOWS_DESIGN.md §4a; legal at any point in
   the window, before or after the mandatory `CommitFieldTake`, in any
   player-chosen order). "up to 2" is ONE buying decision (buy 1 wood for 1
   food, OR buy 2 wood for 2 food), NOT two separate uses — so it is modeled as a
   play-variant trigger (`register_play_variant_trigger`, mirroring
   `home_brewer.py`) with variants "1" and "2" (the wood quantity bought / food
   spent). Buying zero is expressed by declining the trigger (`Proceed`). The
   `PendingFieldPhase` frame's `triggers_resolved` gives the once-per-field-phase
   cap the printed "In the field phase of each harvest" describes: firing the
   trigger (at either quantity) marks it resolved, so it cannot fire again this
   window.

   Payment (ruling 82, 2026-07-26; this card shipped with a plain food-on-hand
   gate and was corrected 2026-07-27): each quantity's price (1 food per wood)
   is payable by ANY legal route — food on hand OR raised by the at-any-time
   crop/animal conversions — so a quantity is offered iff ITS OWN price is
   raise-able (`_liquidatable_to`; the window sits INSIDE the harvest conversion
   span, where the gate delegates to the same frontier the raise frame
   enumerates). The grain the take just delivered is itself legal fuel — the
   engine's post-take re-check (`_field_phase_step`) hosts the frame even when
   the buy only became payable through the take's income. Firing buys directly
   when the food is on hand; short of it, the fire pushes the raise-only
   `PendingFoodPayment` (resume kind `"treegardener:<qty>"` — static variants
   ride the resume kind, the Canal Boatman shape), and the resume debits the
   food and grants the wood.

The Shaving Horse (A048) clarification is MOOT here: Shaving Horse is BANNED —
never implemented (marked 🚫 BANNED in CARD_IMPLEMENTATION_PROGRESS.md's A48
entry) — so there is no card in the pool whose wood-obtained activation this
could double, and nothing is built for that interaction.

Both effects read/modify only the owner's own resources (no crops, no
HarvestOccasion), so each is a plain state edit. The card is empty in the Family
game (no player owns it), so the engine stays byte-identical and the C++ gates
are untouched. See CARD_AUTHORING_GUIDE.md and harvest_windows.py.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import (
    register_food_payment_resume,
    register_occupation,
)
from agricola.cards.triggers import register, register_auto, register_play_variant_trigger
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "treegardener"

WINDOW = "field_phase"

_MAX_BUY = 2   # "up to 2 additional wood"


def _credit_wood(state: GameState, idx: int, wood: int) -> GameState:
    """Grant `wood` wood to player `idx` (touching no other state)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=wood))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


# --- Clause 1: the mandatory +1 wood (a field-phase auto) --------------------

def _auto_eligible(state: GameState, idx: int) -> bool:
    """Always fires: the +1 wood is unconditional (no cost, no threshold)."""
    return True


def _auto_apply(state: GameState, idx: int) -> GameState:
    """+1 wood in the field phase, before the crop take (a plain resource credit)."""
    return _credit_wood(state, idx, 1)


# --- Clause 2: the optional "buy up to 2 wood for 1 food each" trigger --------

def _buy_eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the buy iff at least the smallest quantity's price — 1 food — is
    raise-able (ruling 82: on hand or by the at-any-time conversions).
    Ownership and the once-per-field-phase cap are enforced by the host
    enumerator / the frame's `triggers_resolved`."""
    return bool(_buy_variants(state, idx))


def _buy_variants(state: GameState, idx: int) -> list[str]:
    """The buy quantities whose OWN price is raise-able (ruling 82): "1"
    (1 food -> 1 wood) and "2" (2 food -> 2 wood), each costing 1 food per wood
    up to the printed cap of 2 additional wood."""
    p = state.players[idx]
    return [str(q) for q in range(1, _MAX_BUY + 1)
            if _liquidatable_to(state, idx, p, Resources(food=q))]


def _buy(state: GameState, idx: int, qty: int) -> GameState:
    """Buy `qty` additional wood, paying 1 food per wood bought. Reached
    directly (food on hand) and as the post-food-payment resume (the raise-only
    frame leaves the raised food in supply to debit)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=qty, food=-qty))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _buy_apply(state: GameState, idx: int, variant: str) -> GameState:
    """Fire one buy. With the food on hand, buy directly; otherwise push the
    raise-only PendingFoodPayment — the quantity is STATIC, so it rides the
    resume_kind itself ("treegardener:<qty>", one registered resume per
    quantity), and the buy reserves nothing (its only cost is the food)."""
    qty = int(variant)
    assert 1 <= qty <= _MAX_BUY, f"unknown treegardener buy quantity {variant!r}"
    if state.players[idx].resources.food >= qty:
        return _buy(state, idx, qty)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=qty,
        resume_kind=f"{CARD_ID}:{qty}", reserved=Cost(),
    ))


# Played via Lessons; no on-play effect (both clauses are recurring field-phase
# effects, so on-play is a no-op).
register_occupation(CARD_ID, lambda state, idx: state)

# Clause 1: the mandatory +1 wood, fired pre-take by the field-phase walk.
register_auto(WINDOW, CARD_ID, _auto_eligible, _auto_apply)

# Clause 2: the optional buy — a free-ordered, once-per-field-phase play-variant
# trigger on the "field_phase" during-window (buy 1 or 2 wood, 1 food each).
register(WINDOW, CARD_ID, _buy_eligible, _buy_apply)
register_play_variant_trigger(CARD_ID, _buy_variants)

# One hook registration covers both the auto and the trigger on this window.
register_harvest_window_hook(CARD_ID, WINDOW)
# One resume per (static) quantity: the raise-only food frame's resume_kind
# carries the chosen quantity (ruling 82's payment shape).
for _q in range(1, _MAX_BUY + 1):
    register_food_payment_resume(
        f"{CARD_ID}:{_q}", (lambda q: lambda state, idx: _buy(state, idx, q))(_q))
