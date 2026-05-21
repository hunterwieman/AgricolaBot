from __future__ import annotations

import numpy as np

from agricola.constants import (
    BUILDING_ACCUMULATION_RATES,
    FOOD_ANIMAL_ACCUMULATION_RATES,
    NUM_MAJOR_IMPROVEMENTS,
    NUM_ROUNDS,
    PERMANENT_ACTION_SPACES,
    SPACE_IDS,
    STAGE_CARDS,
    CellType,
    HouseMaterial,
    Phase,
)
from agricola.resources import Animals, Resources
from agricola.state import (
    ActionSpaceState,
    BoardState,
    Cell,
    Farmyard,
    GameState,
    PlayerState,
)

# TODO: A canonical enumeration of valid fence configurations will be needed by
# enumerate_valid_fence_actions (deferred). Consider implementing in a separate
# fencing.py module to keep setup.py focused on initialisation.


def _make_round_card_order(rng: np.random.Generator) -> tuple:
    """Shuffle cards within each stage and concatenate to produce round_card_order.

    round_card_order[i] is the action space ID that appears at round i+1.
    """
    order = []
    for stage in sorted(STAGE_CARDS.keys()):
        cards = list(STAGE_CARDS[stage])
        rng.shuffle(cards)
        order.extend(cards)
    return tuple(order)


def _make_action_spaces(round_card_order: tuple) -> tuple:
    """Build the initial ActionSpaceState for all 25 action spaces.

    Returns a tuple of length len(SPACE_IDS), indexed by SPACE_INDEX[space_id].
    Permanent spaces: round_revealed=0, accumulated/accumulated_amount pre-loaded for round 1.
    Stage cards: round_revealed = the round they appear, accumulated=Resources(), accumulated_amount=0.
    """
    by_id: dict[str, ActionSpaceState] = {}

    # Permanent spaces
    for space_id in PERMANENT_ACTION_SPACES:
        if space_id in BUILDING_ACCUMULATION_RATES:
            # Building-resource space: pre-load round-1 Resources
            by_id[space_id] = ActionSpaceState(
                workers=(0, 0),
                accumulated=BUILDING_ACCUMULATION_RATES[space_id],
                round_revealed=0,
            )
        elif space_id in FOOD_ANIMAL_ACCUMULATION_RATES:
            # Food/animal space: pre-load scalar round-1 goods
            _, rate = FOOD_ANIMAL_ACCUMULATION_RATES[space_id]
            by_id[space_id] = ActionSpaceState(
                workers=(0, 0),
                accumulated_amount=rate,
                round_revealed=0,
            )
        else:
            by_id[space_id] = ActionSpaceState(
                workers=(0, 0),
                round_revealed=0,
            )

    # Stage cards — round_card_order[i] appears at round i+1
    for i, card_id in enumerate(round_card_order):
        round_revealed = i + 1
        if card_id in BUILDING_ACCUMULATION_RATES:
            by_id[card_id] = ActionSpaceState(
                workers=(0, 0),
                accumulated=Resources(),
                round_revealed=round_revealed,
            )
        else:
            by_id[card_id] = ActionSpaceState(
                workers=(0, 0),
                accumulated_amount=0,
                round_revealed=round_revealed,
            )

    return tuple(by_id[sid] for sid in SPACE_IDS)


def _make_farmyard() -> Farmyard:
    """Build a fresh farmyard with starting rooms at (1,0) and (2,0)."""
    room_cell = Cell(cell_type=CellType.ROOM)
    empty_cell = Cell()

    grid = tuple(
        tuple(
            room_cell if (r, c) in {(1, 0), (2, 0)} else empty_cell
            for c in range(5)
        )
        for r in range(3)
    )

    horizontal_fences = tuple(tuple(False for _ in range(5)) for _ in range(4))
    vertical_fences = tuple(tuple(False for _ in range(6)) for _ in range(3))

    return Farmyard(
        grid=grid,
        horizontal_fences=horizontal_fences,
        vertical_fences=vertical_fences,
    )


def _make_player(food: int) -> PlayerState:
    """Build a starting PlayerState with the given food amount."""
    return PlayerState(
        resources=Resources(food=food),
        animals=Animals(),
        farmyard=_make_farmyard(),
        house_material=HouseMaterial.WOOD,
        people_total=2,
        people_home=2,
        newborns=0,
        begging_markers=0,
        future_resources=(Resources(),) * NUM_ROUNDS,
        minor_improvements=frozenset(),
        occupations=frozenset(),
        harvest_conversions_used=frozenset(),
    )


def setup(seed: int) -> GameState:
    """Initialise a 2-player Family game and return the starting GameState.

    All randomness is resolved here using the seeded RNG. After this function
    returns the game is fully deterministic.
    """
    rng = np.random.default_rng(seed)

    # 1. Determine starting player
    starting_player = int(rng.integers(0, 2))  # 0 or 1

    # Starting player gets 2 food; other player gets 3 food
    food_for = [3, 3]
    food_for[starting_player] = 2

    # 2 & 3. Build player states
    players = tuple(_make_player(food_for[p]) for p in range(2))

    # 4. Determine round card order
    round_card_order = _make_round_card_order(rng)

    # 5. Initialise action spaces
    action_spaces = _make_action_spaces(round_card_order)

    # 6. All major improvements start on the supply board
    major_improvement_owners = tuple(None for _ in range(NUM_MAJOR_IMPROVEMENTS))

    board = BoardState(
        action_spaces=action_spaces,
        major_improvement_owners=major_improvement_owners,
        round_card_order=round_card_order,
    )

    # 7. Starting phase is WORK; current player is the starting player.
    # pending_stack is empty (no non-atomic action in progress at game start).
    return GameState(
        round_number=1,
        phase=Phase.WORK,
        current_player=starting_player,
        starting_player=starting_player,
        players=players,
        board=board,
        pending_stack=(),
    )
