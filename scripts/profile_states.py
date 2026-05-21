"""Prefabricated GameState fixtures for engine profiling.

Nine states across early/mid/late game. Each factory composes existing
helpers from `tests.factories` and `agricola/setup.py`; nothing in
`agricola/` or `tests/` is modified.

Coverage requirement (per item C in POSSIBLE_NEXT_STEPS.md): the union of
states must make every action space legal in at least one state, except
`lessons` (permanently illegal in the Family game without occupation
cards). The `late_round_14_all_legal` state alone satisfies the bulk of
this requirement; the others provide variety across game positions.

Usage:
    from scripts.profile_states import STATES
    for name, state in STATES.items():
        ...
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

# Make `agricola` and `tests` importable when running this script directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agricola.constants import (
    BUILDING_ACCUMULATION_RATES,
    CellType,
    HouseMaterial,
)
from agricola.engine import step
from agricola.pasture import compute_pastures_from_arrays
from agricola.resources import Animals, Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import (
    add_resources,
    with_animals,
    with_current_player,
    with_fields,
    with_grid,
    with_house,
    with_majors,
    with_people,
    with_resources,
    with_round,
    with_space,
    with_sown_fields,
)


# ---------------------------------------------------------------------------
# Helpers local to this module
# ---------------------------------------------------------------------------

def _add_pasture(state, player_idx, cells, num_stables=0):
    """Add a pasture covering `cells` with the given number of stables.

    Sets the perimeter fences, optionally places stables on the named cells,
    and recomputes the pasture cache. `cells` is an iterable of (row, col).
    """
    p = state.players[player_idx]
    fy = p.farmyard

    cells_set = set(cells)
    hf = [list(row) for row in fy.horizontal_fences]
    vf = [list(row) for row in fy.vertical_fences]

    # Set perimeter fences: any edge between an in-cell and an out-cell.
    for (r, c) in cells_set:
        # Top edge
        if (r - 1, c) not in cells_set:
            hf[r][c] = True
        # Bottom edge
        if (r + 1, c) not in cells_set:
            hf[r + 1][c] = True
        # Left edge
        if (r, c - 1) not in cells_set:
            vf[r][c] = True
        # Right edge
        if (r, c + 1) not in cells_set:
            vf[r][c + 1] = True

    new_hf = tuple(tuple(row) for row in hf)
    new_vf = tuple(tuple(row) for row in vf)

    # Add stables on the requested number of cells (first N in iteration order).
    grid = [list(row) for row in fy.grid]
    sorted_cells = sorted(cells_set)
    for i, (r, c) in enumerate(sorted_cells):
        if i >= num_stables:
            break
        grid[r][c] = Cell(cell_type=CellType.STABLE)
    new_grid = tuple(tuple(row) for row in grid)

    new_pastures = compute_pastures_from_arrays(new_grid, new_hf, new_vf)
    new_farmyard = dataclasses.replace(
        fy,
        grid=new_grid,
        horizontal_fences=new_hf,
        vertical_fences=new_vf,
        pastures=new_pastures,
    )
    new_player = dataclasses.replace(p, farmyard=new_farmyard)
    new_players = tuple(
        new_player if i == player_idx else state.players[i] for i in range(2)
    )
    return dataclasses.replace(state, players=new_players)


def _reveal_all_stage_cards(state):
    """Mark every stage card revealed by setting round_revealed=1 on each.

    Useful for late-game states so that legality enumeration sees all 25
    spaces as available. The actual `round_card_order` is left alone — we
    just override the revealed flag to ensure the space is queryable.
    """
    new_state = state
    for sid in state.board.round_card_order:
        if sid is None:
            continue
        new_state = with_space(new_state, sid, round_revealed=1)
    return new_state


def _refill_all_accumulation(state, *, building_amount=3, scalar_amount=2):
    """Top up every accumulation space so its legality predicate passes."""
    new_state = state
    for sid in (
        "forest",
        "clay_pit",
        "reed_bank",
        "western_quarry",
        "eastern_quarry",
    ):
        rate = BUILDING_ACCUMULATION_RATES[sid]
        # Just multiply the per-round rate by `building_amount` rounds' worth.
        accumulated = Resources(
            wood=rate.wood * building_amount,
            clay=rate.clay * building_amount,
            reed=rate.reed * building_amount,
            stone=rate.stone * building_amount,
        )
        new_state = with_space(new_state, sid, accumulated=accumulated)
    for sid in ("fishing", "meeting_place", "sheep_market", "pig_market", "cattle_market"):
        new_state = with_space(new_state, sid, accumulated_amount=scalar_amount)
    return new_state


# ---------------------------------------------------------------------------
# Early-game states (rounds 1-3)
# ---------------------------------------------------------------------------

def early_round_1_default():
    """Fresh setup, seed 0. The baseline."""
    return setup(seed=0)


def early_round_2_post_placements():
    """Round 2 after a few worker placements have run and accumulation has
    been partially depleted. Built by running step() forward a few times
    from setup, so the state is fully reachable through normal gameplay."""
    state = setup(seed=0)
    # Place a handful of workers on safe early-game spaces. The exact
    # selections don't matter — we just want a state with some workers
    # placed, accumulation depleted in spots, and a non-default position.
    from agricola.actions import PlaceWorker
    for space in ("day_laborer", "grain_seeds", "forest", "clay_pit"):
        state = step(state, PlaceWorker(space=space))
    return state


def early_round_3_wealthy():
    """Round 3, both players with moderate stockpiles, one plowed field
    each, default rooms. Exercises early-game decision breadth — many more
    action spaces are legal than from a fresh setup, because the players
    can afford things they otherwise couldn't."""
    state = setup(seed=0)
    state = with_round(state, 3)
    # Stage 2 cards are revealed at round 5; nothing extra to reveal here.
    for pi in (0, 1):
        state = with_resources(
            state, pi,
            wood=8, clay=4, reed=3, stone=2,
            food=4, grain=2, veg=1,
        )
        state = with_fields(state, pi, [(0, 2)])
    state = _refill_all_accumulation(state, building_amount=2, scalar_amount=2)
    return state


# ---------------------------------------------------------------------------
# Mid-game states (rounds 6-9)
# ---------------------------------------------------------------------------

def mid_round_6_basic():
    """Round 6, one player has 2 small pastures + a few animals, the other
    has 3 fields + grain on them. Stage 2 cards revealed."""
    state = setup(seed=0)
    state = with_round(state, 6)

    # Player 0: pastures + animals
    state = with_resources(state, 0, wood=12, clay=6, reed=4, stone=3,
                           food=6, grain=1, veg=0)
    state = _add_pasture(state, 0, [(0, 2)], num_stables=1)  # 1x1, 1 stable -> capacity 4
    state = _add_pasture(state, 0, [(0, 3), (0, 4)], num_stables=0)  # 2x1 -> capacity 4
    state = with_animals(state, 0, sheep=2, boar=1, cattle=0)

    # Player 1: fields heavy
    state = with_resources(state, 1, wood=4, clay=2, reed=2, stone=1,
                           food=3, grain=0, veg=0)
    state = with_sown_fields(state, 1, grain_fields=[(0, 1), (0, 2)],
                             veg_fields=[(0, 3)])

    state = _refill_all_accumulation(state, building_amount=2)
    state = _reveal_all_stage_cards(state)  # stage 2 cards available
    state = with_current_player(state, 0)
    return state


def mid_round_8_animals():
    """Round 8, animal-heavy state to exercise pareto_frontier hot paths
    (animal-market accommodation). Both players have animals + pastures."""
    state = setup(seed=0)
    state = with_round(state, 8)

    for pi in (0, 1):
        state = with_resources(state, pi, wood=10, clay=4, reed=3, stone=2,
                               food=4, grain=0, veg=0)
        # 2x2 pasture at (0,2)-(1,3) - capacity 8
        state = _add_pasture(state, pi,
                             [(0, 2), (0, 3), (1, 2), (1, 3)],
                             num_stables=1)
        state = with_animals(state, pi, sheep=3, boar=2, cattle=1)

    state = _refill_all_accumulation(state, building_amount=3, scalar_amount=3)
    state = _reveal_all_stage_cards(state)
    state = with_majors(state, owner_by_idx={0: 0})  # P0 has Fireplace
    state = with_current_player(state, 0)
    return state


def mid_round_9_complex_farmyard():
    """Round 9, complex farmyard: 3 pastures with varied stables, fields
    sown, multiple rooms. Exercises pasture decomposition + legality across
    many enumerator paths."""
    state = setup(seed=0)
    state = with_round(state, 9)

    # Player 0: complex farmyard
    state = with_resources(state, 0, wood=15, clay=8, reed=5, stone=4,
                           food=8, grain=2, veg=1)
    # Add an extra wood room first
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    # Now place sown fields + pastures using non-room cells
    state = with_sown_fields(state, 0, grain_fields=[(0, 1)], veg_fields=[(0, 2)])
    # Pasture 1: 1x1 stable at (1, 1)
    state = _add_pasture(state, 0, [(1, 1)], num_stables=1)
    # Pasture 2: 1x1 at (0, 3)
    state = _add_pasture(state, 0, [(0, 3)], num_stables=0)
    # Pasture 3: 2x1 at (1, 3)-(1, 4)
    state = _add_pasture(state, 0, [(1, 3), (1, 4)], num_stables=0)
    state = with_animals(state, 0, sheep=4, boar=1, cattle=2)
    state = with_people(state, 0, total=3, home=3)

    # Player 1: contrast — simpler, more empty cells
    state = with_resources(state, 1, wood=6, clay=3, reed=2, stone=2,
                           food=3, grain=1, veg=0)

    state = _refill_all_accumulation(state, building_amount=2)
    state = _reveal_all_stage_cards(state)
    state = with_majors(state, owner_by_idx={2: 0, 7: 1})  # P0 has Cooking Hearth, P1 has Joinery
    state = with_current_player(state, 0)
    return state


# ---------------------------------------------------------------------------
# Late-game states (rounds 11-14)
# ---------------------------------------------------------------------------

def late_round_12_clay_house():
    """Round 12, player 0 has clay house + multiple majors. Stage 5 cards
    revealed (urgent_wish_for_children, cultivation)."""
    state = setup(seed=0)
    state = with_round(state, 12)

    state = with_resources(state, 0, wood=12, clay=8, reed=4, stone=8,
                           food=10, grain=3, veg=2)
    state = with_house(state, 0, HouseMaterial.CLAY)
    # Convert wood rooms to clay rooms (cell type stays ROOM; house_material is on PlayerState)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})  # extra room
    state = with_sown_fields(state, 0, grain_fields=[(0, 1)])
    state = _add_pasture(state, 0, [(1, 1), (1, 2)], num_stables=1)
    state = with_animals(state, 0, sheep=3, boar=2, cattle=2)
    state = with_people(state, 0, total=3, home=3)

    state = with_resources(state, 1, wood=8, clay=4, reed=3, stone=3,
                           food=6, grain=1, veg=1)
    state = with_sown_fields(state, 1, grain_fields=[(0, 1), (0, 2)])

    state = _refill_all_accumulation(state, building_amount=2)
    state = _reveal_all_stage_cards(state)
    state = with_majors(state, owner_by_idx={0: 0, 7: 0, 8: 1})  # P0 Fireplace+Joinery, P1 Pottery
    state = with_current_player(state, 0)
    return state


def late_round_13_harvest_setup():
    """Round 13 (a harvest round), positioned to exercise the harvest
    sub-phase decision surface. The state itself is in WORK phase — round
    13's harvest fires after RETURN_HOME. Workload C still calls
    legal_actions/step on this WORK-phase state."""
    state = setup(seed=0)
    state = with_round(state, 13)

    # Player 0: full farm, ready to be hit with harvest
    state = with_resources(state, 0, wood=6, clay=3, reed=2, stone=3,
                           food=2, grain=2, veg=1)
    state = with_sown_fields(state, 0,
                             grain_fields=[(0, 1), (0, 2)],
                             veg_fields=[(0, 3)])
    state = _add_pasture(state, 0, [(1, 1), (1, 2)], num_stables=1)
    state = with_animals(state, 0, sheep=4, boar=2, cattle=1)
    state = with_people(state, 0, total=4, home=4)

    state = with_resources(state, 1, wood=4, clay=2, reed=2, stone=2,
                           food=1, grain=1, veg=0)
    state = with_sown_fields(state, 1, grain_fields=[(0, 1)])
    state = with_animals(state, 1, sheep=2, boar=0, cattle=0)

    state = _refill_all_accumulation(state, building_amount=2)
    state = _reveal_all_stage_cards(state)
    state = with_majors(state, owner_by_idx={2: 0, 7: 1, 8: 0})
    state = with_current_player(state, 0)
    return state


def late_round_14_all_legal():
    """Round 14, **all 25 action spaces except `lessons` are legal**.

    This is the coverage state for Workload C — by itself it makes every
    legality predicate pass for the active player, except `lessons`
    (permanently illegal in the Family game).

    Layout for player 0 (the active player):
    - WOOD house (so `house_redevelopment` / `farm_redevelopment` are legal —
      both call `_can_renovate`, which requires wood-or-clay house)
    - 3 rooms (so `basic_wish_for_children` is legal: rooms > people_total)
    - 2 people total, 2 at home
    - One plowed-not-sown field (so cultivation / grain_utilization's sow path is legal)
    - One empty cell adjacent to rooms (so farm_expansion's room-build path is legal)
    - Many empty non-enclosed cells (for fencing / farm_expansion stable-build / farmland)
    - Fireplace owned (so bake_bread paths are legal; baker for grain_utilization / side_job)
    - Resources sized so every cost-gate is satisfied
    - All accumulation spaces topped up so the take-from-accumulation predicates pass
    - All stage cards revealed at round 1 so the stage-2-through-stage-6 cards are queryable
    """
    state = setup(seed=0)
    state = with_round(state, 14)

    # --- Active player (0): designed so every space's legality predicate passes
    state = with_house(state, 0, HouseMaterial.WOOD)
    state = with_people(state, 0, total=2, home=2)
    # 3 rooms at (0,0), (1,0), (2,0); one plowed field at (0,2)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})  # add a third room
    state = with_fields(state, 0, [(0, 2)])
    state = with_resources(
        state, 0,
        wood=50,   # plenty for fencing, stables, rooms, majors
        clay=20,   # renovate (3 rooms = 3 clay), ovens, majors
        reed=10,   # rooms, ovens, majors, renovate
        stone=10,  # majors, ovens, wells
        food=30,
        grain=5,   # sowing + baking
        veg=3,     # sowing
    )
    state = with_animals(state, 0, sheep=1, boar=1, cattle=1)

    # Give P0 a baking improvement (Fireplace idx=0) but NOT every major,
    # so `major_improvement` legality (afford any unowned major) still passes.
    state = with_majors(state, owner_by_idx={0: 0})

    # --- Player 1: just give them resources so the game stays interesting
    state = with_resources(state, 1, wood=8, clay=4, reed=3, stone=3,
                           food=5, grain=1, veg=1)

    # --- All accumulation spaces topped up
    state = _refill_all_accumulation(state, building_amount=3, scalar_amount=3)

    # --- All stage cards visibly revealed (some stage-3-onward cards default to
    # round_revealed > 14 in the original shuffle; this forces them all on)
    state = _reveal_all_stage_cards(state)

    # P0 is the carefully-designed player; make them active so legality fires
    # against the right farmyard.
    state = with_current_player(state, 0)

    return state


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

STATES = {
    # Early
    "early_round_1_default":         early_round_1_default,
    "early_round_2_post_placements": early_round_2_post_placements,
    "early_round_3_wealthy":         early_round_3_wealthy,
    # Mid
    "mid_round_6_basic":             mid_round_6_basic,
    "mid_round_8_animals":           mid_round_8_animals,
    "mid_round_9_complex_farmyard":  mid_round_9_complex_farmyard,
    # Late
    "late_round_12_clay_house":      late_round_12_clay_house,
    "late_round_13_harvest_setup":   late_round_13_harvest_setup,
    "late_round_14_all_legal":       late_round_14_all_legal,
}


EARLY = ("early_round_1_default", "early_round_2_post_placements", "early_round_3_wealthy")
MID   = ("mid_round_6_basic", "mid_round_8_animals", "mid_round_9_complex_farmyard")
LATE  = ("late_round_12_clay_house", "late_round_13_harvest_setup", "late_round_14_all_legal")


# ---------------------------------------------------------------------------
# Validation: run by `python scripts/profile_states.py`
# ---------------------------------------------------------------------------

def _validate():
    """Build each state and call legal_actions on it to confirm structural
    validity. Also report which action spaces are legal in each state, so
    Workload C's coverage requirement can be audited."""
    from agricola.actions import PlaceWorker
    from agricola.constants import SPACE_IDS
    from agricola.legality import legal_actions

    print(f"Validating {len(STATES)} prefab states:\n")
    all_legal_spaces = set()
    for name, factory in STATES.items():
        state = factory()
        actions = legal_actions(state)
        place_actions = [a for a in actions if isinstance(a, PlaceWorker)]
        legal_spaces = sorted(a.space for a in place_actions)
        all_legal_spaces.update(legal_spaces)
        print(f"  {name}")
        print(f"    round={state.round_number} phase={state.phase.name} "
              f"current_player={state.current_player} "
              f"#legal_actions={len(actions)} #legal_placements={len(place_actions)}")
        print(f"    legal placements: {', '.join(legal_spaces)}")
        print()

    print("Coverage audit (Workload C requirement):")
    expected = set(SPACE_IDS) - {"lessons"}  # lessons permanently illegal in Family
    missing = expected - all_legal_spaces
    extra = all_legal_spaces - set(SPACE_IDS)
    if missing:
        print(f"  MISSING ({len(missing)}): {sorted(missing)}")
    else:
        print(f"  All {len(expected)} non-`lessons` spaces are legal in at least one state. ✓")
    if extra:
        print(f"  UNEXPECTED: {sorted(extra)}")
    print(f"  (Skipped: lessons — permanently illegal in Family without occupation cards.)")


if __name__ == "__main__":
    _validate()
