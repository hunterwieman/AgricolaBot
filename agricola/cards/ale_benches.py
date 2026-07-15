"""Ale-Benches (minor improvement, A29; Artifex Expansion; Points Provider).

Card text (verbatim): "In the returning home phase of each round, you can pay
exactly 1 grain from your supply to get 1 bonus point. If you do, each other
player gets 1 food."
Cost: 1 Wood. Prerequisite: "2 Occupations". No printed VPs (the points are
earned in play, banked below).

TIMING — "in the returning home phase of each round" is the round-end ladder's
``returning_home`` window (user ruling 49, 2026-07-12: "in the returning home
phase" is a distinct rung of the round-end ladder;
``agricola/cards/round_end.py``). Unlike Silage's "after which there is no
harvest", Ale-Benches names NO harvest condition — the returning home phase
happens every round (it precedes the harvest on harvest rounds) — so the
effect is offered on ALL rounds, harvest rounds included. That rung fires
PRE-reset; Ale-Benches reads no board occupancy, so the timing is harmless.

THE CHOICE — an optional TRIGGER ("you can pay"): a single
``FireTrigger(card_id)`` on the window's frame, eligible only when the owner
holds >= 1 grain in SUPPLY ("from your supply" — a field's grain does not
qualify). Firing:

- banks 1 bonus point in the per-card ``CardStore`` (the Big Country
  banked-points idiom): a point earned mid-game but scored at end-game, so
  ``_apply`` increments the counter and ``register_scoring`` reads it back. The
  bank accumulates across every round the owner pays;
- debits the 1 grain from supply;
- gives EACH other player 1 food ("if you do, each other player gets 1 food" —
  the food is a consequence of paying, so it is applied in the same fire). The
  loop over the non-owner seats is written player-count-generically (2-player
  today: the single opponent).

ONCE PER ROUND comes free from the window frame's ``triggers_resolved`` (one
``returning_home`` window per round, a fresh frame each round); DECLINING is
the frame's ``Proceed`` (no SkipTrigger, the standard optional-trigger shape).

Prerequisite "2 Occupations" → ``min_occupations=2``.

Card-game only (ownership-gated registries; the banked points live in the
card-only ``CardStore``): the Family game is byte-identical and the C++ gates
are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "ale_benches"


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """Offer the pay-for-a-point iff the owner holds >= 1 grain IN SUPPLY
    ("from your supply" — a field's grain is not a source here). Ownership is
    the window machinery's gate; once-per-round is the frame's
    ``triggers_resolved``."""
    return state.players[idx].resources.grain >= 1


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 grain from supply → bank 1 bonus point (CardStore counter, scored
    at end-game) → each other player gets 1 food."""
    players = list(state.players)
    p = players[idx]
    banked = p.card_state.get(CARD_ID, 0) + 1
    players[idx] = fast_replace(
        p,
        resources=p.resources - Resources(grain=1),
        card_state=p.card_state.set(CARD_ID, banked),
    )
    for j in range(len(players)):
        if j != idx:
            players[j] = fast_replace(
                players[j], resources=players[j].resources + Resources(food=1))
    return fast_replace(state, players=tuple(players))


def _score(state: GameState, idx: int) -> int:
    """The banked bonus points (1 per round the owner paid a grain)."""
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), min_occupations=2)

# The optional once-per-round pay-a-grain-for-a-point on the round-end ladder's
# returning_home window (ruling 49); the bonus point is banked for scoring.
register("returning_home", CARD_ID, _eligible, _apply)
register_scoring(CARD_ID, _score)
