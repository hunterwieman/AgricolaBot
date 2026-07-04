"""Potato Harvester (occupation, C106; Consul Dirigens Expansion; players 1+).

Card text: "When you play this card, you immediately get 3 food. For each
vegetable you get from your fields during the field phase of the harvest, you get
1 additional food."

Category 2 on-play (+3 food) + a per-occasion harvest consequence.

Timing mapping (harvest-window machinery, HARVEST_WINDOWS_DESIGN.md §4d):
- **Unit counting** (ruling 6, 2026-07-03): "For each vegetable you get…" counts
  UNITS — one additional food per vegetable actually taken — so `_apply` sums the
  `veg` entries' `amount` in the occasion manifest.
- **Field-phase scoped** (`state.phase == Phase.HARVEST_FIELD`): "during the field
  phase of the harvest" scopes the clause to the FIELD PHASE (the window), not to
  the one crop-take action. Every vegetable gotten from a field during the field
  phase counts — including one from a card-granted additional harvest placed "in
  the field phase" (Stable Manure). So it fires on ANY occasion emitted while the
  phase is HARVEST_FIELD, NOT only `source == "take"`. A future WORK-phase Bumper
  Crop take (the field-phase EFFECT, not the phase — user ruling 4) earns nothing.
  (Unlike Grain Sieve, which ruling 9 scopes to the take occasion alone.)

Implemented as a per-occasion AUTO (`register_harvest_occasion_auto`): it fires
immediately after every emitted occasion, reading the manifest — the field-phase
take removes exactly 1 crop per planted field (grain XOR veg), so a veg-sown
field contributes one `veg` entry of `amount=1`. Reading WHAT was harvested (the
manifest) replaces the old pre-take grid-snapshot idiom on the legacy
`"harvest_field"` event.
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_occasion_auto
from agricola.cards.specs import register_occupation
from agricola.constants import Phase
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "potato_harvester"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=3))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _veg_taken(occasion) -> int:
    """Vegetable UNITS this occasion took (ruling 6)."""
    return sum(e.amount for e in occasion.entries if e.crop == "veg")


def _eligible(state: GameState, idx: int, occasion) -> bool:
    # Any harvesting occasion during the FIELD PHASE ("during the field phase of
    # the harvest" scopes the window, not the take), that got a vegetable — so a
    # card-granted extra veg harvest counts, a WORK-phase Bumper Crop take does not.
    return state.phase == Phase.HARVEST_FIELD and _veg_taken(occasion) > 0


def _apply(state: GameState, idx: int, occasion) -> GameState:
    """+1 food per vegetable UNIT the field-phase take harvested this occasion."""
    food = _veg_taken(occasion)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_harvest_occasion_auto(CARD_ID, _eligible, _apply)
