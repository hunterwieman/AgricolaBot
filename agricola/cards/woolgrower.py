"""Woolgrower (occupation, A148; Artifex Expansion; Farm Planner; players 4+).

Card text (verbatim): "This card can hold a number of sheep equal to the number
of completed feeding phases."

Classification: a pure STANDING capacity card — no on-play effect. It grants
sheep-only slots whose count equals the number of feeding phases completed so far
in the game, realized through the per-species typed-slot registry
(`register_typed_slots`, capacity_mods.py) and the greedy strip at the
ownership-aware accommodation entry points (`helpers.accommodates`,
`helpers.pareto_frontier`, `helpers.breeding_frontier`) — the same machinery Cattle
Farm and Sheep Agent use. A sheep parked on a sheep-only slot never constrains the
other animals, so the owner's accommodation problem equals the standard one with the
parked sheep removed and added back to every answer (exact by dominance, per type).

Four-player only ([4]): NOT dealt in the 2-player game. Implemented for
forward-compat under the project's standing [3+]/[4] directive (design input, unit-
tested only), not because it is playable at 2 players.

The slot count (user rulings 2026-07-21 — the GLOBAL game-time feeding-phase count):
- The number of slots is `helpers.completed_feeding_phases(state)` — ONE shared,
  game-time count of feeding phases that have fully resolved, NOT a per-player or
  per-owner tally. It ticks when the harvest's feeding phase resolves regardless of
  any player's participation: a harvest-skip card (Layabout) exempts its owner from
  feeding but does not erase the phase, so the count still increments even if EVERY
  player skipped. (Read the full derivation in `completed_feeding_phases`' docstring.)
- Because the count is game-global, the `_slots` fn reads it off `state` (the
  2026-07-21 `register_typed_slots` signature widening added exactly for this) rather
  than off `player_state` — game-time reads come from `state`, farm/tableau reads from
  `player_state`.

Monotonicity — no eviction path: `completed_feeding_phases` is monotone non-decreasing
over a game (feeding phases only accumulate; the count never drops), so card capacity
never DROPS and no already-housed sheep can ever be forced out because the card lost a
slot.

Composition:
- It composes with the other sheep-slot cards (Dolly's Mother, Sheep Agent) by plain
  summation in `typed_slot_counts` — every owned typed-slot card's sheep component is
  added together.
- As a holder occupation it is a REGISTERED animal holder (it registers a typed slot),
  so it is automatically EXCLUDED from Sheep Agent's qualifying count via
  `animal_holder_card_ids()` — an occupation that is "already able to hold animals"
  earns no Sheep Agent slot.

Family fast path: the typed-slot registry is empty for the Family game, so
`typed_slot_counts` returns `Animals()` and every accommodation formula reduces to its
pre-card text (C++ gates untouched — card-only state). This card is never dealt outside
`GameMode.CARDS` at 4 players regardless.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_typed_slots
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.helpers import completed_feeding_phases
from agricola.resources import Animals
from agricola.state import PlayerState

CARD_ID = "woolgrower"


def _slots(state, player_state: PlayerState) -> Animals:
    """Sheep-only slots equal to the GLOBAL number of completed feeding phases
    (user rulings 2026-07-21). Read off `state` (game-time fact), not
    `player_state`."""
    return Animals(sheep=completed_feeding_phases(state))


register_occupation(CARD_ID, _noop_on_play)   # no on-play effect (passive capacity)
register_typed_slots(CARD_ID, _slots)
