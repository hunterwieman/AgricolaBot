"""Furniture Maker (occupation, deck C #116; Corbarius Expansion; players 1+).

Card text: "When you play this card, you immediately get 1 wood. Each time you
play an occupation after this one, you get 1 wood for each food paid as
occupation cost."

CLASSIFICATION (settled, 2026-07-15): on_play grants 1 wood; the recurring
clause is a mandatory, choice-free `register_auto("after_play_occupation", ...)`
— own plays only (the registries' default own-action routing + ownership gate).
Two design decisions, recorded per the spec:

1. "AFTER THIS ONE" — its own play is excluded via the play host's
   `played_card_id` stamp (the Clutterer/Bonehead idiom): eligibility requires
   `state.pending_stack[-1].played_card_id != "furniture_maker"`. Without the
   guard, playing Furniture Maker itself as a food-costing occupation (e.g. the
   second Lessons play) would pay wood at its own deferred after-flip — the card
   is already in the tableau by then.

2. "1 WOOD FOR EACH FOOD PAID AS OCCUPATION COST" — read the play host frame's
   `cost.food`. `PendingPlayOccupation.cost` is the route-supplied occupation
   cost (Lessons' ramp — free first, 1 food after; Scholar's flat 1 food), set
   at push time; the host is on top when the after-autos fire, so the read is
   direct. DELIBERATE SCOPING: a play-variant SURCHARGE (Roof Ballaster's
   optional 1-food payment) is an effect price, NOT "occupation cost" —
   RULES.md: an individual printed cost "is paid in addition to the occupation
   cost" — and it is correctly excluded here because the frame's `cost` field
   never includes surcharges (`_execute_play_occupation` folds the variant
   surcharge into a LOCAL cost for the debit and never writes it back to the
   frame). Food raised through the shared food-payment path (liquidation) is
   genuinely paid — the frame's cost is still debited in food — so it counts.

FOREST SCHOOL — RULED (user, 2026-07-15): wood-substituted food does NOT count
as "food paid as occupation cost". Forest School ("You can replace each food
that an occupation costs with wood") is an optional `before_play_occupation`
trigger that converts wood -> food to pay the cost; when it fires, the player
paid WOOD, not food, so Furniture Maker grants nothing for that play. The guard
needs no engine change: Forest School's fire is recorded in the host frame's
`triggers_resolved`, which survives the after-flip, so eligibility/apply
subtract the substituted food. Forest School substitutes the WHOLE printed food
cost in one fire (it is not partial), so "fired -> 0 food actually paid in
food" is exact for today's catalog; a future PARTIAL food-substitution card
would need the substituted amount tracked rather than this all-or-nothing
check.

Opponent plays never fire (own-action routing; ownership additionally requires
Furniture Maker in the acting player's tableau — a copy still in HAND is
inert). Eligibility also requires `cost.food >= 1`: a free play (the first
Lessons occupation) pays no food and grants nothing.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "furniture_maker"


def _update_player(state: GameState, idx: int, p) -> GameState:
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _on_play(state: GameState, idx: int) -> GameState:
    """"When you play this card, you immediately get 1 wood." """
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return _update_player(state, idx, p)


def _food_paid_in_food(top) -> int:
    """Food ACTUALLY paid in food toward the occupation cost. The frame's
    `cost.food` is the charged food, MINUS any wood-substituted by Forest School
    (user ruling 2026-07-15 — substituted food is paid in wood, not food).
    Forest School substitutes the whole printed food cost when it fires, and its
    fire is stamped in the host's `triggers_resolved` (surviving the after-flip),
    so a fired Forest School zeroes the count exactly for today's catalog."""
    cost = getattr(top, "cost", None)
    if cost is None:
        return 0
    if "forest_school" in getattr(top, "triggers_resolved", frozenset()):
        return 0
    return cost.food


def _eligible(state: GameState, idx: int) -> bool:
    """The just-played occupation is not Furniture Maker itself ("after this
    one" — design decision 1) and at least 1 food was actually paid in food
    (nothing to pay out on a free play, or on a Forest-School-substituted play
    where the cost was paid in wood)."""
    if not state.pending_stack:
        return False
    top = state.pending_stack[-1]
    if getattr(top, "played_card_id", None) == CARD_ID:
        return False
    return _food_paid_in_food(top) >= 1


def _apply(state: GameState, idx: int) -> GameState:
    """1 wood per food actually paid in food (design decision 2: the frame's
    `cost.food`, less any Forest-School wood-substitution; surcharges are never
    on the frame, so never counted)."""
    food_paid = _food_paid_in_food(state.pending_stack[-1])
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=food_paid))
    return _update_player(state, idx, p)


register_occupation(CARD_ID, _on_play)
register_auto("after_play_occupation", CARD_ID, _eligible, _apply)
