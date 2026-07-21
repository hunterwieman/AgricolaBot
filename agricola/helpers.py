from __future__ import annotations

import functools
import math
from itertools import product as iproduct

from agricola import opt_config
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.state import Farmyard, GameState, PlayerState


# ---------------------------------------------------------------------------
# Part 0: Decision-free animal grants
# ---------------------------------------------------------------------------

def grant_animals(state: GameState, idx: int, animals: Animals) -> GameState:
    """Give player `idx` `animals` with NO immediate accommodation decision, and flag
    the player for the accommodation barrier.

    This is the single choke point for every decision-free animal gain — round-start
    collection (engine._collect_future_rewards) and on-play card gains (Game Trade,
    Young Animal Market, Shepherd's Crook). It adds the animals to `player.animals`
    *even if that exceeds the farm's housing capacity* (a transient over-capacity state
    — nothing asserts animals <= capacity; only scoring reads the totals, and the
    barrier always reconciles before scoring) and sets `animals_need_accommodation`.

    The engine's accommodation barrier (engine._reconcile_accommodation, run at every
    decision boundary in _advance_until_decision) then checks — only for a flagged
    player — whether the animals fit; if not, it surfaces a PendingAccommodate so the
    player chooses which to keep (the rest cooked to food). If they DO fit, the barrier
    just clears the flag (no frame). Batching is automatic: several grants at the same
    game moment land here before any decision boundary, so the barrier sees the combined
    total and asks once. The per-card contract is simply "grant your animals in one
    synchronous shot" — do not interleave a player prompt between two same-moment grants.
    """
    p = state.players[idx]
    p = fast_replace(
        p, animals=p.animals + animals, animals_need_accommodation=True,
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)),
    )


def suppress_space_reward(state: GameState) -> GameState:
    """Suppress the TOP action-space host's OWN reward — the general half of the
    reward-replacement seam (ACTION_REPLACEMENT_DESIGN.md). A card's optional
    replace-trigger calls this in the space's before-window, then applies its own
    alternate grant SEPARATELY (the two are independent — the alternate reward never
    rides the suppressed channel).

    Host-aware, because the two host kinds represent their reward differently:

    - **Atomic host** (`PendingActionSpace` — Day Laborer / Animal Catcher): the
      reward is a function run at Proceed (`ATOMIC_HANDLERS`), so the only way to
      suppress it is to skip that function. Set ``suppressed=True``; ``_apply_proceed``
      checks it, and the ``taken`` delta then reads ``Resources()`` — so "got food
      from a space" reactors (Kindling Gatherer) self-correct with no special-casing.
    - **Animal market** (`PendingSheepMarket` / `PendingPigMarket` /
      `PendingCattleMarket` — Pet Lover): the reward is the ``gained`` animals swept
      off the space at initiate. Suppress = leave them on the space (restore
      ``accumulated_amount``) and zero ``gained`` — "took nothing from the space", so
      the now-trivial ``CommitAccommodate`` just flips to the after-phase and any
      future "took an animal from a market" reactor (which would read ``gained``)
      stays silent.

    Card-only: only ever called from a played card's trigger, so the Family game and
    the C++ gates never reach it.
    """
    from agricola.pending import (
        PendingActionSpace, PendingSheepMarket, PendingPigMarket,
        PendingCattleMarket, replace_top,
    )
    from agricola.state import get_space, with_space

    top = state.pending_stack[-1]
    if isinstance(top, PendingActionSpace):
        return replace_top(state, fast_replace(top, suppressed=True))
    assert isinstance(top, (PendingSheepMarket, PendingPigMarket, PendingCattleMarket)), (
        f"suppress_space_reward: unsupported host {type(top).__name__}")
    space = get_space(state.board, top.space_id)
    state = fast_replace(state, board=with_space(
        state.board, top.space_id,
        fast_replace(space, accumulated_amount=space.accumulated_amount + top.gained)))
    return replace_top(state, fast_replace(top, gained=0))


# ---------------------------------------------------------------------------
# Part 1: Simple derived quantities
# ---------------------------------------------------------------------------

def fences_built(farmyard: Farmyard) -> int:
    """Count fence pieces placed on the board (derived from the fence arrays)."""
    return (
        sum(sum(row) for row in farmyard.horizontal_fences)
        + sum(sum(row) for row in farmyard.vertical_fences)
    )


def buildable_fences(player: PlayerState) -> int:
    """Fence PIECES the player can still place onto the board: the supply pile
    (`fences_in_supply`, location 4) plus any held on cards (Ash Trees pools, location 3) —
    both are placeable; only the wood differs. Distinct from the SUPPLY count, which excludes
    the on-card pieces (the conflation that motivated the stored `fences_in_supply` field). In
    the Family game (no cards) this equals `15 - fences_built(farmyard)`, the old derived
    value. The pool total is registry-driven (the card-game cost-mod registries); the local
    import avoids a load-time cycle (helpers -> cards package)."""
    from agricola.cards.cost_mods import free_fence_pool_remaining
    return player.fences_in_supply + free_fence_pool_remaining(player)


def stables_built(farmyard: Farmyard) -> int:
    """Count stables ON the board (built). Derived from the grid — the read the
    built-count consumers (capacity, Tumbrel, the heuristic) want."""
    return sum(
        1 for r in range(3) for c in range(5)
        if farmyard.grid[r][c].cell_type == CellType.STABLE
    )


def stables_in_supply(player_state) -> int:
    """Stable PIECES still in the player's supply pile: 4 − built − card-removed.

    Derived, per the derived-not-stored default: a card cost that spends a
    stable piece without building it (Market Stall C54's "1 Stable from Your
    Supply") records the removal in its own card_state, summed through the
    cost-mod registry — so `4 − built` alone is NOT the supply once such a card
    is played, and build legality must gate on THIS. Family game: the registry
    is empty and this is exactly `4 − built`. Consumers wanting the BUILT count
    use `stables_built`, never `4 − stables_in_supply` (which double-counts
    card removals as buildings). The local import avoids a load-time cycle
    (helpers -> cards package)."""
    from agricola.cards.cost_mods import stables_removed_from_supply
    return (4 - stables_built(player_state.farmyard)
            - stables_removed_from_supply(player_state))


def cooking_rates(state: GameState, player_idx: int) -> tuple[int, int, int, int]:
    """Return (sheep_rate, boar_rate, cattle_rate, veg_rate) for at-any-time food conversion.

    Based on the best cooking improvement the player owns:
      Cooking Hearth (major idx 2 or 3) -> (2, 3, 4, 3)
      Fireplace      (major idx 0 or 1) -> (2, 2, 3, 2)
      Neither                           -> (0, 0, 0, 1)

    If the player owns both a Fireplace and a Cooking Hearth, the Cooking
    Hearth rates apply (they are strictly better for every type).

    The veg rate has a 1:1 fallback per RULES.md feeding rules ("Grain and
    vegetables in personal supply count as 1 food each"). Animal rates have
    no such fallback — without a cooking improvement, animals cannot be
    converted to food, so the rate is 0.

    Callers that only need the animal triple (e.g. pareto_frontier,
    breeding_frontier) slice the first three elements: cooking_rates(...)[:3].

    Card seam: the base tuple is folded through the owned cooking-rate bonuses
    (`agricola/cards/cooking_mods.py` — Fatstock Stretcher's +1 sheep/boar).
    Empty registry (the Family game) → the base tuple unchanged. Cache-safe:
    every memoized frontier takes the rates as explicit key arguments, so a
    card-modified rate is a different key by construction (§5.4). The local
    import is the load-order-safe idiom (see `stables_in_supply`)."""
    owners = state.board.major_improvement_owners
    has_hearth    = any(owners[i] == player_idx for i in (2, 3))
    has_fireplace = any(owners[i] == player_idx for i in (0, 1))

    if has_hearth:
        base = (2, 3, 4, 3)
    elif has_fireplace:
        base = (2, 2, 3, 2)
    else:
        base = (0, 0, 0, 1)
    from agricola.cards.cooking_mods import apply_cooking_rate_bonuses
    return apply_cooking_rate_bonuses(state, player_idx, base)


# ---------------------------------------------------------------------------
# Part 2: Pasture-derived helpers
# ---------------------------------------------------------------------------
#
# `Pasture` and the BFS that builds the pasture decomposition live in
# `agricola.pasture`. The decomposition itself is cached on
# `Farmyard.pastures` (auto-filled by `Farmyard.__post_init__`), so reading
# from `farmyard.pastures` is O(1). All helpers below derive from it.

def enclosed_cells(farmyard: Farmyard) -> frozenset:
    """Return the set of (row, col) coordinates that are inside any pasture."""
    result: set = set()
    for p in farmyard.pastures:
        result.update(p.cells)
    return frozenset(result)


# ---------------------------------------------------------------------------
# Part 3: Farm slots, can_accommodate, pareto_frontier
# ---------------------------------------------------------------------------

def extract_slots(player_state: PlayerState) -> tuple[list[int], int]:
    """Return (pasture_capacities, num_flexible_slots).

    pasture_capacities: list of ints, one per pasture.
    num_flexible_slots: standalone stables + the house-pet capacity (1 by default; raised
    by a capacity card such as Animal Tamer — see agricola/cards/capacity_mods.py).
    """
    pastures = player_state.farmyard.pastures
    pasture_capacities = [p.capacity for p in pastures]

    total_stables_built = stables_built(player_state.farmyard)
    stables_in_pastures = sum(p.num_stables for p in pastures)
    standalone_stables = total_stables_built - stables_in_pastures

    # Card capacity modifiers (no-op in the Family game). The house provides 1 flexible slot
    # (the default pet) unless raised — Animal Tamer grants one per room (each may hold a
    # different type, which the flexible-slot model already captures). A per-pasture card
    # (Drinking Trough) adds a flat bonus to every pasture's capacity. Local import: the cards
    # package imports engine modules, so a top-level import here would cycle — the
    # load-order-safe pattern legality.py uses for cost_mods. Empty registries -> +0 / 1, so
    # this stays byte-identical (and the frontier caches key on these outputs, so no staleness).
    from agricola.cards.capacity_mods import (
        extra_animal_caps,
        extra_flexible_slots,
        house_pet_capacity,
        pasture_capacity_bonus,
        pasture_capacity_per_list,
        reserved_empty_pasture_indices,
    )
    bonus = pasture_capacity_bonus(player_state)
    if bonus:
        pasture_capacities = [c + bonus for c in pasture_capacities]
    # Per-pasture CONDITIONED bonuses (Tinsmith Master: +1 only for a pasture with no
    # stable) — a parallel list summed per pasture, None on the Family fast path. Applied
    # like the flat bonus: after the stable doubling, before the reserved-empty drop (a
    # reserved pasture's capacity comparison must see its true final capacity).
    per = pasture_capacity_per_list(player_state, pastures)
    if per is not None:
        pasture_capacities = [c + b for c, b in zip(pasture_capacities, per)]
    num_flexible = (standalone_stables + house_pet_capacity(player_state)
                    + extra_flexible_slots(player_state))

    # A card may FORBID animals in one pasture (Herbal Garden / Beaver Colony): drop the
    # reserved (smallest-capacity qualifying) pasture from the list entirely. Empty registry
    # -> no reservation -> byte-identical. `pasture_capacities` is still parallel to
    # `pastures` here (the bonus preserves order/length), so the indices align.
    reserved = reserved_empty_pasture_indices(player_state, pastures, pasture_capacities)
    if reserved:
        pasture_capacities = [c for i, c in enumerate(pasture_capacities)
                              if i not in reserved]

    # Pasture-LIKE card holders (Stockyard: one anonymous single-type bin of 3)
    # append LAST — after the per-pasture bonuses and the reserved-empty drop —
    # so no pasture-only fold can ever touch a card bin, and the rules layer
    # (pasture scoring, pasture-referencing effects) keeps reading farmyard
    # geometry rather than this anonymous list. Empty registry -> () ->
    # byte-identical (and the frontier caches key on these outputs).
    extra = extra_animal_caps(player_state)
    if extra:
        pasture_capacities = pasture_capacities + list(extra)

    return pasture_capacities, num_flexible


def can_accommodate(
    pasture_capacities: list[int],
    num_flexible: int,
    sheep: int,
    boar: int,
    cattle: int,
) -> bool:
    """Check if (sheep, boar, cattle) animals can be assigned to the given slots.

    Each pasture holds exactly ONE type of animal (up to its capacity).
    Each flexible slot (standalone stable or house) holds exactly 1 animal of any type.

    Try all assignments of animal types to pastures; return True if any assignment
    results in total overflow ≤ num_flexible.
    """
    counts = (sheep, boar, cattle)
    n = len(pasture_capacities)

    # Each pasture assigned to: 0=empty, 1=sheep, 2=boar, 3=cattle
    for assignment in iproduct(range(4), repeat=n):
        dedicated = [0, 0, 0]
        for i, t in enumerate(assignment):
            if t > 0:
                dedicated[t - 1] += pasture_capacities[i]

        overflow = sum(max(0, counts[t] - dedicated[t]) for t in range(3))
        if overflow <= num_flexible:
            return True

    return False


def _typed_slot_strip(player_state: PlayerState, gained: Animals):
    """The GREEDY STRIP for typed (per-species) card slots (originally the
    sheep-only Dolly's Mother strip, user-proposed 2026-07-06; generalized to
    the per-species registry 2026-07-21 — Wildlife Reserve, Cattle Farm, Mud
    Patch, Sheep Agent). Exact by dominance, per type INDEPENDENTLY: a typed
    slot can hold only its own species, so parking that species there never
    constrains any other animal — the owner's accommodation problem equals the
    standard one with the parked animals removed. Returns
    (strip: Animals, doctored_player, doctored_gained): per-species strips
    taken from `gained` first, then the player's animals — or
    (Animals(), unchanged, unchanged) for the Family fast path. Callers add
    the stripped animals back to every result; food math is unchanged (cooked
    counts are differences)."""
    from agricola.cards.capacity_mods import typed_slot_counts

    slots = typed_slot_counts(player_state)
    strips = {}
    g_new = {}
    p_new = {}
    for t in ("sheep", "boar", "cattle"):
        have = getattr(player_state.animals, t) + getattr(gained, t)
        strip = min(getattr(slots, t), have)
        strips[t] = strip
        if not strip:
            continue
        from_gained = min(strip, getattr(gained, t))
        if from_gained:
            g_new[t] = getattr(gained, t) - from_gained
        rest = strip - from_gained
        if rest:
            p_new[t] = getattr(player_state.animals, t) - rest
    if g_new:
        gained = fast_replace(gained, **g_new)
    if p_new:
        player_state = fast_replace(
            player_state,
            animals=fast_replace(player_state.animals, **p_new))
    return Animals(**strips), player_state, gained


def accommodates(player_state: PlayerState, sheep: int, boar: int, cattle: int) -> bool:
    """Can this player's farm house (sheep, boar, cattle)? THE ownership-aware
    accommodation check: `extract_slots` + the typed card-slot strip (Dolly's
    Mother's sheep slot, the 2026-07-21 per-species holders) +
    `can_accommodate`. Player-level callers (the accommodation barrier, card
    conditions) use this; `can_accommodate` stays the pure slots-level
    primitive."""
    from agricola.cards.capacity_mods import typed_slot_counts

    caps, num_flexible = extract_slots(player_state)
    slots = typed_slot_counts(player_state)
    return can_accommodate(caps, num_flexible,
                           max(0, sheep - slots.sheep),
                           max(0, boar - slots.boar),
                           max(0, cattle - slots.cattle))


def pareto_frontier(
    player_state: PlayerState,
    gained: Animals,
    rates: tuple[int, int, int] = (0, 0, 0),
) -> list[tuple[Animals, int]]:
    """Return all Pareto-optimal achievable animal configurations after gaining animals.

    Respects both inventory bounds (cannot exceed current + gained) and farm
    capacity (must be physically accommodatable). Animals may be discarded.

    rates: (sheep_rate, boar_rate, cattle_rate) for animal-to-food conversion.
    Food is computed deterministically from the frontier point and rates; it does
    not affect which configurations are Pareto-optimal (frontier is over animal
    counts only).

    A typed card slot (Dolly's Mother's sheep slot; the 2026-07-21 per-species
    holders — Wildlife Reserve, Cattle Farm, Mud Patch, Sheep Agent) is
    applied here via the greedy strip: compute the standard frontier with the
    parked animals removed, then add them back to every point
    (`_typed_slot_strip` — exact by dominance, per type independently; the
    food values carry over unchanged because cooked counts are differences).
    The strip changes the ARGUMENTS of the memoized internals, so every cache
    keys honestly — no staleness.

    Returns list of (Animals, food_gained) tuples.
    """
    strip, player_state, gained = _typed_slot_strip(player_state, gained)
    if strip != Animals():
        base = _pareto_frontier_dispatch(player_state, gained, rates)
        return [(fast_replace(a, sheep=a.sheep + strip.sheep,
                              boar=a.boar + strip.boar,
                              cattle=a.cattle + strip.cattle), food)
                for a, food in base]
    return _pareto_frontier_dispatch(player_state, gained, rates)


def _pareto_frontier_dispatch(
    player_state: PlayerState,
    gained: Animals,
    rates: tuple[int, int, int],
) -> list[tuple[Animals, int]]:
    """The standard (slot-strip-free) frontier: the opt path or the readable
    level-0 oracle below."""
    if opt_config.PARETO_OPT_LEVEL >= 1:
        return _pareto_frontier_opt(player_state, gained, rates)

    pasture_capacities, num_flexible = extract_slots(player_state)

    s_available = player_state.animals.sheep  + gained.sheep
    b_available = player_state.animals.boar   + gained.boar
    c_available = player_state.animals.cattle + gained.cattle

    feasible = [
        Animals(sheep=s, boar=b, cattle=c)
        for s in range(s_available + 1)
        for b in range(b_available + 1)
        for c in range(c_available + 1)
        if can_accommodate(pasture_capacities, num_flexible, s, b, c)
    ]

    def dominates(a: Animals, b: Animals) -> bool:
        """True if a is at least as good as b in every component and strictly better in one."""
        return (
            a.sheep >= b.sheep and a.boar >= b.boar and a.cattle >= b.cattle
            and a != b
        )

    sR, bR, cR = rates
    frontier = []
    for candidate in feasible:
        if not any(dominates(other, candidate) for other in feasible):
            food = (
                (s_available - candidate.sheep)  * sR
                + (b_available - candidate.boar)   * bR
                + (c_available - candidate.cattle) * cR
            )
            frontier.append((candidate, food))

    return frontier


def feeding_requirement(state, idx: int) -> int:
    """The food player `idx` owes at this harvest's feeding — THE chokepoint.

    Base rule (RULES.md Feeding Phase): 2 food per adult, 1 per newborn,
    expressed as ``2*people_total − newborns``. Cards that change what feeding
    costs (Child's Toy's "your newborns require 2 food"; Old Miser [4]) fold
    in here via ``register_feeding_requirement`` (agricola/cards/
    harvest_windows.py) — owned folds apply in registration order, and the
    result is floored at 0.

    Cache safety: the folded requirement flows into the memoized
    ``harvest_feed_frontier`` as its ``food_owed`` ARGUMENT — part of the
    projection key — so a card-dependent requirement can never serve a stale
    frontier (the FRONTIER_OPT_DESIGN hidden-input footgun does not arise).
    Family fast path: the fold registry is empty; this is the bare formula.
    """
    from agricola.cards.harvest_windows import FEEDING_REQUIREMENT_FOLDS

    p = state.players[idx]
    need = 2 * p.people_total - p.newborns
    if FEEDING_REQUIREMENT_FOLDS:
        for card_id, fold in FEEDING_REQUIREMENT_FOLDS.items():
            if (card_id in p.occupations
                    or card_id in p.minor_improvements):
                need = fold(state, idx, need)
    return max(0, need)


def breeding_food_gained(
    pre: Animals,
    post: Animals,
    rates: tuple[int, int, int] = (0, 0, 0),
    sheep_min: int = 2,
) -> int:
    """Food generated by reaching `post` animal counts from `pre` during breeding.

    The breeding food formula, factored out so it has a single source of truth
    shared by `breeding_frontier` (which tabulates it across every frontier
    point) and `_execute_breed` (which applies it to the one chosen point).

    `pre`   = pre-breeding animal counts (the player's animals at breed time).
    `post`  = chosen post-breeding animal counts (a `breeding_frontier` point).
    `rates` = (sheep_rate, boar_rate, cattle_rate) animal-to-food conversion.
    `sheep_min` = how many sheep breeding requires (2 by the rule; 1 with an
    owned single-parent card — Dolly's Mother, ruled 2026-07-06).

    Per type with parent threshold m (m = 2 for boar/cattle always): the player
    cooks pre-breed down to r; breeding fires iff r >= m (and the newborn is
    placeable — the frontier's capacity test), giving post = r + 1 >= m + 1.
    So: if (pre >= m and post >= m + 1), the removals = (pre + 1 - post), all
    converted to food; otherwise breeding did not fire and removals =
    (pre - post). The `post >= m + 1` test is the exact fired-and-kept
    indicator — see the `breeding_frontier` docstring and
    ENGINE_IMPLEMENTATION.md (§4 Harvest) for the m = 2 derivation, which
    generalizes verbatim.
    """
    s, b, c = pre.sheep, pre.boar, pre.cattle
    sF, bF, cF = post.sheep, post.boar, post.cattle
    sR, bR, cR = rates
    m = sheep_min
    food_s = (s + 1 - sF) * sR if (s >= m and sF >= m + 1) else (s - sF) * sR
    food_b = (b + 1 - bF) * bR if (b >= 2 and bF >= 3) else (b - bF) * bR
    food_c = (c + 1 - cF) * cR if (c >= 2 and cF >= 3) else (c - cF) * cR
    return food_s + food_b + food_c


def breeding_frontier(
    player_state: PlayerState,
    rates: tuple[int, int, int] = (0, 0, 0),
) -> list[tuple[Animals, int]]:
    """Return all Pareto-optimal (final animals, food generated) outcomes for
    the breeding phase.

    The player may cook/release animals before breeding fires. After breeding
    there is no further cooking step. Breeding adds 1 animal of each type that
    has >= 2 animals (>= 1 sheep with an owned single-parent card — Dolly's
    Mother, ruled 2026-07-06), if farm capacity allows.

    Card modifiers are read off `player_state` HERE and threaded as plain
    ARGUMENTS into the memoized internals (so every cache keys honestly):
    `sheep_min` shifts the sheep parent threshold; typed card slots (Dolly's
    Mother's sheep slot, the 2026-07-21 per-species holders) relax the
    capacity test by the greedy strip — a post-config (sF, bF, cF) must fit
    with the parked animals on their cards, i.e.
    `can_accommodate(max(0, sF - slots.sheep), max(0, bF - slots.boar),
    max(0, cF - slots.cattle))`.

    Algorithm:
    1. Compute desired post-breed upper bounds (n+1 for each type at/over its
       parent threshold).
    2. Enumerate all (sF, bF, cF) within those bounds that fit (strip-aware).
    3. Keep only Pareto-optimal configurations (over animal counts).
    4. Compute food for each via `breeding_food_gained` (the shared formula).
    """
    from agricola.cards.capacity_mods import sheep_min_parents, typed_slot_counts

    sheep_min = sheep_min_parents(player_state)
    slots = typed_slot_counts(player_state)

    if opt_config.PARETO_OPT_LEVEL >= 1:
        return _breeding_frontier_opt(player_state, rates, sheep_min, slots)

    s = player_state.animals.sheep
    b = player_state.animals.boar
    c = player_state.animals.cattle

    s_desired = s + 1 if s >= sheep_min else s
    b_desired = b + 1 if b >= 2 else b
    c_desired = c + 1 if c >= 2 else c

    pasture_capacities, num_flexible = extract_slots(player_state)

    feasible = [
        Animals(sheep=sF, boar=bF, cattle=cF)
        for sF in range(s_desired + 1)
        for bF in range(b_desired + 1)
        for cF in range(c_desired + 1)
        if can_accommodate(pasture_capacities, num_flexible,
                           max(0, sF - slots.sheep),
                           max(0, bF - slots.boar),
                           max(0, cF - slots.cattle))
    ]

    def dominates(a: Animals, b_: Animals) -> bool:
        return (
            a.sheep >= b_.sheep and a.boar >= b_.boar and a.cattle >= b_.cattle
            and a != b_
        )

    pre = player_state.animals
    frontier = []
    for candidate in feasible:
        if not any(dominates(other, candidate) for other in feasible):
            frontier.append((candidate,
                             breeding_food_gained(pre, candidate, rates,
                                                  sheep_min)))

    return frontier


# ---------------------------------------------------------------------------
# Part 4: Food-payment frontiers (Task 7)
# ---------------------------------------------------------------------------
#
# NOTE: these may move to a dedicated `harvest.py` (or `food.py`) if harvest
# grows enough auxiliary helpers to warrant its own module. Today they live
# here alongside the other Pareto-frontier helpers.

def food_payment_frontier(
    player_state: PlayerState,
    food_owed: int,
    rates: tuple[int, int, int, int],
    span_converters: tuple = (),
    animal_floors: tuple = (0, 0, 0),
) -> list:
    """Return Pareto-optimal (grain_rem, veg_rem, sheep_rem, boar_rem, cattle_rem)
    tuples for FULLY paying ``food_owed`` food via crop/animal conversion.

    "rem" = REMAINING goods after the conversion (matches the
    breeding_frontier / pareto_frontier convention; CommitConvert in
    actions.py uses CONSUMED amounts, which the caller derives by subtraction).

    rates: (sheep_rate, boar_rate, cattle_rate, veg_rate). Grain is always
    1:1 (no rate). Pass the full 4-tuple from cooking_rates(state, player_idx).

    Pareto dimensions are the 5 remaining-goods counts. Food surplus is NOT
    a Pareto dim — see ENGINE_IMPLEMENTATION.md §4.2 (the optionality-bundling
    rule), specifically the "Pareto dominance over upstream goods only"
    prescription. An over-converted config like (consume 3 grain) for
    food_owed=2 is dominated by (consume 2 grain) on (grain_rem); the +1
    surplus food contributes no Pareto value.

    Per-good consumption caps:
      grain  consumed: 0..min(player.grain,  food_owed)                # rate=1
      veg    consumed: 0..min(player.veg,    ceil(food_owed/vR))
      sheep  consumed: 0..min(player.sheep,  ceil(food_owed/sR))       if sR > 0 else 0
      boar   consumed: 0..min(player.boar,   ceil(food_owed/bR))       if bR > 0 else 0
      cattle consumed: 0..min(player.cattle, ceil(food_owed/cR))       if cR > 0 else 0
    Each cap is the max useful consumption — converting more is always
    Pareto-dominated by converting one less.

    food_owed == 0 short-circuits: returns [(player.grain, player.veg,
    player.sheep, player.boar, player.cattle)] — no-conversion is the only
    Pareto-optimal config when no payment is needed.

    For food_owed > 0 with insufficient player capacity
    (max food_produced < food_owed), returns []. Callers requiring a
    non-empty frontier (future card payment actions) should pre-check
    feasibility. The harvest feeding path uses harvest_feed_frontier below,
    which always has at least the (all-goods-remaining, begging=food_owed)
    entry.

    THE CONVERTER-CLUSTER EXTENSIONS (rulings 34/37/39, 2026-07-12 — the
    generalized in-harvest raise frame; CARD_DEFERRED_PLANS.md):

    **`animal_floors` (ruling 39's stateless post-breed cooking floor)** —
    (sheep_F, boar_F, cattle_F): a type currently AT OR ABOVE its floor may
    not be cooked below it (consumable = count − F when count >= F, else
    count — the parents+offspring protection in shorthand form). Applied by
    CLIPPING the animal supplies the core enumeration sees and translating
    the protected amounts back onto every result — a uniform per-dimension
    +const, so dominance and order are preserved exactly and the cached core
    (`_food_payment_points`) is untouched: no new cache key, no cache hazard.
    The default (0, 0, 0) clips nothing (every pre-existing caller).

    **`span_converters` (rulings 34/37 — pure building-resource converters
    in the raise frame)** — a tuple of (conversion_id, (wood, clay, reed,
    stone) input, food_out) for each once-per-harvest BINARY converter
    currently available to the player (owned + in-span + budget-unused —
    the CALLER derives this from state; the budget is shared with the
    feed-phase craft seam via `harvest_conversions_used`). Non-empty input
    CHANGES THE RETURN SHAPE: each element becomes
    ``((g, v, s, b, c, wood_rem, clay_rem, reed_rem, stone_rem), fired)``
    with `fired` a sorted tuple of the conversion_ids this config fires —
    the Pareto space gains the four building-resource remaining dims (fired
    is NOT a dim; on an exact 9-dim tie the SMALLER fired set wins — fewer
    burned once-per-harvest budgets dominates). Subsets are enumerated
    OUTSIDE the cached core (each subset's food offsets the owed amount and
    its inputs debit the building supplies). With ``food_owed == 0`` no
    fires are offered — deferring a budget preserves optionality, the span
    continues (Foundations' preserving-optionality rule).
    """
    sp_, bp_, cp_ = (
        animal_floors[0] if player_state.animals.sheep >= animal_floors[0] else 0,
        animal_floors[1] if player_state.animals.boar >= animal_floors[1] else 0,
        animal_floors[2] if player_state.animals.cattle >= animal_floors[2] else 0,
    )
    if sp_ or bp_ or cp_ or span_converters:
        return _food_payment_generalized(
            player_state, food_owed, rates, span_converters, (sp_, bp_, cp_))

    if opt_config.PARETO_OPT_LEVEL >= 1:
        return _food_payment_frontier_opt(player_state, food_owed, rates)

    sR, bR, cR, vR = rates
    grain_max  = player_state.resources.grain
    veg_max    = player_state.resources.veg
    sheep_max  = player_state.animals.sheep
    boar_max   = player_state.animals.boar
    cattle_max = player_state.animals.cattle

    if food_owed == 0:
        return [(grain_max, veg_max, sheep_max, boar_max, cattle_max)]

    # Per-good consumption caps.
    grain_cap  = min(grain_max,  food_owed)
    veg_cap    = min(veg_max,    math.ceil(food_owed / vR)) if vR > 0 else 0
    sheep_cap  = min(sheep_max,  math.ceil(food_owed / sR)) if sR > 0 else 0
    boar_cap   = min(boar_max,   math.ceil(food_owed / bR)) if bR > 0 else 0
    cattle_cap = min(cattle_max, math.ceil(food_owed / cR)) if cR > 0 else 0

    candidates: list[tuple[int, int, int, int, int]] = []
    for g in range(grain_cap + 1):
        for v in range(veg_cap + 1):
            for s in range(sheep_cap + 1):
                for b in range(boar_cap + 1):
                    for c in range(cattle_cap + 1):
                        food_produced = g + v * vR + s * sR + b * bR + c * cR
                        if food_produced < food_owed:
                            continue
                        candidates.append((
                            grain_max  - g,
                            veg_max    - v,
                            sheep_max  - s,
                            boar_max   - b,
                            cattle_max - c,
                        ))

    # Pareto-filter on the 5-dim remaining-goods vector. NO food_surplus dim.
    def dominates(a, b):
        return all(ax >= bx for ax, bx in zip(a, b)) and any(ax > bx for ax, bx in zip(a, b))

    frontier: list[tuple[int, int, int, int, int]] = []
    for i, tup in enumerate(candidates):
        if not any(dominates(candidates[j], tup) for j in range(len(candidates)) if j != i):
            frontier.append(tup)

    return frontier


def _food_payment_counts(g, v, s, b, c, food_owed, rates) -> list:
    """The crop/animal payment frontier over EXPLICIT counts — the shared core
    the generalized path calls per converter subset. Dispatches to the cached
    rate-descending enumeration (opt level >= 1) or a brute baseline identical
    to `food_payment_frontier`'s (cross-level-tested there)."""
    if food_owed == 0:
        return [(g, v, s, b, c)]
    if opt_config.PARETO_OPT_LEVEL >= 1:
        return _food_payment_points(g, v, s, b, c, food_owed, rates)
    sR, bR, cR, vR = rates
    caps = (
        min(g, food_owed),
        min(v, math.ceil(food_owed / vR)) if vR > 0 else 0,
        min(s, math.ceil(food_owed / sR)) if sR > 0 else 0,
        min(b, math.ceil(food_owed / bR)) if bR > 0 else 0,
        min(c, math.ceil(food_owed / cR)) if cR > 0 else 0,
    )
    maxes = (g, v, s, b, c)
    candidates = []
    for cg in range(caps[0] + 1):
        for cv in range(caps[1] + 1):
            for cs in range(caps[2] + 1):
                for cb in range(caps[3] + 1):
                    for cc in range(caps[4] + 1):
                        if cg + cv * vR + cs * sR + cb * bR + cc * cR < food_owed:
                            continue
                        candidates.append(tuple(
                            m - x for m, x in zip(maxes, (cg, cv, cs, cb, cc))))

    def _dom(a, b2):
        return (all(ax >= bx for ax, bx in zip(a, b2))
                and any(ax > bx for ax, bx in zip(a, b2)))

    return [t for i, t in enumerate(candidates)
            if not any(_dom(candidates[j], t)
                       for j in range(len(candidates)) if j != i)]


def _food_payment_generalized(
    player_state, food_owed, rates, span_converters, protected,
) -> list:
    """The generalized raise-frame frontier (rulings 34/37/39, 2026-07-12) —
    see `food_payment_frontier`'s docstring for the full contract. `protected`
    is the already-clipped (sheep, boar, cattle) floor amounts (0 where the
    floor doesn't bind). Enumerates converter SUBSETS around the crop/animal
    core; the core sees floor-clipped animal supplies and the protected
    amounts translate back onto every result (a uniform +const per dimension:
    dominance-order preserving, so the Pareto pass here is exact)."""
    r = player_state.resources
    a = player_state.animals
    sp_, bp_, cp_ = protected
    g, v = r.grain, r.veg
    s2, b2, c2 = a.sheep - sp_, a.boar - bp_, a.cattle - cp_

    if not span_converters:
        # Floors only: legacy 5-tuple shape, translated back.
        return [(rg, rv, rs + sp_, rb + bp_, rc + cp_)
                for (rg, rv, rs, rb, rc)
                in _food_payment_counts(g, v, s2, b2, c2, food_owed, rates)]

    build = (r.wood, r.clay, r.reed, r.stone)
    best: dict = {}   # 9-dim remaining vector -> fired ids (smaller set wins)
    n = len(span_converters)
    for mask in range(1 << n):
        chosen = [span_converters[i] for i in range(n) if mask & (1 << i)]
        if chosen and food_owed == 0:
            continue   # no fires at owe 0 — deferring preserves optionality
        need = [0, 0, 0, 0]
        food_s = 0
        for _cid, inp, out in chosen:
            for k in range(4):
                need[k] += inp[k]
            food_s += out
        if any(need[k] > build[k] for k in range(4)):
            continue
        build_rem = tuple(build[k] - need[k] for k in range(4))
        fired = tuple(sorted(cid for cid, _inp, _out in chosen))
        owe2 = max(0, food_owed - food_s)
        for (rg, rv, rs, rb, rc) in _food_payment_counts(
                g, v, s2, b2, c2, owe2, rates):
            vec = (rg, rv, rs + sp_, rb + bp_, rc + cp_) + build_rem
            old = best.get(vec)
            if old is None or len(fired) < len(old) or (
                    len(fired) == len(old) and fired < old):
                best[vec] = fired

    def _dom(x, y):
        return (all(ax >= bx for ax, bx in zip(x, y))
                and any(ax > bx for ax, bx in zip(x, y)))

    vecs = list(best)
    frontier = [
        (vec, best[vec]) for i, vec in enumerate(vecs)
        if not any(_dom(vecs[j], vec) for j in range(len(vecs)) if j != i)
    ]
    return sorted(frontier)


def harvest_feed_frontier(
    player_state: PlayerState,
    food_owed: int,
    rates: tuple[int, int, int, int],
) -> list[tuple[tuple[int, int, int, int, int], int]]:
    """Return Pareto-optimal ((grain_rem, veg_rem, sheep_rem, boar_rem,
    cattle_rem), begging) pairs for paying as much of ``food_owed`` as the
    player chooses, begging the rest.

    "rem" = REMAINING goods (matches breeding_frontier / food_payment_frontier).

    Implementation: for each paid level in [0, food_owed], call
    food_payment_frontier with that paid amount. For each returned config,
    compute the actual food it generates from the remaining tuple. Admit the
    config to the candidate set ONLY at the paid level matching its natural
    fit — ``paid == min(food_generated, food_owed)``. This admits each
    config exactly once, with begging = food_owed - paid equal to its
    actual begging.

    The natural-fit filter prevents the "ghost begging" problem: a config
    producing F food qualifies for food_payment_frontier(paid=k) for every
    k <= F (capped at food_owed). Without the filter, the candidate set
    would hold up to F+1 copies of the same config, all but one with
    begging values that don't match the actual food generated. The filter
    keeps exactly the one entry whose ``paid`` matches reality.

    The downstream 6-dim Pareto-filter on (5 goods, -begging) would also
    prune the ghosts (each ghost is dominated by the natural-fit entry on
    the -begging dim), but the natural-fit filter is a noticeably faster
    pre-filter that reduces the input size to the O(n^2) Pareto pass.

    Pareto dimensions: the 5 remaining-goods counts AND -begging
    (fewer-is-better polarity). Food surplus is NOT a Pareto dim — see
    ENGINE_IMPLEMENTATION.md §4.2 -> Pareto dominance over upstream
    goods. Begging IS included as a Pareto dim because it represents a
    strategic cost the player has a genuine choice to incur — pay food and
    avoid the marker, or preserve goods and take the scoring penalty.

    food_owed == 0 short-circuits: returns
    [((player.grain, player.veg, player.sheep, player.boar, player.cattle), 0)].

    Frontier is always non-empty for food_owed > 0: the all-remaining +
    begging=food_owed config (from paid=0, where it's the unique natural
    fit) is always a candidate and always on the frontier.
    """
    if opt_config.PARETO_OPT_LEVEL >= 1:
        return _harvest_feed_frontier_opt(player_state, food_owed, rates)

    sR, bR, cR, vR = rates
    grain_max  = player_state.resources.grain
    veg_max    = player_state.resources.veg
    sheep_max  = player_state.animals.sheep
    boar_max   = player_state.animals.boar
    cattle_max = player_state.animals.cattle

    if food_owed == 0:
        return [((grain_max, veg_max, sheep_max, boar_max, cattle_max), 0)]

    # Aggregate candidates from each paid level, admitting each config at the
    # paid level matching its natural fit (= min(food_generated, food_owed)).
    candidates: list[tuple[tuple[int, int, int, int, int], int]] = []
    for paid in range(food_owed + 1):
        for remaining in food_payment_frontier(player_state, paid, rates):
            food_generated = (
                (grain_max  - remaining[0])
                + (veg_max    - remaining[1]) * vR
                + (sheep_max  - remaining[2]) * sR
                + (boar_max   - remaining[3]) * bR
                + (cattle_max - remaining[4]) * cR
            )
            if paid == min(food_generated, food_owed):
                candidates.append((remaining, food_owed - paid))

    # Pareto-filter on (grain_rem, veg_rem, sheep_rem, boar_rem, cattle_rem, -begging).
    def end_state(cand):
        remaining, beg = cand
        return (*remaining, -beg)

    def dominates(a, b):
        return all(ax >= bx for ax, bx in zip(a, b)) and any(ax > bx for ax, bx in zip(a, b))

    end_states = [end_state(cand) for cand in candidates]
    frontier: list[tuple[tuple[int, int, int, int, int], int]] = []
    for i, cand in enumerate(candidates):
        if not any(
            dominates(end_states[j], end_states[i])
            for j in range(len(candidates)) if j != i
        ):
            frontier.append(cand)

    return frontier


# ---------------------------------------------------------------------------
# Part 5: Optimization paths (FRONTIER_OPT_DESIGN.md)
# ---------------------------------------------------------------------------
#
# Active only when opt_config.PARETO_OPT_LEVEL >= 1. Level 0 (the default) never
# reaches this code — the public helpers above run their baseline bodies
# untouched. Every function here is set-identical to the corresponding baseline
# (validated across all levels by tests/test_frontier_opt.py) and additionally
# returns a canonically-sorted list, so levels 1-3 are mutually list-identical.
#
# Phase 1 implements the Level-1 algorithmic fast paths (max-corner for the
# animal frontiers; rate-descending enumeration for food payment) plus the
# canonical sort. The Level-2/3 caches layer on top in later phases.


def _pareto_max_3d(points) -> tuple:
    """Pareto-maximal subset of an iterable of (s, b, c) tuples, sorted.

    "Maximal" = not componentwise-dominated by another point. Returns a sorted
    tuple (lexicographic on (sheep, boar, cattle)) — the canonical order.
    """
    pts = list(points)
    out = [
        p for p in pts
        if not any(
            o != p and o[0] >= p[0] and o[1] >= p[1] and o[2] >= p[2]
            for o in pts
        )
    ]
    return tuple(sorted(out))


def _animal_frontier_points(
    caps_tuple: tuple, num_flexible: int, s_cap: int, b_cap: int, c_cap: int,
) -> tuple:
    """Rate-free Pareto frontier of feasible (s, b, c) with each <= its cap,
    canonically sorted. Shared by pareto / breeding (same can_accommodate).

    Dispatches on the opt level: level >= 2 routes through the exact projection
    cache (these args ARE the key); level 1 calls the generator directly. The
    Level-3 Phi path is wired inside `_animal_points_cached`.
    """
    if opt_config.PARETO_OPT_LEVEL >= 2:
        return _animal_points_cached(caps_tuple, num_flexible, s_cap, b_cap, c_cap)
    return _animal_points_l1gen(caps_tuple, num_flexible, s_cap, b_cap, c_cap)


@functools.lru_cache(maxsize=100_000)
def _animal_points_cached(caps_tuple, num_flexible, s_cap, b_cap, c_cap):
    """Exact projection cache (Level 2). The result is level-invariant (the same
    set/sorted list at every level), so an entry computed under one level is
    valid under another; the conftest fixture clears it between tests. Phase 3
    branches to the Phi path here on a miss when PARETO_OPT_LEVEL >= 3.
    """
    if opt_config.PARETO_OPT_LEVEL >= 3:
        phi = _phi_cached(caps_tuple, num_flexible)
        return _frontier_from_phi(phi, s_cap, b_cap, c_cap)
    return _animal_points_l1gen(caps_tuple, num_flexible, s_cap, b_cap, c_cap)


def _animal_points_l1gen(caps_tuple, num_flexible, s_cap, b_cap, c_cap):
    """Level-1 generator: max-corner fast path + brute feasible-set + 3-D Pareto
    filter (same can_accommodate as the baseline, so set-identical). Returns a
    canonically-sorted tuple of (s, b, c).

    Max-corner: if keeping everything is accommodatable it dominates every other
    config (food is not a Pareto dim), so the frontier is the singleton {caps}.
    """
    pasture_capacities = list(caps_tuple)
    if can_accommodate(pasture_capacities, num_flexible, s_cap, b_cap, c_cap):
        return ((s_cap, b_cap, c_cap),)
    feasible = [
        (s, b, c)
        for s in range(s_cap + 1)
        for b in range(b_cap + 1)
        for c in range(c_cap + 1)
        if can_accommodate(pasture_capacities, num_flexible, s, b, c)
    ]
    return _pareto_max_3d(feasible)


@functools.lru_cache(maxsize=20_000)
def _phi_cached(caps_tuple, num_flexible):
    return _build_phi(caps_tuple, num_flexible)


def _build_phi(caps_tuple, num_flexible):
    """Phi(farm) = Pareto-max of the feasible animal set for this farm shape,
    independent of animal caps (Level 3, FRONTIER_OPT_DESIGN.md §6.2).

    Naive build: a triangular box sweep (s+b+c <= max single-type capacity)
    filtered by the SAME `can_accommodate` oracle as the baseline — so Phi is
    guaranteed to match, with no separate correctness surface. The structured
    grouped build (§6.2) is a deferred speed refinement; this is one-time per
    farm shape and then reused across every animal-cap query.
    """
    pasture_capacities = list(caps_tuple)
    ub = sum(caps_tuple) + num_flexible       # max animals of a single type
    feasible = [
        (s, b, c)
        for s in range(ub + 1)
        for b in range(ub + 1 - s)            # total can't exceed ub
        for c in range(ub + 1 - s - b)
        if can_accommodate(pasture_capacities, num_flexible, s, b, c)
    ]
    return _pareto_max_3d(feasible)


def _frontier_from_phi(phi, s_cap, b_cap, c_cap):
    """Per-call frontier from cached Phi (§6.2/§6.3): max-corner short-circuit,
    else clip Phi to the caps and re-Pareto. Returns a canonically-sorted tuple.

    Correctness: `can_accommodate` is downward-closed, so the clipped Phi
    generates exactly the query frontier (§6.3 lemma). Clipping is a `min`
    projection that can create dominations, so the re-Pareto is mandatory.
    """
    if any(p[0] >= s_cap and p[1] >= b_cap and p[2] >= c_cap for p in phi):
        return ((s_cap, b_cap, c_cap),)
    clipped = {
        (min(p[0], s_cap), min(p[1], b_cap), min(p[2], c_cap)) for p in phi
    }
    return _pareto_max_3d(clipped)


def _pareto_frontier_opt(player_state, gained, rates):
    pasture_capacities, num_flexible = extract_slots(player_state)
    s_av = player_state.animals.sheep + gained.sheep
    b_av = player_state.animals.boar + gained.boar
    c_av = player_state.animals.cattle + gained.cattle
    sR, bR, cR = rates
    pts = _animal_frontier_points(
        tuple(sorted(pasture_capacities)), num_flexible, s_av, b_av, c_av,
    )
    return [
        (Animals(sheep=s, boar=b, cattle=c),
         (s_av - s) * sR + (b_av - b) * bR + (c_av - c) * cR)
        for (s, b, c) in pts
    ]


def _breeding_frontier_opt(player_state, rates, sheep_min=2, typed_slots=None):
    s = player_state.animals.sheep
    b = player_state.animals.boar
    c = player_state.animals.cattle
    s_des = s + 1 if s >= sheep_min else s
    b_des = b + 1 if b >= 2 else b
    c_des = c + 1 if c >= 2 else c
    pasture_capacities, num_flexible = extract_slots(player_state)
    # Typed card slots ride the greedy strip: the frontier over strip-aware
    # feasibility (`fits(max(0, sF - strip_s), ...)` per type) equals the
    # standard frontier computed with each type's bound reduced by its strip,
    # every point then shifted back up — exact because each type's feasible
    # range is downward-closed and the shifted point dominates its unshifted
    # sibling (the `_typed_slot_strip` dominance argument, per type
    # independently). The reduced bounds change the memo key, so the cache
    # stays honest.
    slots = typed_slots if typed_slots is not None else Animals()
    strip_s = min(slots.sheep, s_des)
    strip_b = min(slots.boar, b_des)
    strip_c = min(slots.cattle, c_des)
    pts = _animal_frontier_points(
        tuple(sorted(pasture_capacities)), num_flexible,
        s_des - strip_s, b_des - strip_b, c_des - strip_c,
    )
    pre = player_state.animals
    return [
        (Animals(sheep=ss + strip_s, boar=bb + strip_b, cattle=cc + strip_c),
         breeding_food_gained(
             pre, Animals(sheep=ss + strip_s, boar=bb + strip_b,
                          cattle=cc + strip_c),
             rates, sheep_min))
        for (ss, bb, cc) in pts
    ]


def _food_payment_points(
    grain_max, veg_max, sheep_max, boar_max, cattle_max, food_owed, rates,
) -> list:
    """Rate-descending nested enumeration → the FULL-payment Pareto frontier as
    a sorted list of remaining 5-tuples, with NO post-Pareto filter.

    Goods are ordered by conversion rate descending (grain is rate 1; rate-0
    goods are excluded — they can never reduce begging). Proven sound + complete
    in FRONTIER_OPT_DESIGN.md Appendix A.
    """
    sR, bR, cR, vR = rates
    maxes = (grain_max, veg_max, sheep_max, boar_max, cattle_max)
    # (5-tuple index, rate, supply); grain is rate 1.
    goods = [
        (0, 1, grain_max), (1, vR, veg_max), (2, sR, sheep_max),
        (3, bR, boar_max), (4, cR, cattle_max),
    ]
    active = sorted((g for g in goods if g[1] > 0), key=lambda g: -g[1])
    consumed = [0, 0, 0, 0, 0]
    out: list = []

    def emit(i: int, remaining: int) -> None:
        if i == len(active):
            if remaining <= 0:
                out.append(tuple(maxes[k] - consumed[k] for k in range(5)))
            return
        idx, rate, supply = active[i]
        upper = min(supply, math.ceil(max(0, remaining) / rate))
        for x in range(upper + 1):
            consumed[idx] = x
            emit(i + 1, remaining - x * rate)
        consumed[idx] = 0

    emit(0, food_owed)
    return sorted(out)


def _food_payment_frontier_opt(player_state, food_owed, rates):
    grain_max = player_state.resources.grain
    veg_max = player_state.resources.veg
    sheep_max = player_state.animals.sheep
    boar_max = player_state.animals.boar
    cattle_max = player_state.animals.cattle
    if food_owed == 0:
        return [(grain_max, veg_max, sheep_max, boar_max, cattle_max)]
    return _food_payment_points(
        grain_max, veg_max, sheep_max, boar_max, cattle_max, food_owed, rates,
    )


def _harvest_feed_frontier_opt(player_state, food_owed, rates):
    grain = player_state.resources.grain
    veg = player_state.resources.veg
    sheep = player_state.animals.sheep
    boar = player_state.animals.boar
    cattle = player_state.animals.cattle
    if opt_config.PARETO_OPT_LEVEL >= 2:
        return _harvest_feed_clipped(grain, veg, sheep, boar, cattle, food_owed, rates)
    return _harvest_feed_compute(grain, veg, sheep, boar, cattle, food_owed, rates)


def _harvest_feed_compute(grain, veg, sheep, boar, cattle, food_owed, rates):
    """harvest_feed frontier over EXPLICIT supplies; canonically sorted.

    Wraps the rate-descending food_payment over each paid level + the natural-fit
    filter + the 6-D Pareto pass (5 goods + -begging) — the same algorithm as the
    baseline, so the returned SET is identical.
    """
    sR, bR, cR, vR = rates
    if food_owed == 0:
        return [((grain, veg, sheep, boar, cattle), 0)]

    candidates: list = []
    for paid in range(food_owed + 1):
        for remaining in _food_payment_points(grain, veg, sheep, boar, cattle, paid, rates):
            food_generated = (
                (grain - remaining[0])
                + (veg - remaining[1]) * vR
                + (sheep - remaining[2]) * sR
                + (boar - remaining[3]) * bR
                + (cattle - remaining[4]) * cR
            )
            if paid == min(food_generated, food_owed):
                candidates.append((remaining, food_owed - paid))

    def _dom(a, b):
        return all(ax >= bx for ax, bx in zip(a, b)) and any(ax > bx for ax, bx in zip(a, b))

    end = [(*rem, -beg) for (rem, beg) in candidates]
    frontier = [
        candidates[i] for i in range(len(candidates))
        if not any(_dom(end[j], end[i]) for j in range(len(candidates)) if j != i)
    ]
    return sorted(frontier)


def _feed_caps(grain, veg, sheep, boar, cattle, food_owed, rates):
    """Per-good 'max useful consumption' caps (§6.5): no good is consumed beyond
    min(supply, ceil(food_owed / rate)). These are exactly the caps the baseline
    food_payment_frontier already computes.
    """
    sR, bR, cR, vR = rates
    return (
        min(grain,  food_owed),
        min(veg,    math.ceil(food_owed / vR)) if vR > 0 else 0,
        min(sheep,  math.ceil(food_owed / sR)) if sR > 0 else 0,
        min(boar,   math.ceil(food_owed / bR)) if bR > 0 else 0,
        min(cattle, math.ceil(food_owed / cR)) if cR > 0 else 0,
    )


def _harvest_feed_clipped(grain, veg, sheep, boar, cattle, food_owed, rates):
    """Level-2 feeding cache (§6.5): key on the CLIPPED supplies (collapses
    strategically-dead excess goods → higher hit rate), then reconstruct by a
    uniform +excess translation. The translation preserves both feasibility and
    lexicographic order, so NO re-Pareto is needed and the sorted output matches
    the level-1 result exactly.
    """
    if food_owed == 0:
        return [((grain, veg, sheep, boar, cattle), 0)]
    cg, cv, cs, cb, cc = _feed_caps(grain, veg, sheep, boar, cattle, food_owed, rates)
    ex = (grain - cg, veg - cv, sheep - cs, boar - cb, cattle - cc)
    clipped = _harvest_feed_cached(cg, cv, cs, cb, cc, food_owed, rates)
    if ex == (0, 0, 0, 0, 0):
        return list(clipped)
    return [
        ((rem[0] + ex[0], rem[1] + ex[1], rem[2] + ex[2], rem[3] + ex[3], rem[4] + ex[4]), beg)
        for (rem, beg) in clipped
    ]


@functools.lru_cache(maxsize=100_000)
def _harvest_feed_cached(cg, cv, cs, cb, cc, food_owed, rates):
    # Cached over clipped supplies; tuple so the shared value is immutable.
    return tuple(_harvest_feed_compute(cg, cv, cs, cb, cc, food_owed, rates))


# ---------------------------------------------------------------------------
# The accumulation-space category (card wordings quantify over it)
# ---------------------------------------------------------------------------

def accumulation_spaces(state: GameState) -> frozenset:
    """The accumulation-space ids of THIS game — the set that card wordings like
    "accumulation space(s)" quantify over (Wood Pile, Hand Truck, Steam Machine,
    Curator).

    Mode-aware: in the CARD game Meeting Place gives no goods (become-SP + an
    optional minor), so it is not an accumulation space there (user ruling
    2026-07-02); in the FAMILY game it accumulates +1 food/round and IS one.
    This accessor is deliberately the ONE definition of the category: when the
    4-player board lands, its extra accumulation spaces (Grove, Hollow, Copse)
    join here — keyed on the game's player count — and every category reader
    updates at once. (The mechanical refill machinery iterates the rate dicts
    in `constants` directly and never this category.)
    """
    from agricola.constants import (
        ACCUMULATION_SPACES,
        ACCUMULATION_SPACES_FAMILY,
        GameMode,
    )
    return (ACCUMULATION_SPACES if state.mode is GameMode.CARDS
            else ACCUMULATION_SPACES_FAMILY)
