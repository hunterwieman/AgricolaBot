from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from agricola.constants import (
    NUM_MAJOR_IMPROVEMENTS,
    NUM_ROUNDS,
    PERMANENT_ACTION_SPACES,
    SPACE_IDS,
    STAGE_CARDS,
    CellType,
    GameMode,
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


def _make_action_spaces_family() -> tuple:
    """Build the initial ActionSpaceState for all 25 action spaces (Family board).

    Returns a tuple of length len(SPACE_IDS), indexed by SPACE_INDEX[space_id].
    Permanent spaces are `revealed=True`; stage cards `revealed=False` (turned up
    by their RevealCard during play — round 1's is dealt by `setup_env`). ALL
    spaces start with empty accumulation: the round-1 reveal's
    `_complete_preparation` loads round-1 goods for the revealed accumulation
    spaces, exactly like every later round. See HIDDEN_INFO_DESIGN.md §3.3.

    The card board (GameMode.CARDS) will diverge from this — a distinct
    `meeting_place_cards` space appended to SPACE_IDS — when the play-card
    foundation lands (CARD_IMPLEMENTATION_PLAN.md I.3, Milestone 1). Until then a
    CARDS game reuses this board and differs only in placement legality
    (CARD_GAME_LEGALITY) + the dealt hands.
    """
    by_id: dict[str, ActionSpaceState] = {}
    for space_id in PERMANENT_ACTION_SPACES:
        # Permanents are face-up before round 1 — revealed_round 0.
        by_id[space_id] = ActionSpaceState(workers=(0, 0), revealed=True,
                                           revealed_round=0)
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


def _make_player(
    food: int,
    *,
    hand_occupations: frozenset = frozenset(),
    hand_minors: frozenset = frozenset(),
) -> PlayerState:
    """Build a starting PlayerState with the given food amount.

    `hand_occupations` / `hand_minors` default empty (the Family game); the card
    game passes the dealt hands. See CARD_IMPLEMENTATION_PLAN.md I.5/I.6.
    """
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
        hand_occupations=hand_occupations,
        hand_minors=hand_minors,
    )


@dataclass(frozen=True)
class CardPool:
    """The configured card pools a card game deals hands from (I.6).

    `occupations` / `minors` are the card-id pools each player's hand is drawn
    from. The engine deals uniformly from these — the competitive draft is a
    belief-construction concern handled above the engine (CARD_SYSTEM_DESIGN.md
    §2, CARD_IMPLEMENTATION_PLAN.md I.5), so setup only needs pools large enough
    to deal HAND_SIZE + HAND_SIZE per player. Card-spec loading (on-play effects,
    costs, prerequisites) is separate and lands with the play-card foundation.
    """
    occupations: tuple = ()   # tuple[str, ...] — occupation card ids
    minors: tuple = ()        # tuple[str, ...] — minor-improvement card ids


HAND_SIZE = 7  # cards of each type per player (2-player full game; RULES.md → the draft)


def _deal_hands(rng: np.random.Generator, card_pool: CardPool) -> tuple:
    """Deal each player HAND_SIZE occupations + HAND_SIZE minors from the pool.

    Returns ((occ0, min0), (occ1, min1)) of frozensets of card ids — a uniform
    draw without replacement across both players (no draft modeled — I.5). The
    pool must hold at least 2 * HAND_SIZE of each type.
    """
    occ = list(card_pool.occupations)
    minr = list(card_pool.minors)
    need = 2 * HAND_SIZE
    if len(occ) < need or len(minr) < need:
        raise ValueError(
            f"card pool too small: need >= {need} of each type, got "
            f"{len(occ)} occupations / {len(minr)} minors"
        )
    occ_pick = rng.choice(len(occ), size=need, replace=False)
    min_pick = rng.choice(len(minr), size=need, replace=False)
    hands = []
    for p in range(2):
        lo, hi = p * HAND_SIZE, (p + 1) * HAND_SIZE
        hands.append((
            frozenset(occ[i] for i in occ_pick[lo:hi]),
            frozenset(minr[i] for i in min_pick[lo:hi]),
        ))
    return tuple(hands)


def _deal_draft_pools(rng: np.random.Generator, card_pool: CardPool) -> tuple:
    """Deal four separate draft pools: (p0_occ, p0_min, p1_occ, p1_min).

    Each pool is HAND_SIZE cards, all drawn without replacement across both
    players. Returns a 4-tuple of tuple[str, ...] of card ids.
    """
    occ = list(card_pool.occupations)
    minr = list(card_pool.minors)
    need = 2 * HAND_SIZE
    if len(occ) < need or len(minr) < need:
        raise ValueError(
            f"card pool too small: need >= {need} of each type, got "
            f"{len(occ)} occupations / {len(minr)} minors"
        )
    occ_pick = rng.choice(len(occ), size=need, replace=False)
    min_pick = rng.choice(len(minr), size=need, replace=False)
    p0_occ = tuple(occ[i] for i in occ_pick[:HAND_SIZE])
    p1_occ = tuple(occ[i] for i in occ_pick[HAND_SIZE:])
    p0_min = tuple(minr[i] for i in min_pick[:HAND_SIZE])
    p1_min = tuple(minr[i] for i in min_pick[HAND_SIZE:])
    return (p0_occ, p0_min, p1_occ, p1_min)


def setup_env(seed: int, *, card_pool: Optional[CardPool] = None,
              draft: bool = False) -> tuple:
    """Initialise a 2-player game; return (initial state, Environment).

    `card_pool=None` → the Family game (GameMode.FAMILY): today's board, empty
    hands — byte-identical to before (the RNG draw sequence is unchanged on this
    path). `card_pool=CardPool(...)` → the card game (GameMode.CARDS): hands are
    dealt from the pool and `GameState.mode` is set to CARDS. See
    CARD_IMPLEMENTATION_PLAN.md I.6.

    `draft=True` (card game only): instead of dealing complete hands, deal four
    draft pools and return a Phase.DRAFT state. Players pick one card at a time
    (occupation then minor per round) and pass pools between rounds. The returned
    state is NOT the round-1 WORK state — it is the DRAFT state before any picks.
    The caller drives the draft via legal_actions/step (CommitDraftPick actions)
    until the state advances to Phase.PREPARATION and then to Phase.WORK normally.

    All randomness (starting player, dealt hands/pools, per-stage card shuffle) is
    resolved here from the seeded RNG. The shuffled reveal order is hidden
    information and lives in the returned Environment — NOT in GameState. When
    draft=False the round 1 reveal is pre-dealt, so the returned GameState is a
    round-1 WORK state. See HIDDEN_INFO_DESIGN.md §3.3 / §3.5.
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

    mode = GameMode.FAMILY if card_pool is None else GameMode.CARDS
    if card_pool is None:
        players = tuple(_make_player(food_for[p]) for p in range(2))
    elif draft:
        # Draft mode: deal four separate pools; hands start empty.
        draft_pools = _deal_draft_pools(rng, card_pool)
        players = tuple(_make_player(food_for[p]) for p in range(2))
    else:
        # Card mode draws from the RNG here; the Family path above does not, so
        # Family setup(seed) is unchanged.
        hands = _deal_hands(rng, card_pool)
        players = tuple(
            _make_player(
                food_for[p],
                hand_occupations=hands[p][0],
                hand_minors=hands[p][1],
            )
            for p in range(2)
        )

    # Hidden reveal order → Environment.
    round_card_order = _make_round_card_order(rng)
    env = Environment(round_card_order=round_card_order)

    board = BoardState(
        # The card board reuses the Family board until `meeting_place_cards`
        # lands with the play-card foundation (I.3); modes differ only in
        # CARD_GAME_LEGALITY + the dealt hands for now.
        action_spaces=_make_action_spaces_family(),
        major_improvement_owners=tuple(None for _ in range(NUM_MAJOR_IMPROVEMENTS)),
    )

    if draft and card_pool is not None:
        # Draft start: return Phase.DRAFT state; no round is pre-dealt.
        # The engine drives picks via CommitDraftPick until all pools are empty,
        # then advances to PREPARATION → WORK normally (including the round-1 reveal).
        raw = GameState(
            round_number=0,
            phase=Phase.DRAFT,
            current_player=starting_player,
            starting_player=starting_player,
            players=players,
            board=board,
            pending_stack=(),
            mode=mode,
            draft_pools=draft_pools,
        )
        # Advance so the first PendingDraftPick frame is on the stack before
        # returning — callers (and legal_actions) expect a paused state.
        state = _advance_until_decision(raw)
        return state, env

    # Pre-round-1 state: round_number=0, PREPARATION, empty stack, nothing revealed.
    pre = GameState(
        round_number=0,
        phase=Phase.PREPARATION,
        current_player=starting_player,
        starting_player=starting_player,
        players=players,
        board=board,
        pending_stack=(),
        mode=mode,
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
