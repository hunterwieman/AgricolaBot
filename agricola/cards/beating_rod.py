"""Beating Rod (minor improvement, B9; Bubulcus Expansion; Goods Provider).

Card text (verbatim): "You can immediately choose to either get 1 reed or
exchange 1 reed for 1 cattle."
No cost, no prerequisite, no printed VPs. TRAVELING (passing) minor — B9 is a
number-001-009 card (`passing_left='X'` in the catalog): after its on-play effect
it moves to the OPPONENT's hand rather than staying in the player's tableau.

An on-play choice between two EFFECTS (not two costs): (a) get 1 reed, or (b) pay
1 reed to get 1 cattle. Per the user (2026-07-13) the player must take ONE of the
two (no do-nothing), and the choice is surfaced WIDE — one play option per route
at the improvement-space selection ("Beating Rod: get reed" / "Beating Rod:
exchange for cattle") — via `register_play_minor_variant` (the Facades Carving
pattern). The reed spent on route (b) is an effect-level exchange PRICE, so it
rides as the variant SURCHARGE (correctly NOT reducible by a cost-modifier card,
unlike a genuine alternative cost).

- Route "reed": zero surcharge, benefit +1 reed. Always present (so the card is
  always playable) — the required zero-surcharge route.
- Route "cattle": surcharge 1 reed (offered only when the player holds >= 1 reed
  — you cannot exchange a reed you don't have), benefit 1 cattle granted via
  `helpers.grant_animals` so the accommodation barrier handles overflow (the
  `early_cattle` / `game_trade` immediate-grant pattern).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.helpers import grant_animals
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "beating_rod"


def _variants(state: GameState, idx: int) -> list:
    """Both routes; the cattle exchange is offered only when a reed is on hand to
    give up (its 1-reed surcharge would also be affordability-filtered by the
    enumerator — reed cannot be liquidated — but the explicit gate states intent)."""
    routes = [("reed", Resources())]
    if state.players[idx].resources.reed >= 1:
        routes.append(("cattle", Resources(reed=1)))
    return routes


def _on_play(state: GameState, idx: int, variant: str) -> GameState:
    if variant == "cattle":
        # The 1-reed surcharge was already debited (folded into payment); grant
        # the cattle through the accommodation choke point.
        return grant_animals(state, idx, Animals(cattle=1))
    # "reed": get 1 reed.
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(reed=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, passing_left=True, on_play=_on_play)
register_play_minor_variant(CARD_ID, _variants)
