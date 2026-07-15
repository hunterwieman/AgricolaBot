"""Roman Pot (minor improvement, E56; Ephipparius Expansion; Food Provider).

Card text: "Place 4 food from the general supply on this card. At the start of
each work phase, if you are the last player in turn order, move 1 food from this
card to your supply."

Cost 1 clay. No prerequisite. Worth 1 VP.

The card holds a draining food reserve in its CardStore slot (an int). Two parts:

ON PLAY — "Place 4 food ... on this card": `on_play` seeds the CardStore to 4.

START-OF-WORK DRIP — "At the start of each work phase, if you are the last player
in turn order, move 1 food from this card to your supply": a MANDATORY,
choice-free income (`register_auto`) on the preparation ladder's `start_of_work`
window (ruling 54, 2026-07-14 — the ladder's last rung, "at the start of each
work phase"; the Trout Pool / Freemason precedent). Fired mechanically per
player, it is gated on two conditions, both re-checked each round:

  * the owner is the LAST player in turn order, and
  * the card still holds at least 1 food.

"Last player in turn order" is expressed generally (for any player count) as
`(idx - starting_player) % n == n - 1` — the player `n-1` seats after the
starting player. In the 2-player game that is the non-starting player. The
starting player is read live from `state.starting_player` (it can change during a
game via Meeting Place), so the drip follows whoever is currently last. Once the
card empties, the food-count gate disarms it. See trout_pool.py / freemason.py.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "roman_pot"


def _on_play(state: GameState, idx: int) -> GameState:
    """Place 4 food on the card (seed the CardStore food count to 4)."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, 4))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _is_last_in_turn_order(state: GameState, idx: int) -> bool:
    n = len(state.players)
    return (idx - state.starting_player) % n == n - 1


def _eligible(state: GameState, idx: int) -> bool:
    return (
        _is_last_in_turn_order(state, idx)
        and state.players[idx].card_state.get(CARD_ID, 0) > 0
    )


def _apply(state: GameState, idx: int) -> GameState:
    # Move 1 food from the card to the player's supply.
    p = state.players[idx]
    held = p.card_state.get(CARD_ID, 0)
    p = fast_replace(
        p,
        resources=p.resources + Resources(food=1),
        card_state=p.card_state.set(CARD_ID, held - 1),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=1)), vps=1, on_play=_on_play)
register_auto("start_of_work", CARD_ID, _eligible, _apply)
