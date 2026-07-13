"""Credit (minor improvement, A54; Artifex Expansion; no cost).

Card text: "When you play this card, you immediately get 5 food. At the end of
each round that does not end with a harvest, you must pay 1 food, or else take
a begging marker."
Cost: none (free). Prerequisite: "At Most 3 Occupations" (max_occupations=3).
Printed VPs: 0. Kept (not passing). Category: Food Provider.

Two pieces:

- **the on-play grant** — "you immediately get 5 food" is a mandatory pure-goods
  gain at play time: `on_play` credits +5 food, no choice, no frame.

- **the recurring debt** — "at the end of each round" is the round-end ladder's
  `end_of_round` rung (ruling 49, 2026-07-12: the returning-home phase is the
  round's LAST phase and "the end of the round" is a DISTINCT, LATER instant —
  the ladder's last window, after the return-home reset; ruling 49 names Credit
  A54 as a member of this "at the end of each round" family). "You must pay 1
  food, or else take a begging marker" is MANDATORY and choice-free — pay 1
  food when you have it, take a begging marker when you don't — so it is an
  automatic effect (`register_auto`), never a forced FireTrigger button
  (ruling 21, 2026-07-05: a mandatory choice-free tier is an AUTO, never a
  forced offer). The ladder walk (`_process_simple_window`, window-major,
  starting player first) fires it per owner mechanically; with both players
  owning a copy, each pays their own.

- **the condition** — "that does not end with a harvest" is the bearer's OWN
  eligibility clause, not a ladder concern (ruling 49: the condition suppresses
  its bearer on harvest rounds; the ladder itself runs unconditioned on every
  round). Eligibility is `state.round_number not in HARVEST_ROUNDS`
  (rounds 4/7/9/11/13/14 end with a harvest → no payment those rounds,
  including round 14).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import HARVEST_ROUNDS
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "credit"

_GRANT = 5  # the on-play food grant


def _on_play(state: GameState, idx: int) -> GameState:
    """"When you play this card, you immediately get 5 food." """
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=_GRANT))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int) -> bool:
    """"...each round that does not end with a harvest" — the bearer's own
    condition (ruling 49): suppressed on the harvest rounds 4/7/9/11/13/14."""
    return state.round_number not in HARVEST_ROUNDS


def _apply(state: GameState, idx: int) -> GameState:
    """"You must pay 1 food, or else take a begging marker." Mandatory and
    choice-free (ruling 21, 2026-07-05): pay 1 food when food >= 1, otherwise
    take 1 begging marker."""
    p = state.players[idx]
    if p.resources.food >= 1:
        p = fast_replace(p, resources=p.resources + Resources(food=-1))
    else:
        p = fast_replace(p, begging_markers=p.begging_markers + 1)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    max_occupations=3,          # "At Most 3 Occupations" prerequisite
    on_play=_on_play,
)
register_auto("end_of_round", CARD_ID, _eligible, _apply)
