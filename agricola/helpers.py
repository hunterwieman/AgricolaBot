from __future__ import annotations

import math
from itertools import product as iproduct

from agricola.constants import CellType
from agricola.resources import Animals
from agricola.state import Farmyard, GameState, PlayerState


# ---------------------------------------------------------------------------
# Part 1: Simple derived quantities
# ---------------------------------------------------------------------------

def fences_in_supply(farmyard: Farmyard) -> int:
    """Count fence pieces not yet placed. Derived from fence arrays."""
    built = (
        sum(sum(row) for row in farmyard.horizontal_fences)
        + sum(sum(row) for row in farmyard.vertical_fences)
    )
    return 15 - built


def stables_in_supply(farmyard: Farmyard) -> int:
    """Count stables not yet built. Derived from grid."""
    built = sum(
        1 for r in range(3) for c in range(5)
        if farmyard.grid[r][c].cell_type == CellType.STABLE
    )
    return 4 - built


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
    """
    owners = state.board.major_improvement_owners
    has_hearth    = any(owners[i] == player_idx for i in (2, 3))
    has_fireplace = any(owners[i] == player_idx for i in (0, 1))

    if has_hearth:
        return (2, 3, 4, 3)
    elif has_fireplace:
        return (2, 2, 3, 2)
    else:
        return (0, 0, 0, 1)


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
    num_flexible_slots: standalone stables + 1 (house pet).
    """
    pastures = player_state.farmyard.pastures
    pasture_capacities = [p.capacity for p in pastures]

    total_stables_built = 4 - stables_in_supply(player_state.farmyard)
    stables_in_pastures = sum(p.num_stables for p in pastures)
    standalone_stables = total_stables_built - stables_in_pastures

    num_flexible = standalone_stables + 1  # +1 for house pet

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

    Returns list of (Animals, food_gained) tuples.
    """
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


def breeding_frontier(
    player_state: PlayerState,
    rates: tuple[int, int, int] = (0, 0, 0),
) -> list[tuple[Animals, int]]:
    """Return all Pareto-optimal (final animals, food generated) outcomes for
    the breeding phase.

    The player may cook/release animals before breeding fires. After breeding
    there is no further cooking step. Breeding adds 1 animal of each type that
    has >= 2 animals, if farm capacity allows.

    Algorithm:
    1. Compute desired post-breed upper bounds (n+1 for each type with n >= 2).
    2. Enumerate all (sF, bF, cF) within those bounds that can_accommodate.
    3. Keep only Pareto-optimal configurations (over animal counts).
    4. Compute food for each using the breeding food formula.
    """
    s = player_state.animals.sheep
    b = player_state.animals.boar
    c = player_state.animals.cattle

    s_desired = s + 1 if s >= 2 else s
    b_desired = b + 1 if b >= 2 else b
    c_desired = c + 1 if c >= 2 else c

    pasture_capacities, num_flexible = extract_slots(player_state)

    feasible = [
        Animals(sheep=sF, boar=bF, cattle=cF)
        for sF in range(s_desired + 1)
        for bF in range(b_desired + 1)
        for cF in range(c_desired + 1)
        if can_accommodate(pasture_capacities, num_flexible, sF, bF, cF)
    ]

    def dominates(a: Animals, b_: Animals) -> bool:
        return (
            a.sheep >= b_.sheep and a.boar >= b_.boar and a.cattle >= b_.cattle
            and a != b_
        )

    sR, bR, cR = rates

    frontier = []
    for candidate in feasible:
        if not any(dominates(other, candidate) for other in feasible):
            sF, bF, cF = candidate.sheep, candidate.boar, candidate.cattle
            # Food formula: if breeding fired for a type (n >= 2) and final >= 3,
            # the newborn was kept so pre-breed removals = (n+1 - fF), all giving food.
            # If final < 3 with n >= 2, breeding did not fire (player ate pre-breed
            # to prevent it or no capacity), removals = (n - fF), all giving food.
            # If n < 2, breeding impossible, removals = (n - fF), all giving food.
            food_s = (s + 1 - sF) * sR if (s >= 2 and sF >= 3) else (s - sF) * sR
            food_b = (b + 1 - bF) * bR if (b >= 2 and bF >= 3) else (b - bF) * bR
            food_c = (c + 1 - cF) * cR if (c >= 2 and cF >= 3) else (c - cF) * cR
            frontier.append((candidate, food_s + food_b + food_c))

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
) -> list[tuple[int, int, int, int, int]]:
    """Return Pareto-optimal (grain_rem, veg_rem, sheep_rem, boar_rem, cattle_rem)
    tuples for FULLY paying ``food_owed`` food via crop/animal conversion.

    "rem" = REMAINING goods after the conversion (matches the
    breeding_frontier / pareto_frontier convention; CommitConvert in
    actions.py uses CONSUMED amounts, which the caller derives by subtraction).

    rates: (sheep_rate, boar_rate, cattle_rate, veg_rate). Grain is always
    1:1 (no rate). Pass the full 4-tuple from cooking_rates(state, player_idx).

    Pareto dimensions are the 5 remaining-goods counts. Food surplus is NOT
    a Pareto dim — see CLAUDE.md "Preserving optionality" Key Design
    Principle, specifically the "Pareto dominance over upstream goods"
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
    """
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
    CLAUDE.md "Preserving optionality" -> Pareto dominance over upstream
    goods. Begging IS included as a Pareto dim because it represents a
    strategic cost the player has a genuine choice to incur — pay food and
    avoid the marker, or preserve goods and take the scoring penalty.

    food_owed == 0 short-circuits: returns
    [((player.grain, player.veg, player.sheep, player.boar, player.cattle), 0)].

    Frontier is always non-empty for food_owed > 0: the all-remaining +
    begging=food_owed config (from paid=0, where it's the unique natural
    fit) is always a candidate and always on the frontier.
    """
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
