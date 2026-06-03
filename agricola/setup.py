from __future__ import annotations

import numpy as np

from agricola.constants import (
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


def _make_action_spaces() -> tuple:
    """Build the initial ActionSpaceState for all 25 action spaces.

    Returns a tuple of length len(SPACE_IDS), indexed by SPACE_INDEX[space_id].
    Permanent spaces are `revealed=True`; stage cards `revealed=False` (turned up
    by their RevealCard during play — round 1's is dealt by `setup_env`). ALL
    spaces start with empty accumulation: the round-1 reveal's
    `_complete_preparation` loads round-1 goods for the revealed accumulation
    spaces, exactly like every later round. See HIDDEN_INFO_DESIGN.md §3.3.
    """
    by_id: dict[str, ActionSpaceState] = {}
    for space_id in PERMANENT_ACTION_SPACES:
        by_id[space_id] = ActionSpaceState(workers=(0, 0), revealed=True)
    for cards in STAGE_CARDS.values():
        for card_id in cards:
            by_id[card_id] = ActionSpaceState(workers=(0, 0), revealed=False)
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


def setup_env(seed: int) -> tuple:
    """Initialise a 2-player Family game; return (round-1 WORK state, Environment).

    All randomness (starting player, per-stage card shuffle) is resolved here from
    the seeded RNG. The shuffled reveal order is hidden information and lives in the
    returned Environment — NOT in GameState. Round 1 is dealt internally (its reveal
    is resolved via the env), so the returned GameState is a round-1 WORK state — the
    game's first player decision. Full-game drivers that cross a round boundary use
    this and pass `env.resolve` as the reveal dealer for rounds 2–14. See
    HIDDEN_INFO_DESIGN.md §3.3 / §3.5.
    """
    # Local imports: keep `agricola.setup` import-time light and avoid any cycle
    # (engine / environment are leaves consumed here, not at module load).
    from agricola.engine import step, _advance_until_decision
    from agricola.environment import Environment

    rng = np.random.default_rng(seed)

    # Starting player + food (SP gets 2, the other 3).
    starting_player = int(rng.integers(0, 2))
    food_for = [3, 3]
    food_for[starting_player] = 2
    players = tuple(_make_player(food_for[p]) for p in range(2))

    # Hidden reveal order → Environment.
    round_card_order = _make_round_card_order(rng)
    env = Environment(round_card_order=round_card_order)

    board = BoardState(
        action_spaces=_make_action_spaces(),
        major_improvement_owners=tuple(None for _ in range(NUM_MAJOR_IMPROVEMENTS)),
    )

    # Pre-round-1 state: round_number=0, PREPARATION, empty stack, nothing revealed.
    pre = GameState(
        round_number=0,
        phase=Phase.PREPARATION,
        current_player=starting_player,
        starting_player=starting_player,
        players=players,
        board=board,
        pending_stack=(),
    )

    # Deal round 1: advance to the round-1 reveal nature node, apply the true card
    # via the env → round-1 WORK.
    reveal_node = _advance_until_decision(pre)
    state = step(reveal_node, env.reveal_action(reveal_node))
    return state, env


def setup(seed: int) -> GameState:
    """Initialise a 2-player Family game and return the round-1 WORK GameState.

    Thin wrapper over `setup_env` that drops the Environment. Fine for inspecting
    the initial state or building a scenario on it; full-game drivers that cross a
    round boundary need `setup_env` (the Environment is the reveal dealer for
    rounds 2–14). See HIDDEN_INFO_DESIGN.md §3.5.
    """
    return setup_env(seed)[0]
