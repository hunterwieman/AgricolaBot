"""Cost-modifier registries + fold accessors (COST_MODIFIER_DESIGN.md §2.5).

A cost card adds one row to one of these registries at import time; no engine edits.
The chokepoint `effective_payments` (in `legality.py`) reads them through the plural
*fold accessors* defined here. Three modifier kinds + the non-resource routes:

- **formula** — replaces the whole printed cost with a fixed alternative (the player
  uses <=1; each seeds its own base). `register_formula`.
- **reduction** — a signed delta on the cost (subtract — or, rarely, add — then floor
  every component at 0). `register_reduction`.
- **conversion** — an optional resource-for-resource substitution at payment time; an
  internally-budgeted *generator* (returns the unchanged input plus every legal
  substitution variant). `register_conversion`.
- **base_route** — a non-resource payment route (`ReturnImprovement`). `register_base_route`.

Family game → every registry empty → every fold is a no-op (returns its input / an
empty list), so `effective_payments` returns `[ctx.base]` — today's cost, no overhead.

Each registry is keyed by `action_kind` ("renovate"|"build_room"|"build_major"|
"play_minor"|…). Ownership is checked here (a hand card cannot modify costs).
"""
from __future__ import annotations

from typing import Callable

from agricola.cost import RESOURCE_FIELDS
from agricola.resources import Resources

# action_kind -> list of (card_id, applies_fn, formula_fn)
FORMULA_MODS: dict[str, list[tuple[str, Callable, Callable]]] = {}
# action_kind -> list of (card_id, reduce_fn)
REDUCTIONS: dict[str, list[tuple[str, Callable]]] = {}
# action_kind -> list of (order, card_id, expand1_fn, record_fn); applied low-order first
# (sink last). record_fn (optional) lets a per-ACTION-budgeted conversion (Millwright) record
# how many budget units a committed payment used, into the card's own CardStore (§ below).
CONVERSIONS: dict[str, list[tuple[int, str, Callable, Callable | None]]] = {}
# action_kind -> list of (card_id_or_None, routes_fn); card_id None = a built-in route
BASE_ROUTES: dict[str, list[tuple[str | None, Callable]]] = {}


def register_formula(action_kind: str, card_id: str, applies: Callable, formula: Callable) -> None:
    """`applies(state, idx, ctx) -> bool`; `formula(state, idx, ctx) -> Resources`."""
    FORMULA_MODS.setdefault(action_kind, []).append((card_id, applies, formula))


def register_reduction(action_kind: str, card_id: str, reduce: Callable) -> None:
    """`reduce(state, idx, ctx, cost: Resources) -> Resources` (a signed delta; the
    fold floors every component at 0 afterward)."""
    REDUCTIONS.setdefault(action_kind, []).append((card_id, reduce))


def register_conversion(action_kind: str, card_id: str, expand1: Callable, *,
                        order: int = 0, record: Callable | None = None) -> None:
    """`expand1(state, idx, ctx, cost: Resources) -> list[Resources]` — an
    internally-budgeted generator that returns the unchanged `cost` plus every legal
    substitution variant. `order` sequences chained conversions: producers low, a
    consuming *sink* (e.g. Millwright, which eats any building resource) high, so the
    sink is applied after the feeders it consumes (COST_MODIFIER_DESIGN.md §4.7).

    `record(state, idx, payment) -> state` (optional) is for a conversion whose budget
    is PER BUILD-ACTION rather than per single build — e.g. Millwright's "up to 2 grain
    per build-rooms/stables ACTION." A multi-shot build (rooms/stables) resolves one
    build at a time, so such a conversion must track how much budget it has spent so far
    THIS action: its `expand1` reads the running count from the card's CardStore and caps
    accordingly, and `record` is called at each build's debit to add the units that
    payment consumed back to that count. The card resets the count at its
    `after_build_*` hook (the Shepherd's-Crook per-action-state pattern). Stateless /
    per-single-build conversions (Frame Builder) leave `record=None`."""
    CONVERSIONS.setdefault(action_kind, []).append((order, card_id, expand1, record))


def register_base_route(action_kind: str, card_id: str | None, routes_fn: Callable) -> None:
    """`routes_fn(state, idx, ctx) -> list[ReturnImprovement]`. `card_id=None` for a
    built-in route (always available); a card id gates the route on ownership."""
    BASE_ROUTES.setdefault(action_kind, []).append((card_id, routes_fn))


# --- ownership + flooring helpers ---

def _owns(player_state, card_id: str) -> bool:
    return card_id in player_state.occupations or card_id in player_state.minor_improvements


def _floor(r: Resources) -> Resources:
    """Clamp every resource component at 0 (a reduction may over-subtract)."""
    return Resources(**{f: max(0, getattr(r, f)) for f in RESOURCE_FIELDS})


# --- fold accessors (the plural forms `effective_payments` calls) ---

def formula_mods(action_kind: str, state, idx: int, ctx) -> list[Resources]:
    """One alternative base per owned, applicable formula card (the player uses <=1)."""
    p = state.players[idx]
    return [
        formula(state, idx, ctx)
        for card_id, applies, formula in FORMULA_MODS.get(action_kind, ())
        if _owns(p, card_id) and applies(state, idx, ctx)
    ]


def apply_reductions(action_kind: str, state, idx: int, ctx, cost: Resources) -> Resources:
    """Fold every owned reduction over `cost` (signed deltas, floored at 0 after each)."""
    p = state.players[idx]
    for card_id, reduce in REDUCTIONS.get(action_kind, ()):
        if _owns(p, card_id):
            cost = _floor(reduce(state, idx, ctx, cost))
    return cost


def owned_conversions(action_kind: str, state, idx: int) -> list[Callable]:
    """The owned conversions' `expand1` generators, ordered producers-before-sinks."""
    p = state.players[idx]
    rows = [(o, fn) for o, cid, fn, _rec in CONVERSIONS.get(action_kind, ()) if _owns(p, cid)]
    rows.sort(key=lambda r: r[0])
    return [fn for _, fn in rows]


def record_conversion_usage(action_kind: str, state, idx: int, payment):
    """After a payment is committed for a build, let each owned per-action-budgeted
    conversion record how many budget units that payment used (updating its own
    CardStore counter), so the NEXT build in the same multi-shot action sees the
    reduced budget. A no-op when no owned conversion has a `record` fn — always in the
    Family game (no cards owned), so the build debits stay byte-identical there."""
    p = state.players[idx]
    for _o, cid, _fn, record in sorted(CONVERSIONS.get(action_kind, ()), key=lambda r: r[0]):
        if record is not None and _owns(p, cid):
            state = record(state, idx, payment)
    return state


def expand_conversions(action_kind: str, state, idx: int, ctx, base: Resources) -> list[Resources]:
    """Candidate payment vectors reachable from `base` via the owned conversions.

    Apply each conversion's budgeted generator EXACTLY ONCE, in order, to the growing
    candidate set. Applying each once (not in two undifferentiated rounds) respects a
    conversion's own "once per action" budget — its `expand1` already encodes all of
    its 0..max variants — while the producers-before-sinks ordering still lets a later
    conversion consume an earlier one's output (the clay->wood->grain chain). Bounded
    and finite; a no-op (`[base]`) when no conversion is owned. A test-only guard
    asserts this equals the budget-respecting closure (COST_MODIFIER_DESIGN.md §4.7)."""
    convs = owned_conversions(action_kind, state, idx)
    cands = {base}
    for fn in convs:
        cands = cands | {c for b in cands for c in fn(state, idx, ctx, b)}
    return list(cands)


def base_routes(action_kind: str, state, idx: int, ctx) -> list:
    """The non-resource payment routes (ReturnImprovement) available now."""
    p = state.players[idx]
    out: list = []
    for card_id, routes_fn in BASE_ROUTES.get(action_kind, ()):
        if card_id is None or _owns(p, card_id):
            out.extend(routes_fn(state, idx, ctx))
    return out


# --- built-in (non-card) routes ---------------------------------------------
# Cooking Hearth via Fireplace-return is a CORE Family rule, not a card: building a
# Cooking Hearth (major_idx 2 or 3) may be paid by returning a Fireplace (idx 0 or 1)
# you own instead of paying clay (COST_MODIFIER_DESIGN.md §4.5). Modeled as a built-in
# `base_route` (card_id=None) so `effective_payments` surfaces it as a `ReturnImprovement`
# alongside the resource payment, Pareto-incomparable to it (both survive).

def _cooking_hearth_fireplace_routes(state, idx: int, ctx) -> list:
    from agricola.constants import COOKING_HEARTH_INDICES, FIREPLACE_INDICES
    from agricola.cost import ReturnImprovement
    if ctx.major_idx not in COOKING_HEARTH_INDICES:
        return []
    owners = state.board.major_improvement_owners
    return [ReturnImprovement(fp) for fp in FIREPLACE_INDICES if owners[fp] == idx]


register_base_route("build_major", None, _cooking_hearth_fireplace_routes)
