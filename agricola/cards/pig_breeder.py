"""Pig Breeder (occupation, A165; Base Revised; players 4+; Livestock Provider).

Card text (verbatim): "When you play this card, you immediately get 1 wild boar.
Your wild boar breed at the end of round 12 (if there is room for the new wild
boar)."
No clarifications / errata printed.

Two effects:

- **On play** — "you immediately get 1 wild boar" is a mandatory, choice-free
  animal gain at play time. Routed through `helpers.grant_animals` (the single
  choke point for every decision-free animal gain): it adds the boar and flags
  the player, and the engine's accommodation barrier reconciles at the next
  decision boundary (1 boar fits a default farm's house-pet slot, so it just
  clears the flag; on a full farm the player is asked which to keep). The
  "immediately" here is the ordinary on-play instant (like Credit's "immediately
  get 5 food") — not a timing qualifier that names a distinct, later moment.

- **The round-12 breed** — "Your wild boar breed at the end of round 12 (if there
  is room for the new wild boar)." This is a one-off, card-driven breeding of the
  standard shape: a type with >= 2 animals produces exactly 1 newborn, but only
  if there is room to house it. The round-end ladder's `end_of_round` rung
  (ruling 49, 2026-07-12 — "the end of the round" is the ladder's last instant)
  is where "at the end of round 12" fires. It is MANDATORY and choice-free (breed
  when the conditions hold, do nothing otherwise) → an automatic effect
  (`register_auto`). Eligibility carries all three gates:
    * `round_number == 12` — the one round this fires (round 12 is not a harvest
      round, so its end goes straight through the round-end ladder);
    * `boar >= 2` — the standard breeding threshold (2 parents make 1 newborn);
    * `accommodates(p, sheep, boar + 1, cattle)` — "if there is room for the new
      wild boar": the post-breed herd must be housable. Gating in eligibility
      means the breed simply does not happen when there is no room (breeding is
      never a forced cook — an unhousable newborn is not born), and because the
      room is verified first, `grant_animals` then adds the boar into space that
      exists (the barrier clears with no keep-which prompt).

Played via Lessons; the recurring registries default empty in the Family game, so
it stays byte-identical and the C++ gates are untouched. See credit.py (on-play +
`end_of_round` auto) and acorns_basket.py / shepherds_crook.py (grant_animals).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.helpers import accommodates, grant_animals
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "pig_breeder"

_BREED_ROUND = 12


def _on_play(state: GameState, idx: int) -> GameState:
    """"When you play this card, you immediately get 1 wild boar." Routed through
    grant_animals so the accommodation barrier can reconcile an over-capacity
    farm."""
    return grant_animals(state, idx, Animals(boar=1))


def _eligible(state: GameState, idx: int) -> bool:
    """Breed at the end of round 12 iff there are >= 2 boar AND the new boar can
    be housed ("if there is room for the new wild boar")."""
    if state.round_number != _BREED_ROUND:
        return False
    a = state.players[idx].animals
    if a.boar < 2:
        return False
    return accommodates(state.players[idx], a.sheep, a.boar + 1, a.cattle)


def _apply(state: GameState, idx: int) -> GameState:
    """+1 boar (the newborn), granted at the end of round 12. Room was verified in
    `_eligible`, so this fits and the barrier clears without a keep-which prompt."""
    return grant_animals(state, idx, Animals(boar=1))


register_occupation(CARD_ID, _on_play)
register_auto("end_of_round", CARD_ID, _eligible, _apply)
