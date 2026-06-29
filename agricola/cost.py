"""Cost-resolution data types + the Pareto-min over payments.

The cost-modifier design (COST_MODIFIER_DESIGN.md) resolves what an action costs
through one chokepoint, `effective_payments` (which lives in `legality.py`, next to
`_can_afford` and the per-pending enumerators). This module holds the *data types*
that chokepoint produces and the pure Pareto-min helper it ends with — kept here,
dependency-light (only `Resources`), so `actions.py` / `legality.py` / `resolution.py`
can all import them without an import cycle.

A **`PaymentOption`** is the unit of payment for a build/renovate/improvement:
- a `Resources` vector (spend these goods), or
- a `ReturnImprovement` (a non-resource route — e.g. build a Cooking Hearth by
  returning a Fireplace you own; COST_MODIFIER_DESIGN.md §4.5 / A2). It carries no
  resource cost, so it bypasses the conversion/reduction pipeline and enters the
  frontier directly.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from agricola.resources import Animals, Resources

# The seven spendable resource components, in canonical order. The Pareto-min
# compares payments over exactly these and nothing else (never any attached reward
# or the route tag) — the exclusion that keeps the alt-cost-minor case correct (A1).
RESOURCE_FIELDS = ("wood", "clay", "reed", "stone", "food", "grain", "veg")


@dataclass(frozen=True)
class ReturnImprovement:
    """A non-resource payment route: pay for the build by returning a major
    improvement you own (the only instance today is Cooking Hearth via returning a
    Fireplace). `improvement_idx` names the returned major. Pareto-incomparable to
    every `Resources` payment, so it always survives the frontier."""
    improvement_idx: int


# The unit of payment surfaced on the frontier and carried by the commit.
PaymentOption = Resources | ReturnImprovement


@dataclass(frozen=True)
class CostCtx:
    """Everything an action contributes to cost resolution besides the player/state:
    its `action_kind`, its `base` (printed) cost, and the discriminators a modifier
    card might read. One flat type for every action — modifiers dispatch on
    `action_kind` and read whatever fields they need (COST_MODIFIER_DESIGN.md §2.2)."""
    action_kind: str                 # "renovate" | "build_room" | "build_major" | "play_minor"
    base: Resources                  # the base (printed) cost, computed by the action's adapter
    to_material: object | None = None    # renovate target material (Clay Plasterer, Chimney Sweep)
    num_rooms: int | None = None         # Master Bricklayer ("by rooms built")
    major_idx: int | None = None
    card_id: str | None = None
    space_id: str | None = None          # entry-point scope (Hunting Trophy, House Artist)
    build_index: int | None = None       # Nth room/stable/fence (Carpenter's Apprentice)
    reserved_animals: Animals = Animals()  # animal portion of THIS cost — reserved before
    #                                        counting animals as food-liquidation fuel, so
    #                                        liquidation never double-spends an animal the cost
    #                                        itself needs (FOOD_PAYMENT_DESIGN.md §4). Resource-
    #                                        only payments don't carry animals, so the modifier
    #                                        pipeline ignores it; only `_liquidatable_to` reads it.


def _goods_key(r: Resources) -> tuple:
    return tuple(getattr(r, f) for f in RESOURCE_FIELDS)


def _dominates(a: Resources, b: Resources) -> bool:
    """True iff payment `a` spends <= `b` in every component and < in at least one
    — i.e. `a` is strictly cheaper, so `b` is dominated and can be pruned."""
    ka, kb = _goods_key(a), _goods_key(b)
    return all(x <= y for x, y in zip(ka, kb)) and any(x < y for x, y in zip(ka, kb))


def pareto_min_over_goods(options: list[PaymentOption]) -> list[PaymentOption]:
    """The non-dominated payments. `Resources` entries are pruned by Pareto-dominance
    over the goods spent (cheaper dominates); identical ones are de-duplicated.
    `ReturnImprovement` routes are incomparable to everything (a different currency),
    so they are always kept. Order: surviving resource payments, then routes."""
    resources = [o for o in options if isinstance(o, Resources)]
    routes = [o for o in options if not isinstance(o, Resources)]
    # De-dup identical resource payments (keeps the first occurrence).
    uniq: dict[tuple, Resources] = {}
    for r in resources:
        uniq.setdefault(_goods_key(r), r)
    survivors = [
        r for r in uniq.values()
        if not any(other is not r and _dominates(other, r) for other in uniq.values())
    ]
    return survivors + routes
