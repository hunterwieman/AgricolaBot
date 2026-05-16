from __future__ import annotations

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


def cooking_rates(state: GameState, player_idx: int) -> tuple[int, int, int]:
    """Return (sheep_rate, boar_rate, cattle_rate) for animal-to-food conversion.

    Based on the best cooking improvement the player owns:
      Cooking Hearth (major idx 2 or 3) -> (2, 3, 4)
      Fireplace      (major idx 0 or 1) -> (2, 2, 3)
      Neither                           -> (0, 0, 0)

    If the player owns both a Fireplace and a Cooking Hearth, the Cooking
    Hearth rates apply (they are strictly better for every animal type).

    If rates are (0, 0, 0), the player has no cooking improvement. Excess
    animals are returned to the general supply; no food is generated.
    """
    owners = state.board.major_improvement_owners
    has_hearth    = any(owners[i] == player_idx for i in (2, 3))
    has_fireplace = any(owners[i] == player_idx for i in (0, 1))

    if has_hearth:
        return (2, 3, 4)
    elif has_fireplace:
        return (2, 2, 3)
    else:
        return (0, 0, 0)


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
