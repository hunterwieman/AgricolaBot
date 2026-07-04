"""Crack Weeder (minor improvement, B58; Bubulcus Expansion; players -).

Card text: "When you play this card, you immediately get 1 food. For each
vegetable you take from a field in the field phase of a harvest, you also get
1 food."

Category 2 on-play (+1 food) + a per-occasion harvest consequence.

Timing mapping (harvest-window machinery, HARVEST_WINDOWS_DESIGN.md §4d):
- **Unit counting** (ruling 6, 2026-07-03): "For each vegetable you take…" counts
  UNITS — one food per vegetable actually taken — so `_apply` sums the `veg`
  entries' `amount` in the occasion manifest, not a count of occasions.
- **Field-phase scoped** (`state.phase == Phase.HARVEST_FIELD`): "in the field
  phase of a harvest" scopes the clause to the FIELD PHASE (the window), not to
  the one crop-take action. Every vegetable taken from a field during the field
  phase counts — including one taken by a card-granted additional harvest whose
  own text places it "in the field phase" (Stable Manure). So this fires on ANY
  occasion emitted while the phase is HARVEST_FIELD (the take AND card-granted
  extras), NOT only `source == "take"`. A future Bumper Crop / Harvest Festival
  Planning take runs during WORK (it triggers the field-phase EFFECT, not the
  phase — user ruling 4), so the phase gate correctly earns nothing there. (This
  is deliberately unlike Grain Sieve, which ruling 9 scopes to the take occasion
  alone.)

Implemented as a per-occasion AUTO (`register_harvest_occasion_auto`): it fires
immediately after every emitted occasion, reading the manifest — each
`HarvestEntry` records `crop` ("grain"/"veg") and `amount` for one field
harvested. The field-phase take removes exactly 1 crop per planted field (grain
XOR veg), so a veg-sown field contributes one `veg` entry of `amount=1`. Reading
WHAT was harvested (the manifest) replaces the old pre-take grid-snapshot idiom
on the legacy `"harvest_field"` event.

See CARD_BATCH_TRIAGE.md (B58).
"""
from __future__ import annotations

from agricola.cards.harvest_windows import register_harvest_occasion_auto
from agricola.cards.specs import register_minor
from agricola.constants import Phase
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "crack_weeder"


def _on_play(state: GameState, idx: int) -> GameState:
    """Immediate +1 food when the card is played."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _veg_taken(occasion) -> int:
    """Vegetable UNITS this occasion took (ruling 6)."""
    return sum(e.amount for e in occasion.entries if e.crop == "veg")


def _eligible(state: GameState, idx: int, occasion) -> bool:
    # Any harvesting occasion during the FIELD PHASE ("in the field phase of a
    # harvest" scopes the window, not the take), that took a vegetable — so a
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


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play)
register_harvest_occasion_auto(CARD_ID, _eligible, _apply)
