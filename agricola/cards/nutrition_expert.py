"""Nutrition Expert (occupation, deck B #135; Bubulcus Expansion; players 3+).

Card text (verbatim): "At the start of each round, you can exchange a set
comprised of 1 animal of any type, 1 grain, and 1 vegetable for 5 food and 2
bonus points."
Category: Points Provider. No printed VPs.

A start-of-round play-variant trigger — the Acquirer / Scholar shape (an OPTIONAL
`start_of_round` trigger surfaced WIDE as one FireTrigger per route via
`register_play_variant_trigger`), with the route being WHICH animal type the set
gives up. Pieces:

- **Timing.** "At the start of each round" -> the preparation ladder's
  `start_of_round` window. Once per round comes from the window frame's
  `triggers_resolved` ("exchange a set" — one set), exactly as for Acquirer.

- **Optional.** "you can" -> declined by the window host's Proceed (no route fired).

- **The set.** "1 animal of any type, 1 grain, and 1 vegetable" — the exchange
  needs all three, so it is offered only when the player holds >= 1 grain, >= 1
  vegetable, and >= 1 of some animal; the chosen animal TYPE is the variant (one
  route per type held). Firing debits 1 of that animal + 1 grain + 1 vegetable.
  (Giving up an animal only lowers the count — no accommodation.)

- **The reward.** "5 food and 2 bonus points": +5 food immediately, and the 2
  bonus points are BANKED in the card's CardStore (accumulating across every
  exchange) and read back by a `register_scoring` term at end-game (the Big
  Country banked-points idiom — bonus points are a play-time quantity, not a
  derivable end-state read).

Played via Lessons; card-only registries + the default-empty CardStore — the
Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "nutrition_expert"
_ANIMALS = ("sheep", "boar", "cattle")
_POINTS_PER_EXCHANGE = 2


def _legal_variants(state: GameState, idx: int) -> list[str]:
    """One route per animal type held, but only when the player also holds the
    grain + vegetable the set requires; else nothing to exchange this round."""
    p = state.players[idx]
    if p.resources.grain < 1 or p.resources.veg < 1:
        return []
    return [a for a in _ANIMALS if getattr(p.animals, a) >= 1]


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return bool(_legal_variants(state, idx))


def _apply(state: GameState, idx: int, variant: str) -> GameState:
    """Debit the set (1 of `variant`, 1 grain, 1 veg), gain 5 food, and bank 2
    bonus points for end-game scoring."""
    p = state.players[idx]
    banked = p.card_state.get(CARD_ID, 0) + _POINTS_PER_EXCHANGE
    p = fast_replace(
        p,
        resources=p.resources - Resources(grain=1, veg=1) + Resources(food=5),
        animals=p.animals - Animals(**{variant: 1}),
        card_state=p.card_state.set(CARD_ID, banked),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _score(state: GameState, idx: int) -> int:
    """The banked bonus points (2 per exchange performed)."""
    return state.players[idx].card_state.get(CARD_ID, 0)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("start_of_round", CARD_ID, _eligible, _apply)
register_play_variant_trigger(CARD_ID, _legal_variants)
register_scoring(CARD_ID, _score)
