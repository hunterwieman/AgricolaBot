"""Slurry Spreader (occupation, A106; Artifex Expansion; players 1+).

Card text: "In the field phase of each harvest, each time you take the last
grain/vegetable from a field, you also get 2 food/1 food."

A per-occasion harvest consequence: automatic income keyed on fields BECOMING
EMPTY during the take.

Timing mapping (harvest-window machinery, HARVEST_WINDOWS_DESIGN.md §4d):
- **Field-phase scoped** (`state.phase == Phase.HARVEST_FIELD`): "In the field
  phase of each harvest" scopes the clause to the FIELD PHASE (the window), not to
  the one crop-take action — "each time" explicitly anticipates more than one such
  event. Any field emptied during the field phase counts, including one emptied by
  a card-granted additional harvest placed "in the field phase". So it fires on
  ANY occasion emitted while the phase is HARVEST_FIELD, NOT only
  `source == "take"`. A future WORK-phase Bumper Crop take (the field-phase EFFECT,
  not the phase — user ruling 4) earns nothing. (Unlike Grain Sieve, which ruling
  9 scopes to the take occasion alone.)
- **Per emptied entry**: "each time you take the last grain/vegetable from a field"
  keys on a field's LAST crop being taken — which the manifest records as the
  per-entry `emptied` flag (design doc §4d lists Slurry Spreader as a "per emptied
  grain/veg entry" consumer). Each emptied `grain` entry pays +2 food; each emptied
  `veg` entry pays +1 food. This manifest read replaces the old pre-take
  grid-snapshot idiom on the legacy `"harvest_field"` event, whose registration-order
  grid read was fragile: reading WHAT actually emptied is the designed, robust
  replacement (correct even when another take-modifier card reduced a field first).

Played via Lessons; its on-play is a no-op.  See CARD_BATCH_TRIAGE.md (A106).
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_occasion_auto
from agricola.cards.specs import register_occupation
from agricola.constants import Phase
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "slurry_spreader"


def _reward(occasion) -> int:
    """Food earned this occasion: +2 per emptied grain entry, +1 per emptied veg
    entry (each such entry is a field whose LAST crop was taken)."""
    food = 0
    for e in occasion.entries:
        if not e.emptied:
            continue
        if e.crop == "grain":
            food += 2 * e.amount
        elif e.crop == "veg":
            food += 1 * e.amount
    return food


def _eligible(state: GameState, idx: int, occasion) -> bool:
    # Any harvesting occasion during the FIELD PHASE that emptied a field ("in the
    # field phase of each harvest, each time…" scopes the window, not the take) —
    # so a card-granted extra harvest that empties a field counts, a WORK-phase
    # Bumper Crop take does not.
    return state.phase == Phase.HARVEST_FIELD and _reward(occasion) > 0


def _apply(state: GameState, idx: int, occasion) -> GameState:
    food = _reward(occasion)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_harvest_occasion_auto(CARD_ID, _eligible, _apply)
