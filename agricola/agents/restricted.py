"""Action-pruning wrapper around `legal_actions`.

`restricted_legal_actions(state)` returns a (possibly narrower) list of legal
actions, applying a fixed set of strategic priors. The wrapper never produces
an empty action set: each filter that would empty the list is skipped, so the
restricted list is always a subset of `legal_actions(state)` of size ≥ 1
(or 0 only when the input is also empty — phase=BEFORE_SCORING).

The priors are organized into per-pending filters:

- **Sub-action ordering** (provably losses are bounded — see notes):
    - Cultivation: plow before sow.
    - Grain Utilization: sow before bake.  (Caveat: bake-first is strictly
      more flexible with Potter Ceramics in play. The user accepted this
      tradeoff explicitly for the current card scope; revisit when more
      bake-event triggers land.)
    - Farm Expansion: build rooms before stables.

- **Cell priority** (opinionated; rooms/stables/plow go to predetermined cells):
    - Stables built in order: (0,4), (0,3), (1,4), (1,3).
    - Rooms built in order:   (0,0), (2,1), (1,1), (2,2).
    - Plow targets in order:  (0,1), (0,2), (1,1), (0,0), (1,2), (2,2), (2,3).
  At each Commit*-cell decision, the wrapper keeps only the top-priority
  legal cell. If none of the priority cells happen to be legal at the
  current state, the filter falls back to the full action set (preserves
  ≥1 legal action).

- **First-pasture opener**: the very first CommitBuildPasture in a given
  PendingBuildFences session must include cell (0,4) or (1,4). Once
  pastures_built >= 1 the restriction lifts.

- **Hard room cap**: never grow past 5 total rooms (2 starting + 3 additional).
  Applied at PendingFarmExpansion (drop ChooseSubAction("build_rooms")) and
  at PendingBuildRooms (drop further CommitBuildRoom once at cap).

- **Drop `use=False` craft conversions**: at PendingHarvestFeed, drop every
  `CommitHarvestConversion(use=False)` action. Explicitly declining a craft
  is redundant — the player can achieve the same outcome by going directly
  to `CommitConvert`. Saves consumers from spending evaluation on a no-op.

- **Minimum-begging at CommitConvert**: at PendingHarvestFeed, among all
  enumerated CommitConvert options keep only those that incur the minimum
  begging count. If multiple actions tie for the minimum, all are kept.

`strict_restricted_legal_actions(state)` is a sibling wrapper used by MCTS
that layers four additional filters on top of `restricted_legal_actions`
(see MCTS_DESIGN.md §7):

- **Cultivation sow-max**: at the PendingSow pushed by Cultivation, keep
  only the (grain, veg) commit that maximizes grain+veg (ties broken by
  more grain).
- **Grain-Utilization veggie rule**: at the PendingSow pushed by Grain
  Utilization, require `veg_sown == min(veggies_in_supply, empty_fields − grain_sown)`
  for each surviving commit — the player chooses grain; veg is auto-maxed.
- **Fencing patterns**: 9 hand-curated rules at PendingBuildFences that
  collapse the legal pasture-build set to specific openers / extensions
  keyed on (existing pastures, wood count).
- **Harvest-feed cap**: at PendingHarvestFeed, if more than 7 CommitConvert
  options are legal, keep the top-5 by `evaluate_hubris_v3` ranking plus 2
  random samples from the rest. Crafts and other actions are always kept.

Architectural choices:

- Engine code is NOT modified. Both wrappers are pure functions over the
  unrestricted `legal_actions(state)`. Removing or A/B-testing the
  restrictions is one constructor argument away.
- Filters compose. Each is a pure function `(state, top, actions) ->
  list[Action]`. The dispatcher inspects the top pending frame and applies
  the relevant filters in a fixed order.
- Both wrappers have zero effect when the pending stack is empty
  (PlaceWorker-level decisions). No restriction is applied to top-level
  worker placement.
"""

from __future__ import annotations

from typing import Callable

from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitHarvestConversion,
    CommitPlow,
    CommitSow,
    Stop,
)
from agricola.constants import CellType
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBuildFences,
    PendingBuildRooms,
    PendingBuildStables,
    PendingCultivation,
    PendingFarmExpansion,
    PendingGrainUtilization,
    PendingHarvestFeed,
    PendingPlow,
    PendingSow,
)
from agricola.state import GameState


# ---------------------------------------------------------------------------
# Priority lists and caps
# ---------------------------------------------------------------------------
#
# These tuples define both WHICH cells are allowed AND in what order they
# are filled. Cells not appearing in a list are never selected as long as
# any listed cell is legal. (If no listed cell is legal — rare; happens
# only in atypical board states — the filter falls back to the full
# action set so the agent stays unstuck.)
#
# Starting rooms are at (1, 0) and (2, 0) per setup.py, so they are
# intentionally absent from ROOM_PRIORITY (those cells already hold rooms).
# Plow priority lists 7 cells out of 13 plowable cells; the omitted cells
# are reserved for pasture / stable / room placements.

STABLE_PRIORITY: tuple[tuple[int, int], ...] = (
    (0, 4),
    (0, 3),
    (1, 4),
    (1, 3),
)

ROOM_PRIORITY: tuple[tuple[int, int], ...] = (
    (0, 0),
    (2, 1),
    (1, 1),
    (2, 2),
)

PLOW_PRIORITY: tuple[tuple[int, int], ...] = (
    (0, 1),
    (0, 2),
    (1, 1),
    (0, 0),
    (1, 2),
    (2, 2),
    (2, 3),
)

# The first pasture in any Build Fences session must include at least one of
# these cells. Once one pasture has been committed, the restriction lifts.
FIRST_PASTURE_REQUIRED_CELLS: frozenset = frozenset({(0, 4), (1, 4)})

# Hard cap on total rooms in the farmyard. 2 starting + 3 additional = 5.
MAX_TOTAL_ROOMS: int = 5


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def restricted_legal_actions(state: GameState) -> list[Action]:
    """Apply strategic action-pruning to `legal_actions(state)`.

    Returns a list that is a (possibly narrowed) subset of the unrestricted
    legal action set. Empty only when the unrestricted set is empty.

    Composition: filters are applied in dispatch order based on the type of
    the top pending frame. Each filter's `_safe_narrow(...)` call guarantees
    the result stays non-empty (filter is skipped if it would empty the set).
    """
    actions = legal_actions(state)
    if not actions:
        return actions
    if not state.pending_stack:
        # PlaceWorker-level decisions get no restriction.
        return actions

    top = state.pending_stack[-1]

    if isinstance(top, PendingFarmExpansion):
        actions = _filter_farm_expansion_room_cap(state, top, actions)
        actions = _filter_farm_expansion_ordering(state, top, actions)
    elif isinstance(top, PendingCultivation):
        actions = _filter_cultivation_ordering(state, top, actions)
    elif isinstance(top, PendingGrainUtilization):
        actions = _filter_grain_utilization_ordering(state, top, actions)
    elif isinstance(top, PendingBuildStables):
        actions = _filter_cell_priority(actions, STABLE_PRIORITY, CommitBuildStable)
    elif isinstance(top, PendingBuildRooms):
        actions = _filter_build_rooms_cap(state, top, actions)
        actions = _filter_cell_priority(actions, ROOM_PRIORITY, CommitBuildRoom)
    elif isinstance(top, PendingPlow):
        actions = _filter_cell_priority(actions, PLOW_PRIORITY, CommitPlow)
    elif isinstance(top, PendingBuildFences):
        actions = _filter_first_pasture(state, top, actions)
    elif isinstance(top, PendingHarvestFeed):
        actions = _filter_drop_use_false_craft(state, top, actions)
        actions = _filter_min_begging(state, top, actions)

    return actions


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_narrow(filtered: list[Action], fallback: list[Action]) -> list[Action]:
    """Return `filtered` if non-empty, else `fallback`.

    Universal escape valve: every filter calls through this so that an
    over-aggressive restriction can never produce an empty action set. The
    fallback preserves the engine's invariant that an active player always
    has at least one legal action available.
    """
    return filtered if filtered else fallback


def _count_rooms(grid: tuple) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.ROOM
    )


# ---------------------------------------------------------------------------
# Sub-action ordering filters (ChooseSubAction level)
# ---------------------------------------------------------------------------

def _filter_farm_expansion_ordering(
    state: GameState, top: PendingFarmExpansion, actions: list[Action],
) -> list[Action]:
    """Build rooms before stables at PendingFarmExpansion.

    If ChooseSubAction("build_rooms") is on offer (engine has decided room
    builds are legal), drop ChooseSubAction("build_stables"). Stop and any
    other actions pass through unchanged.
    """
    has_rooms = any(
        isinstance(a, ChooseSubAction) and a.name == "build_rooms"
        for a in actions
    )
    if not has_rooms:
        return actions
    narrowed = [
        a for a in actions
        if not (isinstance(a, ChooseSubAction) and a.name == "build_stables")
    ]
    return _safe_narrow(narrowed, actions)


def _filter_cultivation_ordering(
    state: GameState, top: PendingCultivation, actions: list[Action],
) -> list[Action]:
    """Plow before sow at PendingCultivation."""
    has_plow = any(
        isinstance(a, ChooseSubAction) and a.name == "plow"
        for a in actions
    )
    if not has_plow:
        return actions
    narrowed = [
        a for a in actions
        if not (isinstance(a, ChooseSubAction) and a.name == "sow")
    ]
    return _safe_narrow(narrowed, actions)


def _filter_grain_utilization_ordering(
    state: GameState, top: PendingGrainUtilization, actions: list[Action],
) -> list[Action]:
    """Sow before bake at PendingGrainUtilization."""
    has_sow = any(
        isinstance(a, ChooseSubAction) and a.name == "sow"
        for a in actions
    )
    if not has_sow:
        return actions
    narrowed = [
        a for a in actions
        if not (isinstance(a, ChooseSubAction) and a.name == "bake_bread")
    ]
    return _safe_narrow(narrowed, actions)


# ---------------------------------------------------------------------------
# Room cap filters (PendingFarmExpansion + PendingBuildRooms)
# ---------------------------------------------------------------------------

def _filter_farm_expansion_room_cap(
    state: GameState, top: PendingFarmExpansion, actions: list[Action],
) -> list[Action]:
    """Drop ChooseSubAction("build_rooms") when at the MAX_TOTAL_ROOMS cap.

    Stops the player from entering PendingBuildRooms when no more rooms can
    be built per this wrapper's policy (even though the engine would allow
    it).
    """
    p = state.players[top.player_idx]
    if _count_rooms(p.farmyard.grid) < MAX_TOTAL_ROOMS:
        return actions
    narrowed = [
        a for a in actions
        if not (isinstance(a, ChooseSubAction) and a.name == "build_rooms")
    ]
    return _safe_narrow(narrowed, actions)


def _filter_build_rooms_cap(
    state: GameState, top: PendingBuildRooms, actions: list[Action],
) -> list[Action]:
    """At PendingBuildRooms, drop CommitBuildRoom once the player is at cap.

    This catches the case where the cap is reached mid-session (multi-shot:
    the player built their MAX_TOTAL_ROOMS-th room and a further build is
    still offered by the engine but disallowed by policy). Stop is left in
    place — the engine offers it once num_built >= 1, which is always true
    in this branch because reaching the cap requires at least one commit.
    """
    p = state.players[top.player_idx]
    if _count_rooms(p.farmyard.grid) < MAX_TOTAL_ROOMS:
        return actions
    narrowed = [a for a in actions if not isinstance(a, CommitBuildRoom)]
    return _safe_narrow(narrowed, actions)


# ---------------------------------------------------------------------------
# Cell priority filter (PendingBuildStables / PendingBuildRooms / PendingPlow)
# ---------------------------------------------------------------------------

def _filter_cell_priority(
    actions: list[Action],
    priority: tuple[tuple[int, int], ...],
    commit_class: type,
) -> list[Action]:
    """Keep only the highest-priority cell among Commit* of `commit_class`.

    Strategy: walk `priority` in order; if any cell appears in the legal
    commit set, keep ONLY that one commit (plus any non-`commit_class`
    actions in the input — typically Stop). If none of the priority cells
    are legal, fall back to the original action set (the priority list
    didn't anticipate the current board shape).

    The semantic is: cells outside the priority list are never chosen as
    long as a priority cell is available; ordering among priority cells is
    strict, no tiebreaks.
    """
    commits = [a for a in actions if isinstance(a, commit_class)]
    others = [a for a in actions if not isinstance(a, commit_class)]
    if not commits:
        return actions
    by_cell = {(a.row, a.col): a for a in commits}
    for (r, c) in priority:
        if (r, c) in by_cell:
            return others + [by_cell[(r, c)]]
    # No priority cell is legal — fall back so the agent isn't stuck.
    return actions


# ---------------------------------------------------------------------------
# First-pasture filter (PendingBuildFences)
# ---------------------------------------------------------------------------

def _filter_first_pasture(
    state: GameState, top: PendingBuildFences, actions: list[Action],
) -> list[Action]:
    """At a fresh PendingBuildFences (`pastures_built == 0`), require the
    first committed pasture to include at least one cell from
    FIRST_PASTURE_REQUIRED_CELLS.

    Once any pasture has been committed (`pastures_built >= 1`), the
    restriction lifts and the full set of CommitBuildPasture options passes
    through.
    """
    if top.pastures_built > 0:
        return actions
    pastures = [a for a in actions if isinstance(a, CommitBuildPasture)]
    others = [a for a in actions if not isinstance(a, CommitBuildPasture)]
    if not pastures:
        return actions
    eligible = [
        p for p in pastures
        if any(cell in FIRST_PASTURE_REQUIRED_CELLS for cell in p.cells)
    ]
    return _safe_narrow(others + eligible, actions)


# ---------------------------------------------------------------------------
# Drop `use=False` craft conversions (PendingHarvestFeed)
# ---------------------------------------------------------------------------

def _filter_drop_use_false_craft(
    state: GameState, top: PendingHarvestFeed, actions: list[Action],
) -> list[Action]:
    """Drop every `CommitHarvestConversion(use=False)` from the action set.

    Explicitly declining a craft is a no-op the player can always achieve by
    going directly to `CommitConvert` (which terminates the feed pending
    without using any undecided crafts). `harvest_conversions_used` is reset
    each harvest in `_resolve_harvest_field`, so not recording the skip has
    no cross-harvest effect.
    """
    narrowed = [
        a for a in actions
        if not (isinstance(a, CommitHarvestConversion) and a.use is False)
    ]
    return _safe_narrow(narrowed, actions)


# ---------------------------------------------------------------------------
# Min-begging filter (PendingHarvestFeed)
# ---------------------------------------------------------------------------

def _filter_min_begging(
    state: GameState, top: PendingHarvestFeed, actions: list[Action],
) -> list[Action]:
    """Among enumerated CommitConvert options, keep only those with minimum
    begging.

    CommitHarvestConversion (craft-firing decisions) and Stop pass through
    unchanged — the filter only constrains the final convert.

    The begging count is computed directly from the action's consumed
    amounts:
        food_produced = grain·1 + veg·vR + sheep·sR + boar·bR + cattle·cR
        need = 2·people_total − newborns
        begging = max(0, need − food_supply − food_produced)
    where rates come from `cooking_rates(state, player_idx)`.

    All CommitConvert options sharing the minimum begging value are kept
    (typically a unique config, but ties are possible — e.g. two
    different upstream-goods configurations that both produce exactly
    enough food).
    """
    # Avoid importing helpers at module top to keep imports light.
    from agricola.helpers import cooking_rates

    converts = [a for a in actions if isinstance(a, CommitConvert)]
    others = [a for a in actions if not isinstance(a, CommitConvert)]
    if len(converts) <= 1:
        return actions

    p = state.players[top.player_idx]
    rates = cooking_rates(state, top.player_idx)  # (sheep, boar, cattle, veg)
    sR, bR, cR, vR = rates
    need = 2 * p.people_total - p.newborns
    food_supply = p.resources.food

    def begging_of(a: CommitConvert) -> int:
        food_produced = (
            a.grain
            + a.veg * vR
            + a.sheep * sR
            + a.boar * bR
            + a.cattle * cR
        )
        return max(0, need - food_supply - food_produced)

    scored = [(a, begging_of(a)) for a in converts]
    min_beg = min(b for _, b in scored)
    keep = [a for a, b in scored if b == min_beg]
    return _safe_narrow(others + keep, actions)


# ---------------------------------------------------------------------------
# Convenience export: the wrapper as a `legal_actions_fn` argument
# ---------------------------------------------------------------------------
#
# Both `RandomAgent` and `HeuristicAgent` take a `legal_actions_fn` kwarg
# defaulting to `agricola.legality.legal_actions`. Passing
# `restricted_legal_actions` swaps in the pruned action set everywhere the
# agent consults legality (top-level pick, singleton-skip, rollout).

LegalActionsFn = Callable[[GameState], list[Action]]


# ===========================================================================
# Strict mode (MCTS_DESIGN §7)
# ===========================================================================
#
# `strict_restricted_legal_actions(state)` layers four MCTS-specific filters
# on top of `restricted_legal_actions(state)`. Used by MCTS to collapse
# trivially-suboptimal sub-action chains, narrow PendingBuildFences to a
# hand-curated rule set, and cap CommitConvert branching at PendingHarvestFeed.
#
# The harvest-feed cap needs an evaluator config (HeuristicConfigV3) and an
# RNG. The module-level callable uses DEFAULT_CONFIG_V3 and a deterministic
# seed-0 RNG; callers that want their own RNG (e.g. an MCTS search instance)
# build a closure via `make_strict_restricted_legal_actions(...)`.


# Hand-curated fencing rule set (MCTS_DESIGN §7.3).
#
# Each rule is `(precondition, allowed_cell_sets, stop_allowed)`:
#
#   - precondition(state, top, p, wood, pastures, pasture_cells_union) -> bool
#   - allowed_cell_sets: list[frozenset[tuple[int, int]]] — the CommitBuildPasture
#     options the rule permits
#   - stop_allowed: bool — whether Stop is in the rule's allowed action set
#     (Stop is preserved only if also already legal at the pending; the
#     engine offers it iff `pastures_built >= 1`)
#
# If a state matches multiple rules, the filter's allowed-action set is the
# UNION of all matching rules' allowed actions (and stop_allowed is OR'd).

_RULE_2x2_TR     = frozenset({(0, 3), (0, 4), (1, 3), (1, 4)})
_RULE_3x2_TR     = frozenset({(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)})
_RULE_8CELL_L    = frozenset(
    {(0, 3), (0, 4), (1, 2), (1, 3), (1, 4), (2, 2), (2, 3), (2, 4)},
)
_RULE_TOP_2      = frozenset({(0, 3), (0, 4)})
_RULE_TOP_RIGHT_CELL = frozenset({(0, 4)})


def _pasture_identity_match(pastures, cells: frozenset) -> bool:
    """True iff `pastures` is exactly one pasture whose cells equal `cells`."""
    return len(pastures) == 1 and pastures[0].cells == cells


# ---------------------------------------------------------------------------
# Public entry point — STRICT
# ---------------------------------------------------------------------------

def strict_restricted_legal_actions(state: GameState) -> list[Action]:
    """Strict-mode wrapper layered atop `restricted_legal_actions(state)`.

    Adds the four MCTS-specific filters (Cultivation sow-max, Grain-Util
    veggie rule, Fencing patterns, Harvest-feed cap). Uses module-level
    defaults for the V3 evaluator config (`DEFAULT_CONFIG_V3`) and a
    deterministic seed-0 RNG for the harvest-feed cap's random samples.

    For callers that want their own RNG or config injected (e.g. an
    `MCTSSearch` instance threading its `search.rng` through every legality
    call), build a closure via `make_strict_restricted_legal_actions(...)`.
    """
    return _strict_impl(state, _default_config(), _default_rng())


def make_strict_restricted_legal_actions(
    *,
    config=None,
    rng=None,
) -> LegalActionsFn:
    """Build a strict legal_actions_fn closure with injected config and RNG.

    `config` defaults to `agricola.agents.heuristic.DEFAULT_CONFIG_V3`;
    `rng` defaults to a fresh `numpy.random.default_rng(0)`. Callers that
    need reproducible matches against a specific seed (e.g. MCTS) should
    pass their own pre-seeded RNG so the cap's random samples are tied to
    that seed.

    Returns a callable with signature `(state) -> list[Action]`, suitable
    for use as an agent's `legal_actions_fn`.
    """
    cfg = config if config is not None else _default_config()
    r = rng if rng is not None else _default_rng()
    def _fn(state: GameState) -> list[Action]:
        return _strict_impl(state, cfg, r)
    return _fn


def _strict_impl(state: GameState, cfg, rng) -> list[Action]:
    """Shared body for the strict wrapper and the factory closure."""
    actions = restricted_legal_actions(state)
    if not actions or not state.pending_stack:
        return actions
    top = state.pending_stack[-1]

    if isinstance(top, PendingSow):
        if top.initiated_by_id == "cultivation":
            actions = _filter_cultivation_sow_max(state, top, actions)
        elif top.initiated_by_id == "grain_utilization":
            actions = _filter_grain_utilization_veggie(state, top, actions)
    elif isinstance(top, PendingBuildFences):
        actions = _filter_fencing_patterns(state, top, actions)
    elif isinstance(top, PendingHarvestFeed):
        actions = _filter_strict_harvest_feed_cap(state, top, actions, cfg, rng)

    return actions


# Lazy module-level defaults — constructed on first use to avoid coupling the
# import order of this module to `agricola.agents.heuristic` (which imports
# from `agricola.agents.base`, which other code in `agricola/agents/__init__.py`
# touches first).

_DEFAULT_CONFIG_CACHE = None
_DEFAULT_RNG_CACHE = None


def _default_config():
    global _DEFAULT_CONFIG_CACHE
    if _DEFAULT_CONFIG_CACHE is None:
        from agricola.agents.heuristic import DEFAULT_CONFIG_V3
        _DEFAULT_CONFIG_CACHE = DEFAULT_CONFIG_V3
    return _DEFAULT_CONFIG_CACHE


def _default_rng():
    global _DEFAULT_RNG_CACHE
    if _DEFAULT_RNG_CACHE is None:
        import numpy as np
        _DEFAULT_RNG_CACHE = np.random.default_rng(0)
    return _DEFAULT_RNG_CACHE


# ---------------------------------------------------------------------------
# Cultivation sow-max (§7.1)
# ---------------------------------------------------------------------------

def _filter_cultivation_sow_max(
    state: GameState, top: PendingSow, actions: list[Action],
) -> list[Action]:
    """Keep only the CommitSow(grain, veg) maximizing grain+veg.

    Applies at PendingSow pushed by Cultivation. When cultivating, sowing
    fewer fields than the maximum throws away part of the action's value
    (Cultivation costs a worker placement either way), so we collapse to
    the single best-by-total CommitSow.

    Ties on total are broken by preferring more grain (grain has the higher
    end-game value-per-unit-sown when fields are limited).
    """
    sows = [a for a in actions if isinstance(a, CommitSow)]
    others = [a for a in actions if not isinstance(a, CommitSow)]
    if not sows:
        return actions
    best = max(sows, key=lambda a: (a.grain + a.veg, a.grain))
    return _safe_narrow(others + [best], actions)


# ---------------------------------------------------------------------------
# Grain-Utilization veggie rule (§7.2)
# ---------------------------------------------------------------------------

def _filter_grain_utilization_veggie(
    state: GameState, top: PendingSow, actions: list[Action],
) -> list[Action]:
    """At Grain-Util's PendingSow, auto-determine `veg_sown` from the grain choice.

    Rule: `veg_sown == min(veggies_in_supply, empty_fields − grain_sown)`.
    The player chooses grain freely; the surviving CommitSow for each grain
    value is the one with veg maxed out (never leave a plowed field empty
    when veggies are available to fill it).
    """
    sows = [a for a in actions if isinstance(a, CommitSow)]
    others = [a for a in actions if not isinstance(a, CommitSow)]
    if not sows:
        return actions
    p = state.players[top.player_idx]
    grid = p.farmyard.grid
    empty_fields = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
        and grid[r][c].grain == 0
        and grid[r][c].veg == 0
    )
    veggies = p.resources.veg
    kept = []
    for a in sows:
        required_veg = min(veggies, max(0, empty_fields - a.grain))
        if a.veg == required_veg:
            kept.append(a)
    return _safe_narrow(others + kept, actions)


# ---------------------------------------------------------------------------
# Fencing patterns (§7.3) — 9 hand-curated rules at PendingBuildFences
# ---------------------------------------------------------------------------

def _filter_fencing_patterns(
    state: GameState, top: PendingBuildFences, actions: list[Action],
) -> list[Action]:
    """Narrow CommitBuildPasture options to the 9 hand-curated patterns.

    Wood counts are EXACT (not lower bounds). Multiple rules may match a
    single state; the allowed-action set is the union. If no rule matches,
    the filter is inert (returns `actions` unchanged).

    Pasture identity vs cell-set semantics differ across rules:
      - Rule 7 (subdivision of a 2x2): requires a SINGLE pasture whose cells
        are exactly the 2x2 cell-set.
      - Rules 8 / 9 (extend the top row): require only that the UNION of all
        pasture cells equals exactly {(0,3),(0,4)} — they don't care whether
        that's one 1x2 pasture or two 1x1 pastures.
    """
    p = state.players[top.player_idx]
    wood = p.resources.wood
    pastures = p.farmyard.pastures
    pasture_cells_union = frozenset(
        cell for past in pastures for cell in past.cells
    )

    allowed_cells: list[frozenset] = []
    stop_allowed = False

    if not pastures:
        # Rule 1
        if wood in (7, 8, 9):
            allowed_cells.append(_RULE_TOP_RIGHT_CELL)
        # Rule 2
        if wood == 10:
            allowed_cells.append(_RULE_2x2_TR)
            allowed_cells.append(_RULE_3x2_TR)
        # Rule 3
        if wood == 13:
            allowed_cells.append(_RULE_3x2_TR)
        # Rule 4
        if wood == 15:
            allowed_cells.append(_RULE_8CELL_L)
            allowed_cells.append(_RULE_3x2_TR)
    else:
        # Rules 5 / 6: a single 1x1 at (0,4) already exists.
        if _pasture_identity_match(pastures, _RULE_TOP_RIGHT_CELL):
            if wood == 3:
                allowed_cells.append(frozenset({(0, 3)}))
                stop_allowed = True
            if wood == 5:
                allowed_cells.append(frozenset({(1, 4), (2, 4)}))
                stop_allowed = True
        # Rule 7: single 2x2 at top-right (subdivision).
        if _pasture_identity_match(pastures, _RULE_2x2_TR) and wood == 2:
            allowed_cells.append(_RULE_TOP_2)
        # Rules 8 / 9: pastures cover exactly {(0,3),(0,4)} (any split).
        if pasture_cells_union == _RULE_TOP_2:
            if wood == 4:
                allowed_cells.append(frozenset({(1, 3), (1, 4)}))
                stop_allowed = True
            if wood == 6:
                allowed_cells.append(frozenset({(1, 3), (1, 4), (2, 3), (2, 4)}))
                stop_allowed = True

    if not allowed_cells and not stop_allowed:
        # No rule matches the current (pastures, wood) combination — inert.
        return actions

    narrowed: list[Action] = []
    for a in actions:
        if isinstance(a, CommitBuildPasture):
            if a.cells in allowed_cells:
                narrowed.append(a)
        elif isinstance(a, Stop):
            if stop_allowed:
                narrowed.append(a)
        else:
            # Defensive: pass through anything else (e.g., FireTrigger).
            narrowed.append(a)

    return _safe_narrow(narrowed, actions)


# ---------------------------------------------------------------------------
# Harvest-feed cap (§7.4)
# ---------------------------------------------------------------------------

def _filter_strict_harvest_feed_cap(
    state: GameState,
    top: PendingHarvestFeed,
    actions: list[Action],
    cfg,
    rng,
) -> list[Action]:
    """Cap CommitConvert branching at PendingHarvestFeed.

    If ≤7 CommitConvert options are present, no cap is applied. Otherwise:
    rank commits by `evaluate_hubris_v3(step(state, a), decider, cfg)`
    descending; keep the top 5 plus 2 random samples (drawn without
    replacement) from the rest.

    Crafts (`CommitHarvestConversion`) and any other actions pass through
    unchanged — sub-sampling crafts risks dropping a strategically important
    one and saves nothing (at most ~3 crafts exist in the Family game).
    """
    crafts: list[Action] = []
    commits: list[CommitConvert] = []
    other: list[Action] = []
    for a in actions:
        if isinstance(a, CommitHarvestConversion):
            crafts.append(a)
        elif isinstance(a, CommitConvert):
            commits.append(a)
        else:
            other.append(a)

    if len(commits) <= 7:
        return actions

    # Lazy imports — keep the wrapper's module load light. The factory
    # functions cache imports already; the cap path is rarely hit, so
    # importing here avoids paying for state/evaluator setup on cold runs.
    from agricola.agents.heuristic import evaluate_hubris_v3
    from agricola.engine import step

    decider = top.player_idx

    def commit_score(a: CommitConvert) -> float:
        return evaluate_hubris_v3(step(state, a), decider, cfg)

    commits_ranked = sorted(commits, key=commit_score, reverse=True)
    top_5 = commits_ranked[:5]
    rest = commits_ranked[5:]

    n_random = min(2, len(rest))
    if n_random > 0:
        idxs = rng.choice(len(rest), size=n_random, replace=False)
        random_2 = [rest[int(i)] for i in idxs]
    else:
        random_2 = []

    return crafts + other + top_5 + random_2
