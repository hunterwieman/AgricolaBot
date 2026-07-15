"""Livestock Expert (occupation, deck E #138; Ephipparius Expansion; players 3+).

Card text (verbatim): "If you play this card in round 11 or before, choose an
animal type: you immediately get a number of animals of that type equal to the
number you already have on your farm."
Category: Goods Provider. No printed VPs.

Category 2 (on-play one-shot) with a play-time CHOICE — the animal sibling of
Parvenu (E145). Modeled as a play-variant occupation
(`register_play_occupation_variant`) whose variant-aware `on_play` DOUBLES the
chosen animal type. Two pieces:

- **the round gate.** "If you play this card in round 11 or before" — the effect
  applies only when `round_number <= 11`. So variants_fn offers the three animal
  routes ("sheep"/"boar"/"cattle") in rounds 1–11 and a single zero-surcharge
  no-op ("none") in round 12+; the card is always playable (each route is
  surcharge-free).

- **the doubling, via the accommodation barrier.** "you immediately get a number
  of animals of that type equal to the number you already have on your farm" is a
  DOUBLING: holding N of the chosen type grants +N of it (animals are not
  location-tracked, so "on your farm" is the player's animal count). The grant
  goes through `helpers.grant_animals` — never a raw `p.animals + …` — so an
  immediate grant that overflows capacity surfaces the accommodation barrier
  (the player chooses which to keep, the rest cooked to food). A zero-count type
  is a legal, pointless choice; on_play grants nothing then (no barrier flag).

"immediately" is the ordinary on-play instant (the card-play moment), the same
reading Parvenu / Roof Ballaster use. Played via Lessons; card-only registries —
the Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation, register_play_occupation_variant
from agricola.helpers import grant_animals
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "livestock_expert"
_MAX_ROUND = 11
_ANIMALS = ("sheep", "boar", "cattle")


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """The three animal routes when played in round 11 or before; otherwise a
    single zero-surcharge no-op."""
    if state.round_number <= _MAX_ROUND:
        return [(a, Resources()) for a in _ANIMALS]
    return [("none", Resources())]


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Double the chosen animal type via the accommodation-aware grant. `none`
    (round 12+) and a zero-count type are no-ops."""
    if variant not in _ANIMALS:
        return state
    have = getattr(state.players[idx].animals, variant)
    if have == 0:
        return state
    return grant_animals(state, idx, Animals(**{variant: have}))


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
