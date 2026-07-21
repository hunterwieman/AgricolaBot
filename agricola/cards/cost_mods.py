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
# card_id -> seed_fn; the per-action free-fence allowance sources (Hedge Keeper, etc.).
# Not action_kind-keyed: a free-fence seed is about the Build Fences action as a whole, gated
# on ownership + (for the seed_fn to read) the literal-action flag / entry-point space.
FREE_FENCE_SEEDS: dict[str, Callable] = {}
# card_id -> edge_fn; per-edge POSITIONAL free-fence sources (Briar Hedge = board-perimeter
# edges; Field Fences = edges next to field tiles). DISTINCT from FREE_FENCE_SEEDS, which is a
# SCALAR per-action budget: a positional card frees SPECIFIC edges by board geometry, so its
# edge_fn returns the (h, v) edge BITMAPS it covers, and the fold unions them across owned
# cards (an edge two cards free is counted once) before intersecting with the pasture's new
# edges. Positional frees apply BEFORE the per-action budget (§9.4 greedy order).
FREE_FENCE_EDGES: dict[str, Callable] = {}


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


def register_free_fence_seed(card_id: str, seed_fn: Callable) -> None:
    """Register a card's contribution to the per-action free-fence budget
    (COST_MODIFIER_DESIGN.md §9.4 source 2). `seed_fn(state, idx, *, build_fences_action,
    space_id) -> int` returns how many fence edges this card frees for the Build Fences
    action described by those two signals (Hedge Keeper: 3 when `build_fences_action`).

    ONE seed function is the single source of truth for three call sites that must agree:
    the seed at frame push (resolution), the placement-time anticipation (legality's
    "is Build Fences available?"), and — via the remaining budget on the frame — the
    during-building enumerator. Ownership-gated like the other cost registries, so the
    Family game (no cards owned) gets `free_fence_budget_for(...) == 0`."""
    FREE_FENCE_SEEDS[card_id] = seed_fn


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


# card_id -> CardStore key holding that card's PERSISTENT free-fence POOL (Ash Trees). The
# THIRD free-fence source (COST_MODIFIER_DESIGN.md §9.4), distinct from the per-action SEEDS
# (a budget reset each action) and the per-edge geometric EDGES: a pool is a reserve of fence
# PIECES held on the card, placed for free and SPENT (decremented) as used. The pieces were
# moved from the player's 15-supply at play, so the total never exceeds 15; the pool counts
# toward `buildable_fences` (the pieces ARE placeable) AND waives their wood.
FREE_FENCE_POOLS: dict[str, str] = {}


def register_free_fence_pool(card_id: str, store_key: str) -> None:
    """Register a card's persistent free-fence pool, held in `card_state[store_key]`
    (Ash Trees). Ownership-gated; empty in the Family game."""
    FREE_FENCE_POOLS[card_id] = store_key


def free_fence_pool_remaining(player) -> int:
    """Total free fences across the player's owned pools (Ash Trees) — both BUILDABLE pieces
    and free of wood. Read by `buildable_fences` (piece count) and `_check_entry_legal` /
    the build accrue (free-wood source). 0 in the Family game (empty registry)."""
    return sum(player.card_state.get(key, 0)
               for cid, key in FREE_FENCE_POOLS.items() if _owns(player, cid))


def spend_fence_pools(player, n: int):
    """Spend up to `n` free fences across the player's owned pools (greedy, registration
    order); return (spent, new_card_state) with each used pool decremented. Called by the
    build path AFTER positional frees + the per-action budget (§9.4 source 3). The spent
    pieces come from the card, so the caller does NOT decrement the supply pile for them."""
    spent = 0
    card_state = player.card_state
    for cid, key in FREE_FENCE_POOLS.items():
        if spent >= n:
            break
        if not _owns(player, cid):
            continue
        avail = card_state.get(key, 0)
        take = min(avail, n - spent)
        if take:
            card_state = card_state.set(key, avail - take)
            spent += take
    return spent, card_state


# ---------------------------------------------------------------------------
# Stable-supply removals (Market Stall C54's play cost)
# ---------------------------------------------------------------------------
# The stable supply stays DERIVED (the CLAUDE.md derived-not-stored default):
# `helpers.stables_in_supply(player) = 4 - built - removals`, where removals are
# recorded in the removing card's own card_state and summed through this
# registry — the same shape as the free-fence pools above, in the opposite
# direction. This expresses a card cost like "1 Stable from Your Supply"
# (Market Stall C54: the piece is permanently spent, never built) without a
# stored PlayerState field, so the Family state shape, the canonical JSON, and
# the C++ contract are untouched (removals live in the card-only, default-
# skipped card_state). card_id -> card_state key holding that card's removed
# count. Ownership-gated; empty in the Family game.
STABLE_SUPPLY_REMOVALS: dict[str, str] = {}


def register_stable_supply_removal(card_id: str, store_key: str) -> None:
    """Register a card that removes stable pieces from its owner's supply
    without building them (card-module import time)."""
    STABLE_SUPPLY_REMOVALS[card_id] = store_key


def stables_removed_from_supply(player) -> int:
    """Total stable pieces card-removed from this player's supply. 0 in the
    Family game (empty registry)."""
    return sum(player.card_state.get(key, 0)
               for cid, key in STABLE_SUPPLY_REMOVALS.items() if _owns(player, cid))


def register_free_fence_edges(card_id: str, edge_fn: Callable) -> None:
    """Register a card's POSITIONAL per-edge free-fence contribution (COST_MODIFIER_DESIGN.md
    §9.4 source 1). `edge_fn(farmyard, h_new, v_new, *, state, idx, initiated_by_id,
    build_fences_action) -> (h_free_bm, v_free_bm)` returns which of the pasture's NEW edges
    (subsets of `h_new` / `v_new`) this card pays no wood for, by board geometry — e.g. Briar
    Hedge returns the board-perimeter intersection, ungated; Field Fences (later) returns the
    field-adjacent edges, gated on `initiated_by_id`. Ownership-gated; empty in the Family game,
    so `positional_free_edge_count` is always 0 there and the Family path stays byte-identical."""
    FREE_FENCE_EDGES[card_id] = edge_fn


def positional_free_edge_count(state, idx: int, farmyard, h_new: int, v_new: int, *,
                               initiated_by_id=None, build_fences_action: bool = True) -> int:
    """How many of a pasture's NEW edges (`h_new` / `v_new`) owned positional cards free of
    wood (COST_MODIFIER_DESIGN.md §9.4 source 1). Unions each owned card's free-edge bitmaps
    (an edge two cards free is counted once), intersects with the new edges, and returns the
    popcount. Applied BEFORE the per-action `free_fence_budget` (a positional-free edge never
    consumes the budget). 0 in the Family game (empty registry)."""
    p = state.players[idx]
    h_free = v_free = 0
    for card_id, edge_fn in FREE_FENCE_EDGES.items():
        if _owns(p, card_id):
            hf, vf = edge_fn(farmyard, h_new, v_new, state=state, idx=idx,
                             initiated_by_id=initiated_by_id,
                             build_fences_action=build_fences_action)
            h_free |= hf
            v_free |= vf
    return (h_free & h_new).bit_count() + (v_free & v_new).bit_count()


def free_fence_budget_for(state, idx: int, *, build_fences_action: bool, space_id) -> int:
    """Total per-action free-fence budget player `idx` would get for a Build Fences action
    with the given literal-action flag + entry-point space (COST_MODIFIER_DESIGN.md §9.4).
    Sums every owned free-fence card's `seed_fn` (sources stack). Family (no owned cards) → 0,
    so the `free_fence_budget` frame field stays default and the Family path is byte-identical."""
    p = state.players[idx]
    return sum(
        seed_fn(state, idx, build_fences_action=build_fences_action, space_id=space_id)
        for card_id, seed_fn in FREE_FENCE_SEEDS.items()
        if _owns(p, card_id)
    )


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


# Free-fence source 1b — ORDINAL frees (ruling 74, 2026-07-21; first member
# Carpenter's Apprentice C88: "Your 13th to 15th fence each cost you nothing").
# A card frees fence PIECES by their cumulative build ordinal (1-indexed over
# pieces placed on the board — derived from the farmyard fence popcount, which
# is exact because fences are never demolished and even pool pieces land on the
# board when built). NON-CONSUMING like the positional edges (source 1): a free
# ordinal waives the wood, never a budget or pool piece, and the piece still
# draws from supply (§9.7). Applied player-optimally alongside positional frees
# (ordinal frees cover non-positional pieces first — within one commit the
# player chooses placement order, so this is rules-true, and all pieces cost 1
# wood so only the count matters). Empty registry -> 0 -> byte-identical.
FREE_FENCE_ORDINALS: dict[str, Callable] = {}


def register_free_fence_ordinals(card_id: str, ordinals_fn: Callable) -> None:
    """Register a card's free fence ordinals. `ordinals_fn(state, idx) ->
    frozenset[int]` — the 1-indexed cumulative piece ordinals the owned card makes
    wood-free (Carpenter's Apprentice: frozenset({13, 14, 15}))."""
    FREE_FENCE_ORDINALS[card_id] = ordinals_fn


def ordinal_free_count(state, idx: int, built_before: int, count: int) -> int:
    """How many of the pieces with ordinals (built_before, built_before + count] are
    free under the player's owned ordinal cards. `built_before` = fences already on
    the board (the pre-commit farmyard popcount). Empty registry / nothing owned -> 0."""
    if not FREE_FENCE_ORDINALS:
        return 0
    p = state.players[idx]
    free: set = set()
    for card_id, fn in FREE_FENCE_ORDINALS.items():
        if _owns(p, card_id):
            free |= fn(state, idx)
    if not free:
        return 0
    return sum(1 for n in range(built_before + 1, built_before + count + 1) if n in free)
