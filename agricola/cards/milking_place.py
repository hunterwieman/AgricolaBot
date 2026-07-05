"""Milking Place (minor improvement, D12; Consul Dirigens Expansion).

Card text (verbatim): "In the feeding phase of each harvest, you get 1 food.
You can no longer hold animals in your house (not even via another card)."
Cost: 1 Grain. Printed VPs: 1. No prerequisite.

Two clauses:

1. **Feeding income** — `register_auto("feeding", …)`: +1 food at the FEED
   entry, before the payment decision, so it helps feed (the standard
   feeding-income moment; user go-ahead 2026-07-05).
2. **The house holds no animals, ever** — a standing rule, not an event:
   registered as a HOUSE-PET NEGATION (`register_house_pet_negation`), which
   drives `capacity_mods.house_pet_capacity` to 0 for this owner, overriding
   every capacity RAISE per the printed "not even via another card" (Animal
   Tamer's own clarification names this card as its negation). Because playing
   it can shrink a full farm's capacity mid-game (an animal currently "in the
   house" no longer fits), `_on_play` flags the accommodation barrier — the
   engine then re-checks the fit at the next decision boundary and surfaces
   the keep-or-cook choice if the animals no longer fit.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_house_pet_negation
from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "milking_place"


def _on_play(state: GameState, idx: int) -> GameState:
    """The capacity may have just SHRUNK (the house slot closes): flag the
    accommodation barrier so the engine re-checks the fit and surfaces the
    keep-or-cook choice if the player's animals no longer fit."""
    p = state.players[idx]
    if p.animals:
        p = fast_replace(p, animals_need_accommodation=True)
        state = fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))
    return state


def _apply_income(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(grain=1)), vps=1,
               on_play=_on_play)
register_auto("feeding", CARD_ID, lambda s, i: True, _apply_income)
register_harvest_window_hook(CARD_ID, "feeding")
register_house_pet_negation(CARD_ID)
