"""Parvenu (occupation, deck E #145; Ephipparius Expansion; players 3+).

Card text (verbatim): "If you play this card in round 7 or before, choose clay
or reed: you immediately get a number of that building resource equal to the
number you already have in your supply."
Category: Building Resource Provider. No printed VPs.

Category 2 (on-play one-shot) with a play-time CHOICE — the Petrified Wood /
Roof Ballaster play-variant shape (`register_play_occupation_variant`), whose
`on_play` reads the chosen variant. Two independent pieces:

- **the round gate.** "If you play this card in round 7 or before" — the effect
  applies only when `round_number <= 7`. So the variants_fn returns the two real
  choices ("clay", "reed") only in rounds 1–7; in round 8+ it returns a single
  zero-surcharge no-op route ("none") so the card is still playable but does
  nothing. (`state.round_number` is the round the card is being played in.)

- **the doubling.** "you immediately get a number of that building resource
  equal to the number you already have in your supply" is a DOUBLING of the
  chosen resource: holding N clay and choosing clay grants +N clay (total 2N).
  A flat on-play gain of a building resource — no accommodation, no push. Both
  variants carry a zero SURCHARGE (the choice costs nothing); the card is always
  playable via either route.

"immediately" here is the ordinary on-play instant (the card-play moment) — the
same reading Roof Ballaster / Petrified Wood use for their on-play "immediately"
one-shots; there is no separate earlier instant to disambiguate.

Both `clay` and `reed` are always offered when round <= 7 even at a zero count
(choosing a resource you hold none of grants 0 — a legal, if pointless, choice
faithful to the printed "choose clay or reed"). Played via Lessons; card-only —
the Family game is byte-identical and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation, register_play_occupation_variant
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "parvenu"
_MAX_ROUND = 7


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """"choose clay or reed" when played in round 7 or before; otherwise a single
    zero-surcharge no-op (the card is still played, just without the gain)."""
    if state.round_number <= _MAX_ROUND:
        return [("clay", Resources()), ("reed", Resources())]
    return [("none", Resources())]


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Grant a number of the chosen resource equal to the amount already held
    (doubling). `none` (round 8+) is a no-op."""
    if variant not in ("clay", "reed"):
        return state
    p = state.players[idx]
    have = getattr(p.resources, variant)
    p = fast_replace(p, resources=p.resources + Resources(**{variant: have}))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
