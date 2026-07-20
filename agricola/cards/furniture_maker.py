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
   `paid_cost.food`. Since ruling 67 (2026-07-20) the executor stamps
   `PendingPlayOccupation.paid_cost` with the resource vector it actually
   debited for the OCCUPATION COST PROPER (the chosen payment from the
   play_occupation cost-conversion frontier, or the route cost on the plain
   path); the host is on top when the after-autos fire, so the read is direct
   ground truth. DELIBERATE SCOPING: a play-variant SURCHARGE (Roof Ballaster's
   optional 1-food payment) is an effect price, NOT "occupation cost" —
   RULES.md: an individual printed cost "is paid in addition to the occupation
   cost" — and it is correctly excluded because the executor stamps only the
   base-cost payment, never the surcharge. Food raised through the shared
   food-payment path (liquidation) is genuinely paid — the debit is still in
   food — so it counts.

FOREST SCHOOL / WORKING GLOVES — RULED (user, 2026-07-15): wood-substituted
food does NOT count as "food paid as occupation cost". Both substitution cards
are play_occupation cost CONVERSIONS (ruling 67), so a substituted play's
`paid_cost` simply carries wood/resources instead of food and the count is
structural — including a PARTIAL substitution (ruling 65's mixed payments,
e.g. 1 wood + 1 food on Writing Desk's 2-food granted play pays out exactly 1
wood here). The old all-or-nothing `triggers_resolved` guard is gone with the
trigger it read.

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
    """Food ACTUALLY paid in food toward the occupation cost. Since ruling 67
    (2026-07-20) the play host carries a `paid_cost` stamp — the resource vector
    the executor really debited for the occupation cost proper (a substitution
    card's converted payment included, the play-variant surcharge excluded) — so
    the read is ground truth: a Forest School / Working Gloves substitution pays
    wood/resources, not food (user ruling 2026-07-15), and a PARTIAL substitution
    (ruling 65's mixed payments) counts its remaining food exactly. Falls back to
    the frame's charged `cost` when no stamp is present (a hand-built frame)."""
    paid = getattr(top, "paid_cost", None)
    if paid is not None:
        return paid.food
    cost = getattr(top, "cost", None)
    return cost.food if cost is not None else 0


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
