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
    - side_effect_fn: optional non-food effect (e.g. Beer Keg's point).
      Called by _execute_harvest_conversion AFTER the food/resource accounting.
      None for the three built-in crafts. With variants_fn set, its signature
      gains the chosen variant: (state, player_idx, variant) -> GameState.
    - variants_fn: optional (state, player_idx) -> list[str] — a conversion
      whose use needs a CHOICE beyond firing it (Craft Brewery's which-grain-
      field, encoded by field height per the user's 2026-07-06 ruling) is
      offered WIDE: one CommitHarvestConversion(conversion_id, variant) per
      currently-legal variant, still once per harvest total. An empty list =
      no legal use right now (the conversion is withheld). None (the default,
      all pre-existing entries) = the ordinary single-commit conversion.
    - frontier_fire: ((grain, veg, wood, clay, reed, stone), food_out) when
      this entry (or one branch of it — Paintbrush's food branch) is a PURE
      good -> food converter reachable through the generalized in-harvest
      raise frame. The 6-tuple input carries the goods consumed at the
      converter's premium rate. Ruling 37 (2026-07-12) originally excluded
      crop-input converters (grain/veg positions always 0); ruling 77 item 1
      (2026-07-21) REVERSES that for FEEDING-PHASE crop converters — "we
      convert goods to food greedily … use Schnapps Distiller for the first
      veggie and our smaller rate for the remaining N-1" — so the grain/veg
      positions are now live (Schnapps Distiller/Distillery) — but NOT Beer Tap,
      whose super-linear tiers (2/3/4 grain -> 3/6/9 food) stay feed-seam-only
      per ruling 78 item 1 (the once-per-harvest budget is not a Pareto dim, so a
      forced frontier fire would commit it at the smallest tier). What
      ruling 37 still excludes stays out: rider outputs (points, goods) and
      field-input converters are NOT frontier-eligible and stay feed-seam-only.
      None (the default) = feed-seam-only. The raise-frame fire shares this
      entry's once-per-harvest budget (`harvest_conversions_used`) with the
      feed-seam offer (ruling 34).
    - frontier_group: the raise-frame mutual-exclusion group (ruling 76
      item 1, 2026-07-21 — Studio, the first multi-variant card to join the
      payment frontier). A multi-variant converter registers one entry per
      variant, all carrying the same frontier_group (Studio: "studio"); a
      single payment bundle may fire AT MOST ONE member of a group, because
      the variants are one card with one once-per-harvest budget (Studio's
      printed "exactly 1 wood/clay/stone" is a CHOICE of resource, not three
      independent fires — co-firing two variants in one bundle would use the
      card twice in one harvest). Enforced by `_food_payment_generalized`'s
      subset enumeration (helpers.py); the cross-FRAME once-per-harvest
      budget is separately enforced by is_owned_fn reading
      `harvest_conversions_used` (the prefix-guard convention), exactly as
      before. None (the default — every single-conversion card/major) = no
      group.
    """
    conversion_id: str
    input_cost:    Resources
    food_out:      int
    is_owned_fn:   Callable[["GameState", int], bool]
    side_effect_fn: Optional[Callable] = None
    variants_fn:   Optional[Callable[["GameState", int], list]] = None
    frontier_fire: Optional[tuple] = None
    frontier_group: Optional[str] = None


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


def fee_is_food_raisable(spec: HarvestConversionSpec) -> bool:
    """Does this conversion charge FOOD, so a player short of food must be
    allowed to raise it rather than be denied the use?

    `input_cost.food > 0` is the whole condition — the honest semantic rather
    than a list of card ids, so a future food-priced conversion is covered the
    day it registers. Every other input component is a building resource or a
    crop, which the raise frame can only ever CONSUME to produce food and never
    conjure, so those stay a plain on-hand requirement exactly as before.

    Why it exists — ruling 82 (2026-07-26), now CARD_AUTHORING_GUIDE.md §0.4:
    a food price gated on `resources.food >= N` "makes that legal payment line
    unplayable", because Agricola's at-any-time conversions are a legal way to
    pay. A food price must therefore be offered whenever the player can reach
    it by ANY legal route, with the shortfall raised through
    `PendingFoodPayment`.

    The FEED seam kept the plain gate until 2026-07-30. Ruling 84 item 4 had
    recorded that as harmless on the grounds that the free-span windows
    flanking the feed frame preserved every legal line — a reachability
    argument written by the implementer, not a user ruling; the user withdrew
    it on 2026-07-30 and directed the raise shape here too.

    Two entries qualify today: Basket Carrier (2 food → 1 wood + 1 reed +
    1 grain) and Furniture Carpenter (2 food → 1 bonus point). Both already
    register the continuation the raise frame resumes into
    (`register_food_payment_resume`); `_execute_harvest_conversion` asserts
    that contract rather than silently falling back to the plain gate.
    """
    return spec.input_cost.food > 0


# --- Built-in major-improvement crafts --------------------------------------

def _owns_major(idx: int) -> Callable[["GameState", int], bool]:
    """Return a closure: (state, player_idx) -> player owns major improvement idx."""
    def fn(state: "GameState", player_idx: int) -> bool:
        return state.board.major_improvement_owners[idx] == player_idx
    return fn


# The three craft majors are pure building-resource converters, so they are
# also reachable through the generalized in-harvest raise frame (rulings
# 34/37, 2026-07-12) — frontier_fire mirrors their input/output. The 6-tuple
# is (grain, veg, wood, clay, reed, stone); building converters leave
# grain=veg=0 (ruling 77 widened the tuple to carry crop inputs too).
register_harvest_conversion(HarvestConversionSpec(
    conversion_id="joinery",
    input_cost=Resources(wood=1),
    food_out=2,
    is_owned_fn=_owns_major(7),
    frontier_fire=((0, 0, 1, 0, 0, 0), 2),
))

register_harvest_conversion(HarvestConversionSpec(
    conversion_id="pottery",
    input_cost=Resources(clay=1),
    food_out=2,
    is_owned_fn=_owns_major(8),
    frontier_fire=((0, 0, 0, 1, 0, 0), 2),
))

register_harvest_conversion(HarvestConversionSpec(
    conversion_id="basketmaker",
    input_cost=Resources(reed=1),
    food_out=3,
    is_owned_fn=_owns_major(9),
    frontier_fire=((0, 0, 0, 0, 1, 0), 3),
))
