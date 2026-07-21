"""Dolly's Mother (minor improvement, E84; Ephipparius Expansion; Livestock
Provider).

Card text (verbatim): "You only require 1 sheep to breed sheep during the
breeding phase of a harvest. This card can hold 1 sheep."
Cost: none (free). Prerequisite: 1 Sheep. VPs: 1 (printed).

Two independent effects, both registered as plain modifier rows
(agricola/cards/capacity_mods.py) with no engine edits:

- **Single-parent sheep breeding** (`register_single_parent_sheep`): the
  sheep parent threshold drops from 2 to 1. Consumed by
  `helpers.breeding_frontier` / `breeding_food_gained` — the threshold is a
  plain ARGUMENT there, so the memoized frontier keys on it (no cache
  staleness) — and by `resolution._execute_breed`'s food + breeding-outcome
  computation, so a from-one-sheep newborn is correctly REPORTED to the
  outcome-reactive cards (Fodder Planter's sow fires on it).

- **The sheep-only card slot** (`register_typed_slots`, 1 sheep): "this card can
  hold 1 sheep" is pure capacity — animals are not location-tracked, so the
  slot is realized by the GREEDY STRIP (user-proposed and ruled 2026-07-06):
  parking a sheep on a sheep-only slot never constrains the other animals,
  so every accommodation question for the owner equals the standard question
  with one sheep removed, the parked sheep added back to every answer. The
  strip is applied at the ownership-aware entry points
  (`helpers.accommodates`, `pareto_frontier`, `breeding_frontier`) and
  composes with Shepherd's Whistle's doctored-farm tests (the doctored
  player still owns this card). It always changes the memoized internals'
  arguments, never a hidden input — the FRONTIER_OPT cache-key rule.

The prerequisite "1 Sheep" is a HAVE-check at play time (>= 1 sheep owned).
Printed 1 VP → `vps=1` (a kept minor's ordinary printed points).

Family fast path: empty registries — `sheep_slot_count` returns 0,
`sheep_min_parents` returns 2, every formula reduces to its previous text,
and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import (
    register_single_parent_sheep,
    register_typed_slots,
)
from agricola.cards.specs import register_minor
from agricola.resources import Animals
from agricola.state import GameState

CARD_ID = "dollys_mother"


def _prereq(state: GameState, idx: int) -> bool:
    """1 Sheep — a HAVE-check, never spent."""
    return state.players[idx].animals.sheep >= 1


register_minor(CARD_ID, prereq=_prereq, vps=1)
register_typed_slots(CARD_ID, lambda p: Animals(sheep=1))
register_single_parent_sheep(CARD_ID)
