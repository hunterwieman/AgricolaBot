"""Truffle Searcher (occupation, B86; Bubulcus Expansion; Farm Planner; players 1+).

Card text (verbatim): "This card can hold a number of wild boar equal to the
number of completed feeding phases."

Classification: a pure STANDING capacity card — no on-play effect. It grants a
boar-only slot count equal to the number of feeding phases the GAME has completed
so far, realized through the per-species typed-slot registry
(`register_typed_slots`, capacity_mods.py) and the greedy strip at the
ownership-aware accommodation entry points (`helpers.accommodates`,
`pareto_frontier`, `breeding_frontier`) — the same machinery as Cattle Farm and
Sheep Agent. A boar parked on a boar-only slot never constrains the other
animals, so the owner's accommodation problem equals the standard one with the
parked boar removed and added back to every answer (exact by dominance, per
type).

The count (user rulings 2026-07-21): the "number of completed feeding phases" is
the GLOBAL, game-time count — `helpers.completed_feeding_phases(state)` — NOT a
per-owner tally. Two rulings define it:
- "The feeding phase" is a phase of the GAME, not a per-player activity, so there
  is ONE count, shared by both players (the per-player feed bands are only the
  engine's sequencing of a phase that is simultaneous in the physical game).
- It ticks on game time regardless of participation: a harvest-skip card
  (Layabout) does not stall it — the count increments even if EVERY player
  skipped that harvest's feeding.
This is why `_slots` takes the count off `state` (game-global fact), not off
`player_state` — exactly the reason `register_typed_slots`' `slots_fn(state,
player_state)` signature carries both (the 2026-07-21 state widening).

Monotonicity — no eviction path (user rulings 2026-07-21): completed feeding
phases only accumulate over a game (the count is monotone non-decreasing — a
completed harvest never un-completes), so the card's slot count never DROPS, and
no situation can arise where a housed boar must be evicted because the card lost
a slot.

Timing note: the count is 0 through the round-4 WORK / FIELD / FEED phases and
first becomes 1 once round 4's feeding has resolved — i.e. at the round-4
BREEDING phase — so a newborn boar bred at the very first harvest is housable on
the card. It then grows by one per subsequent harvest (rounds 7, 9, 11, 13, 14).

Family fast path: the typed-slot registry is empty for the Family game, so
`typed_slot_counts` returns `Animals()` and every accommodation formula reduces
to its pre-card text (C++ gates untouched — card-only state).
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_typed_slots
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.helpers import completed_feeding_phases
from agricola.resources import Animals
from agricola.state import GameState, PlayerState

CARD_ID = "truffle_searcher"


def _slots(state: GameState, player_state: PlayerState) -> Animals:
    """Boar-only slots equal to the GLOBAL number of completed feeding phases
    (`helpers.completed_feeding_phases`, user rulings 2026-07-21 — one shared,
    game-time count). Reads only `state`; `player_state` is unused because the
    count is a game-global fact, not a per-owner tally."""
    return Animals(boar=completed_feeding_phases(state))


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect (passive capacity)
register_typed_slots(CARD_ID, _slots)
