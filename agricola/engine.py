"""Game-state transition engine.

Public API: `step(state, action) -> GameState`. Pure transition function;
the loop that drives a game lives outside this module (typically in the
agent loop / test harness).

See CLAUDE.md "Engine and Turn Resolution Architecture" for the full
design rationale and TASK_5.md for the implementation breakdown.
"""
from __future__ import annotations

import dataclasses

from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitAccommodate,
    CommitBake,
    CommitBuildMajor,
    CommitBuildRoom,
    CommitBuildStable,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    CommitSubAction,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.constants import (
    BUILDING_ACCUMULATION_RATES,
    FOOD_ANIMAL_ACCUMULATION_RATES,
    Phase,
)
from agricola.pending import (
    PendingBakeBread,
    PendingBuildRooms,
    PendingBuildStables,
    PendingBuildMajor,
    PendingCattleMarket,
    PendingPigMarket,
    PendingPlow,
    PendingRenovate,
    PendingSheepMarket,
    PendingSow,
    pop,
    replace_top,
)
from agricola.resources import Resources
from agricola.state import GameState
from agricola.resolution import (
    ATOMIC_HANDLERS,
    CHOOSE_SUBACTION_HANDLERS,
    NONATOMIC_HANDLERS,
    _apply_worker_placement,
    _execute_accommodate,
    _execute_bake,
    _execute_build_major,
    _execute_build_room,
    _execute_build_stable,
    _execute_plow,
    _execute_renovate,
    _execute_sow,
)

# Ensure card registrations run at engine-module load time.
import agricola.cards  # noqa: F401


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def step(state: GameState, action: Action) -> GameState:
    """Apply one action and auto-advance through system transitions.

    Preconditions (caller's responsibility — step does NOT validate):
      - action is in legal_actions(state).
      - state.phase != Phase.BEFORE_SCORING.

    Postconditions:
      - The action's effect has been applied.
      - The state has been auto-advanced through phase transitions and
        active-player switches until the next agent decision OR
        state.phase == Phase.BEFORE_SCORING.

    Raises:
      - NotImplementedError if action is a PlaceWorker on `farm_expansion`,
        `farm_redevelopment`, or `fencing` (still deferred after Task 5C).
      - RuntimeError if state.phase == Phase.BEFORE_SCORING.
    """
    if state.phase == Phase.BEFORE_SCORING:
        raise RuntimeError("step called on a terminated game")

    # 1. Apply the agent's action.
    state = _apply_action(state, action)

    # 2. If a worker placement just completed (stack is now empty in WORK),
    #    rotate to the next player who has workers. This is THE alternation
    #    point — it does not run at any other time.
    #
    #    The `state.phase == Phase.WORK` clause is a safety guard. In Task 5
    #    step is only ever called during WORK (no agent decisions during
    #    RETURN_HOME or PREPARATION), so the clause is redundant for Task 5.
    #    It matters once cards introduce mid-RETURN_HOME / mid-PREPARATION /
    #    mid-HARVEST triggers that require agent input: at that point step
    #    is called in those phases, and we do NOT want to alternate workers
    #    when the player resolves a return-home trigger — workers aren't
    #    being placed during RETURN_HOME. The clause guards against that.
    if state.phase == Phase.WORK and not state.pending_stack:
        state = _advance_current_player(state)

    # 3. Walk through system-driven transitions (phase changes) until the
    #    next agent decision OR the game ends.
    state = _advance_until_decision(state)
    return state


# ---------------------------------------------------------------------------
# Action dispatch
# ---------------------------------------------------------------------------

def _apply_action(state: GameState, action: Action) -> GameState:
    if isinstance(action, PlaceWorker):
        return _apply_place_worker(state, action)
    if isinstance(action, ChooseSubAction):
        return _apply_choose_sub_action(state, action)
    if isinstance(action, CommitSubAction):
        return _apply_commit_subaction(state, action)
    if isinstance(action, FireTrigger):
        return _apply_fire_trigger(state, action)
    if isinstance(action, Stop):
        return _apply_stop(state)
    raise TypeError(f"Unknown action type: {type(action).__name__}")


# Metadata dispatch table for Commit* sub-actions. Each entry maps a
# CommitSubAction subclass to:
#   (expected_pending_type, effect_fn, auto_pop)
# Co-located with its sole consumer (_apply_commit_subaction below).
#
# `auto_pop` semantics:
#   True  -> dispatcher pops the sub-action pending after the effect runs.
#   False -> dispatcher leaves the stack alone; the effect function is
#            responsible for any stack manipulation (pop, push wrapper, etc.).
#
# Adding a new sub-action: define a new CommitX subclass + an
# `_execute_x(state, player_idx, commit)` in resolution.py + a row here.
COMMIT_SUBACTION_HANDLERS: dict[type, tuple] = {
    CommitSow:          (PendingSow,          _execute_sow,          True),
    CommitBake:         (PendingBakeBread,    _execute_bake,         True),
    CommitPlow:         (PendingPlow,         _execute_plow,         True),
    CommitBuildStable:  (PendingBuildStables, _execute_build_stable, False),
    CommitBuildRoom:    (PendingBuildRooms,   _execute_build_room,   False),
    CommitRenovate:     (PendingRenovate,     _execute_renovate,     True),
    # CommitAccommodate lands on any of three market parent pendings.
    # `isinstance` handles tuple-of-types natively in _apply_commit_subaction.
    CommitAccommodate:  (
        (PendingSheepMarket, PendingPigMarket, PendingCattleMarket),
        _execute_accommodate,
        True,
    ),
    # CommitBuildMajor: auto_pop=False because the effect function owns its
    # own conditional stack manipulation — pop PendingBuildMajor for non-oven
    # majors, or push PendingClayOven / PendingStoneOven (leaving
    # PendingBuildMajor on the stack underneath) for ovens.
    CommitBuildMajor:   (PendingBuildMajor,   _execute_build_major,  False),
}


def _apply_place_worker(state: GameState, action: PlaceWorker) -> GameState:
    # Cross-cutting bookkeeping: workers, people_home.
    state = _apply_worker_placement(state, action.space)

    if action.space in ATOMIC_HANDLERS:
        return ATOMIC_HANDLERS[action.space](state)

    if action.space in NONATOMIC_HANDLERS:
        return NONATOMIC_HANDLERS[action.space](state)

    raise NotImplementedError(
        f"Non-atomic space {action.space!r} is not implemented "
        f"(deferred: farm_expansion, farm_redevelopment, fencing)"
    )


def _apply_choose_sub_action(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    assert state.pending_stack, "ChooseSubAction called with empty pending_stack"
    top = state.pending_stack[-1]
    handler = CHOOSE_SUBACTION_HANDLERS.get(type(top))
    if handler is None:
        raise ValueError(
            f"No ChooseSubAction handler registered for pending type "
            f"{type(top).__name__}"
        )
    return handler(state, action)


def _apply_commit_subaction(
    state: GameState, action: CommitSubAction,
) -> GameState:
    """Generic handler for any CommitSubAction subclass.

    Looks up `(expected_pending_type, effect_fn, auto_pop)` in
    `COMMIT_SUBACTION_HANDLERS`, asserts the expected pending is on top,
    applies the effect, and (if `auto_pop`) pops the sub-action pending.

    When `auto_pop=False`, the effect function is responsible for any stack
    manipulation it needs (pop, push wrapper, replace_top, etc.).

    Parent `*_chosen` flags are set earlier, by the `_choose_subaction_*`
    handler that pushed the sub-action pending. This dispatcher does not
    touch parent state.
    """
    assert state.pending_stack, (
        f"{type(action).__name__} called with empty pending_stack"
    )
    pending_type, effect_fn, auto_pop = COMMIT_SUBACTION_HANDLERS[type(action)]
    top = state.pending_stack[-1]
    assert isinstance(top, pending_type), (
        f"{type(action).__name__} expected top={pending_type.__name__}, "
        f"got {type(top).__name__}"
    )
    state = effect_fn(state, top.player_idx, action)
    if auto_pop:
        state = pop(state)
    return state


def _apply_fire_trigger(
    state: GameState, action: FireTrigger,
) -> GameState:
    from agricola.cards.triggers import CARDS  # local import to avoid load-order surprises
    assert state.pending_stack, "FireTrigger called with empty pending_stack"
    top = state.pending_stack[-1]
    entry = CARDS[action.card_id]
    state = entry.apply_fn(state, top.player_idx)
    new_top = dataclasses.replace(
        top, triggers_resolved=top.triggers_resolved | {action.card_id},
    )
    return replace_top(state, new_top)


def _apply_stop(state: GameState) -> GameState:
    assert state.pending_stack, "Stop called with empty pending_stack"
    # Pop only the top frame. Do NOT assert the stack is empty afterward —
    # future cards may have deeper stacks where Stop is legal at a non-bottom
    # frame.
    return pop(state)


# ---------------------------------------------------------------------------
# Active-player alternation
# ---------------------------------------------------------------------------

def _advance_current_player(state: GameState) -> GameState:
    """Rotate current_player to the next player who has workers.

    If only the current player has workers, return state unchanged (they
    keep placing). If no player has workers, return state unchanged —
    `_advance_until_decision` then transitions to RETURN_HOME.

    Modular arithmetic generalizes to N-player games even though Task 5
    has 2 players. Future cards may allow placing with people_home == 0
    (e.g., certain occupations grant "free" placements); the predicate
    below would need to consult those card states at that time.
    """
    num_players = len(state.players)
    for offset in range(1, num_players):
        candidate = (state.current_player + offset) % num_players
        if state.players[candidate].people_home > 0:
            return dataclasses.replace(state, current_player=candidate)
    return state


# ---------------------------------------------------------------------------
# Phase auto-advance
# ---------------------------------------------------------------------------

def _advance_until_decision(state: GameState) -> GameState:
    """Walk system-driven phase transitions until the next agent decision
    or game-over. Pure function over state.

    Idempotent: any state returned by this function is stable — running
    it again produces the same state.
    """
    while True:
        # Case 1: a pending frame is active. Decision is awaiting agent.
        if state.pending_stack:
            return state

        # Case 2: terminal phase. No more steps possible.
        if state.phase == Phase.BEFORE_SCORING:
            return state

        # Case 3: WORK phase. If any player has workers, an agent decision
        # is awaiting. If neither does, the work phase ends.
        if state.phase == Phase.WORK:
            if all(p.people_home == 0 for p in state.players):
                state = dataclasses.replace(state, phase=Phase.RETURN_HOME)
                continue
            return state

        # Case 4: RETURN_HOME phase. End-of-round bookkeeping.
        if state.phase == Phase.RETURN_HOME:
            state = _resolve_return_home(state)
            continue

        # Case 5: PREPARATION phase. Setup for the next round.
        if state.phase == Phase.PREPARATION:
            state = _resolve_preparation(state)
            continue

        # TODO: when the harvest is implemented, branches for HARVEST_FIELD,
        # HARVEST_FEED, HARVEST_BREED go here. They would be entered from
        # _resolve_return_home on HARVEST_ROUNDS (4, 7, 9, 11, 13, 14).
        raise AssertionError(f"Unexpected phase in advance loop: {state.phase}")


# ---------------------------------------------------------------------------
# Phase resolvers
# ---------------------------------------------------------------------------

def _resolve_return_home(state: GameState) -> GameState:
    """End-of-round bookkeeping: reset worker placements, return people
    home. Does NOT clear newborns (those need to survive to HARVEST_FEED
    for the 1-food discount; clearing happens in _resolve_preparation of
    the next round). Does NOT increment round_number (that happens in
    _resolve_preparation).

    Transitions to PREPARATION for ongoing rounds, or to BEFORE_SCORING
    after round 4 in Task 5.
    """
    # Future: card triggers fire here ("when you return home from
    # action space X, may do Y"). Stub for Task 5.

    # 1. Reset every action space's worker tuple. Unrevealed spaces
    #    already have workers=(0, 0); the reset is a no-op for them.
    new_spaces = {
        space_id: dataclasses.replace(action_space, workers=(0, 0))
        for space_id, action_space in state.board.action_spaces.items()
    }
    new_board = dataclasses.replace(state.board, action_spaces=new_spaces)

    # 2. Return all people home. Newborns NOT cleared here.
    new_players = tuple(
        dataclasses.replace(p, people_home=p.people_total)
        for p in state.players
    )

    state = dataclasses.replace(state, players=new_players, board=new_board)

    # 3. Decide next phase.
    # Task 5: halt after round 4 (harvest is unimplemented).
    if state.round_number >= 4:
        return dataclasses.replace(state, phase=Phase.BEFORE_SCORING)

    # TODO: when the harvest is implemented, on HARVEST_ROUNDS (4, 7, 9,
    # 11, 13, 14) this should transition to Phase.HARVEST_FIELD instead
    # of Phase.PREPARATION. The harvest itself (Field/Feed/Breed) is a
    # distinct multi-phase entity with its own resolvers and player
    # decisions; _resolve_return_home only triggers the transition, it
    # does NOT run any harvest logic. After the harvest completes, the
    # game transitions to Phase.PREPARATION for the next round (rounds
    # 1–13), or directly to Phase.BEFORE_SCORING (after round 14's
    # HARVEST_BREED).
    return dataclasses.replace(state, phase=Phase.PREPARATION)


def _resolve_preparation(state: GameState) -> GameState:
    """Set up the new round: increment round_number, refill revealed
    accumulation spaces, distribute future_resources for this round,
    clear newborns, and reset current_player to starting_player.

    Not called for round 1 (setup pre-loads round-1 accumulation goods
    and the engine starts at Phase.WORK).
    """
    # Future: card triggers fire here ("at the start of each round, may
    # do X"). Stub for Task 5.

    new_round = state.round_number + 1

    # 1. Refill revealed accumulation spaces. After incrementing the
    #    round counter, the comparison `round_revealed <= new_round`
    #    correctly identifies the just-revealed stage card too.
    new_spaces = dict(state.board.action_spaces)
    for space_id, action_space in list(new_spaces.items()):
        if action_space.round_revealed > new_round:
            continue   # not yet revealed
        if space_id in BUILDING_ACCUMULATION_RATES:
            rate = BUILDING_ACCUMULATION_RATES[space_id]
            new_spaces[space_id] = dataclasses.replace(
                action_space,
                accumulated=action_space.accumulated + rate,
            )
        elif space_id in FOOD_ANIMAL_ACCUMULATION_RATES:
            _, rate = FOOD_ANIMAL_ACCUMULATION_RATES[space_id]
            new_spaces[space_id] = dataclasses.replace(
                action_space,
                accumulated_amount=action_space.accumulated_amount + rate,
            )
    new_board = dataclasses.replace(state.board, action_spaces=new_spaces)

    # 2. Per-player: distribute future_resources, clear newborns.
    idx = new_round - 1
    new_players = tuple(
        dataclasses.replace(
            p,
            resources=p.resources + p.future_resources[idx],
            future_resources=(
                p.future_resources[:idx]
                + (Resources(),)
                + p.future_resources[idx + 1:]
            ),
            newborns=0,
        )
        for p in state.players
    )

    # 3. Transition to WORK with starting_player as the active player.
    return dataclasses.replace(
        state,
        round_number=new_round,
        players=new_players,
        board=new_board,
        phase=Phase.WORK,
        current_player=state.starting_player,
    )
