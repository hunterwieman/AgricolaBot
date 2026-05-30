"""Harvest-conversion registry.

Parallels agricola.cards.triggers — a dict of HarvestConversionSpec entries,
keyed by conversion_id. Each entry describes a once-per-harvest goods-to-food
conversion the player can opt into during HARVEST_FEED via the
CommitHarvestConversion sub-action.

Three built-in entries register at module-load time:

- "joinery"     — 1 wood -> 2 food (Joinery,            major idx 7)
- "pottery"     — 1 clay -> 2 food (Pottery,            major idx 8)
- "basketmaker" — 1 reed -> 3 food (Basketmaker's Workshop, major idx 9)

Future cards (e.g., Stone Sculptor: "1 stone -> 1 food + 1 point per harvest")
register their own entries via register_harvest_conversion(spec).

The registry is imported from agricola.cards.__init__ so the three built-in
entries register before any HARVEST_FEED resolution / enumeration reads
HARVEST_CONVERSIONS.

See ENGINE_IMPLEMENTATION.md §4.3 (Harvest sub-phases), and the
HARVEST_FEED legality enumerator / _execute_harvest_conversion effect function,
for how this registry is consumed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

from agricola.resources import Resources

if TYPE_CHECKING:
    from agricola.state import GameState


@dataclass(frozen=True)
class HarvestConversionSpec:
    """One once-per-harvest conversion entry.

    - conversion_id: unique string key, used by CommitHarvestConversion and
      stored in PlayerState.harvest_conversions_used to mark "decided".
    - input_cost: Resources spent to fire the conversion (e.g. Resources(wood=1)).
    - food_out: food produced when fired.
    - is_owned_fn: (state, player_idx) -> bool. True iff the player owns the
      source granting this conversion (major improvement, card, etc.).
    - side_effect_fn: optional non-food effect (e.g. Stone Sculptor's +1 point).
      Called by _execute_harvest_conversion AFTER the food/resource accounting.
      None for the three built-in crafts.
    """
    conversion_id: str
    input_cost:    Resources
    food_out:      int
    is_owned_fn:   Callable[["GameState", int], bool]
    side_effect_fn: Optional[Callable[["GameState", int], "GameState"]] = None


# Conversion-id-keyed registry. Mutable at import time only; treated as
# read-only after package init.
HARVEST_CONVERSIONS: dict[str, HarvestConversionSpec] = {}


def register_harvest_conversion(spec: HarvestConversionSpec) -> None:
    """Add a HarvestConversionSpec to HARVEST_CONVERSIONS, keyed by its id.

    Called at import time by the module that defines the conversion. The
    three built-in crafts register themselves at the bottom of this module;
    future card modules register their own entries from inside their module
    body, mirroring the agricola.cards.triggers.register() pattern.
    """
    HARVEST_CONVERSIONS[spec.conversion_id] = spec


# --- Built-in major-improvement crafts --------------------------------------

def _owns_major(idx: int) -> Callable[["GameState", int], bool]:
    """Return a closure: (state, player_idx) -> player owns major improvement idx."""
    def fn(state: "GameState", player_idx: int) -> bool:
        return state.board.major_improvement_owners[idx] == player_idx
    return fn


register_harvest_conversion(HarvestConversionSpec(
    conversion_id="joinery",
    input_cost=Resources(wood=1),
    food_out=2,
    is_owned_fn=_owns_major(7),
))

register_harvest_conversion(HarvestConversionSpec(
    conversion_id="pottery",
    input_cost=Resources(clay=1),
    food_out=2,
    is_owned_fn=_owns_major(8),
))

register_harvest_conversion(HarvestConversionSpec(
    conversion_id="basketmaker",
    input_cost=Resources(reed=1),
    food_out=3,
    is_owned_fn=_owns_major(9),
))
