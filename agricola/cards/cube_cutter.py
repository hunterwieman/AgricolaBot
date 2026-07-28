"""Cube Cutter (occupation, C98; Corbarius Expansion; players 1+).

Card text (verbatim): "When you play this card, you immediately get 1 wood. In
the field phase of each harvest, you can use this card to exchange exactly 1
wood and 1 food for 1 bonus point."

Category: Points Provider. Two effects:

1. On play (via Lessons): immediately gain 1 wood.

2. A recurring, optional, once-per-field-phase exchange — spend exactly 1 wood
   and 1 food, produce no food, and bank 1 bonus point.

TIMING — the field phase (harvest window #5). Earlier this card rode the
`HARVEST_CONVERSIONS` seam, which surfaces in the FEEDING phase, not the field
phase. That was a mis-timing (mis-timed card #1 in CARD_DEFERRED_PLANS.md): at
FEED the owner could first cook wood→food via a craft/Joinery conversion and pay
the exchange's food from that, whereas the printed field-phase timing requires
the food already on hand before any feeding conversions run. Per the
harvest-window redesign (HARVEST_WINDOWS_DESIGN.md §4 class (a); user-agreed
design 2026-07-03), Cube Cutter is a **free-ordered independent optional trigger
on the "field_phase" during-window**, legal at any point in the window (before or
after the mandatory crop take, in any player-chosen order). The frame's
`triggers_resolved` gives the once-per-field-phase cap the printed "In the field
phase of each harvest, you can use this card…" describes. The exchange touches no
crops and emits no HarvestOccasion, so it is a plain state edit, not an
additional harvest.

The point cannot be granted immediately (there is no immediate-VP mechanism), so
each fire increments a per-card CardStore counter (banked across all six
harvests), and the scoring term reads the count back at end-game.

THE PRICE (corrected per ruling 82, 2026-07-27) — 1 wood + 1 food. The wood must
be on hand outright (liquidation only ever produces food), but the food is
payable by ANY legal route — on hand OR raised by the at-any-time conversions
(ruling 82: "An implementation must never make a rules-legal move unplayable.
The canonical violation: a 'pay N food' cost gated on food-on-hand"). The
eligibility is therefore `_liquidatable_to(wood=1, food=1)` — which enforces the
wood-on-hand part itself, and in-span delegates to the same frontier the raise
frame enumerates (span converters and post-breed floors included, so the gate
and the frame agree by construction). With the food on hand `_apply` exchanges
directly; when short it pushes a raise-only `PendingFoodPayment` whose
registered resume (`_exchange`) debits the full 1 wood + 1 food and banks the
point. The exchange's own wood is RESERVED from the raise
(`reserved=Cost(resources=Resources(wood=1))`): an in-span wood-eating
converter (the Joinery's span exchange) could otherwise cook the very wood
this card is about to spend. Owning the occupation is sufficient — there is NO
Joinery/major gate (unlike Furniture Carpenter). The once-per-field-phase cap
is untouched: the fire is recorded on the PendingFieldPhase frame's
`triggers_resolved` before the raise frame resolves.

Card-only state (the CardStore int) is empty in the Family game, so the engine
stays byte-identical and the C++ gates are untouched. See
CARD_AUTHORING_GUIDE.md and harvest_windows.py.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import (
    register_food_payment_resume,
    register_occupation,
)
from agricola.cards.triggers import register
from agricola.legality import _liquidatable_to
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "cube_cutter"

WINDOW = "field_phase"


def _on_play(state: GameState, idx: int) -> GameState:
    """On play: immediately gain 1 wood."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved: frozenset) -> bool:
    """Offer the exchange iff the owner can afford exactly 1 wood + 1 food —
    the wood on hand, the food by any legal route: on hand or raised by the
    at-any-time conversions (ruling 82, corrected 2026-07-27; a plain
    food-on-hand gate makes rules-legal moves unplayable). `_liquidatable_to`
    enforces the wood-on-hand part itself, and in-span it delegates to the
    same frontier the raise frame enumerates.

    Owning the occupation is sufficient (no major/Joinery gate). The
    once-per-field-phase cap is enforced by the PendingFieldPhase frame's
    `triggers_resolved` (this fn is only consulted for unfired triggers), so it
    is not re-checked here.
    """
    return _liquidatable_to(state, idx, state.players[idx],
                            Resources(wood=1, food=1))


def _exchange(state: GameState, idx: int) -> GameState:
    """Spend 1 wood + 1 food, produce no food, bank +1 point. Reached directly
    (food on hand) and as the post-food-payment resume (the raise-only frame
    leaves the raised food in supply for this to debit)."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p,
        resources=p.resources - Resources(wood=1, food=1),
        card_state=p.card_state.set(CARD_ID, banked + 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _apply(state: GameState, idx: int) -> GameState:
    """Fire the exchange. With the food on hand, exchange directly; otherwise
    push the raise-only PendingFoodPayment (ruling 82's corrected payment
    shape) with the exchange's own 1 wood RESERVED — an in-span wood-eating
    converter must not cook the wood the resumed exchange still needs."""
    if state.players[idx].resources.food >= 1:
        return _exchange(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=1, resume_kind=CARD_ID,
        reserved=Cost(resources=Resources(wood=1)),
    ))


def _score(state: GameState, idx: int) -> int:
    """Sum of bonus points banked across all harvests."""
    return state.players[idx].card_state.get(CARD_ID, 0)


# Played via Lessons; on-play grants 1 wood.
register_occupation(CARD_ID, _on_play)

# The recurring goods->VP exchange, in the field-phase during-window: an optional,
# free-ordered, once-per-field-phase trigger (spend 1 wood + 1 food, bank +1 point).
register(WINDOW, CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, WINDOW)
# The raise-only food frame's continuation (ruling 82's corrected payment shape).
register_food_payment_resume(CARD_ID, _exchange)

register_scoring(CARD_ID, _score)
