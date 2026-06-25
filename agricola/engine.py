"""Game-state transition engine.

Public API: `step(state, action) -> GameState`. Pure transition function;
the loop that drives a game lives outside this module (typically in the
agent loop / test harness).

See ENGINE_IMPLEMENTATION.md §1 (Engine structure & dispatch) for the full
design rationale and TASK_5.md for the implementation breakdown.
"""
from __future__ import annotations

import dataclasses

from agricola.actions import (
    Action,
    ChooseSubAction,
    CommitAccommodate,
    CommitBake,
    CommitBreed,
    CommitBuildMajor,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitFamilyGrowth,
    CommitHarvestConversion,
    CommitPlayMinor,
    CommitPlayOccupation,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    CommitSubAction,
    FireTrigger,
    PlaceWorker,
    RevealCard,
    Stop,
)
from agricola.constants import (
    BUILDING_ACCUMULATION_RATES,
    FOOD_ANIMAL_ACCUMULATION_RATES,
    HARVEST_ROUNDS,
    NUM_ROUNDS,
    SPACE_IDS,
    STAGE_CARDS,
    CellType,
    GameMode,
    Phase,
)
from agricola.pending import (
    PendingBakeBread,
    PendingBuildFences,
    PendingBuildRooms,
    PendingBuildStables,
    PendingBuildMajor,
    PendingCattleMarket,
    PendingFamilyGrowth,
    PendingHarvestBreed,
    PendingHarvestFeed,
    PendingPigMarket,
    PendingPlayMinor,
    PendingPlayOccupation,
    PendingPlow,
    PendingRenovate,
    PendingReveal,
    PendingSheepMarket,
    PendingSow,
    pop,
    push,
    replace_top,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space, with_space
from agricola.resolution import (
    ATOMIC_HANDLERS,
    CHOOSE_SUBACTION_HANDLERS,
    NONATOMIC_HANDLERS,
    _apply_worker_placement,
    _execute_accommodate,
    _execute_bake,
    _execute_breed,
    _execute_build_major,
    _execute_build_pasture,
    _execute_build_room,
    _execute_build_stable,
    _execute_convert,
    _execute_family_growth,
    _execute_harvest_conversion,
    _execute_play_minor,
    _execute_play_occupation,
    _execute_plow,
    _execute_renovate,
    _execute_sow,
    _update_player,
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
      - RuntimeError if state.phase == Phase.BEFORE_SCORING.
      - NotImplementedError only as a defensive guard if a PlaceWorker
        targets a space without registered handlers (should not happen for
        any space surfaced by legal_placements).
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

    # 4. Engine invariant: no player has negative resources or animals.
    #    `Resources.__sub__` / `__add__` intentionally allow negative result
    #    components (no clamping — it would be tedious to special-case every
    #    operator); `Animals` has no arithmetic operators, so negative animal
    #    counts arise only from direct construction in effect code. Either
    #    way the check has to live at a transition boundary.
    #    Catching the violation here, at the end of every step(), gives the
    #    tightest possible bug-localization: the assertion message names the
    #    action and the player, so the offending sub-action effect or
    #    enumerator gate is one source-grep away.
    #
    #    Gated on `__debug__` so `python -O` (or PYTHONOPTIMIZE=1) strips the
    #    check entirely for production / self-play / training. Tests, CI, and
    #    interactive dev all run unoptimized — the safety net stays live there.
    #    See PROFILING.md R2 for the rationale.
    if __debug__:
        _assert_nonnegative_state(state, action)

    return state


def _assert_nonnegative_state(state: GameState, action: Action) -> None:
    """Verify all players' resources and animals are non-negative.

    Engine-level safety net. Should never fire in correct code; if it does,
    the action immediately preceding is the prime suspect (a sub-action
    effect debited without a matching legality / affordability gate, or a
    multi-shot enumerator emitted an option past the affordability frontier).
    """
    for p_idx, p in enumerate(state.players):
        r = p.resources
        for fld in ("wood", "clay", "reed", "stone", "food", "grain", "veg"):
            val = getattr(r, fld)
            assert val >= 0, (
                f"Engine invariant violated after action {action!r}: "
                f"player {p_idx} resources.{fld} = {val} (must be >= 0)."
            )
        a = p.animals
        for fld in ("sheep", "boar", "cattle"):
            val = getattr(a, fld)
            assert val >= 0, (
                f"Engine invariant violated after action {action!r}: "
                f"player {p_idx} animals.{fld} = {val} (must be >= 0)."
            )


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
    if isinstance(action, RevealCard):
        return _apply_reveal_card(state, action)
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
    # CommitBuildPasture: auto_pop=False (multi-shot). The effect function
    # increments PendingBuildFences's counters via replace_top and leaves
    # the pending on the stack; Stop pops it.
    CommitBuildPasture: (PendingBuildFences,  _execute_build_pasture, False),
    # Harvest sub-actions (Task 7). All auto_pop=False — the trailing Stop is
    # the explicit exit. PendingHarvestFeed hosts both CommitHarvestConversion
    # (zero or more) and CommitConvert (exactly one), with `conversion_done`
    # gating Stop.
    CommitHarvestConversion: (PendingHarvestFeed,  _execute_harvest_conversion, False),
    CommitConvert:           (PendingHarvestFeed,  _execute_convert,            False),
    CommitBreed:             (PendingHarvestBreed, _execute_breed,              False),
    # Card game: play one occupation from hand. auto_pop=True — Lessons plays
    # exactly one occupation, then PendingPlayOccupation pops and the turn ends.
    CommitPlayOccupation:    (PendingPlayOccupation, _execute_play_occupation,  True),
    # Card game: play one minor from hand. auto_pop=True — one minor played, then
    # PendingPlayMinor pops; declining is the frame's Stop (also pops).
    CommitPlayMinor:         (PendingPlayMinor,      _execute_play_minor,       True),
    # Card game: the family-growth primitive (mandatory; parameter-free singleton).
    CommitFamilyGrowth:      (PendingFamilyGrowth,   _execute_family_growth,    True),
}


def _apply_place_worker(state: GameState, action: PlaceWorker) -> GameState:
    # Cross-cutting bookkeeping: workers, people_home.
    state = _apply_worker_placement(state, action.space)

    if action.space in ATOMIC_HANDLERS:
        return ATOMIC_HANDLERS[action.space](state)

    if action.space in NONATOMIC_HANDLERS:
        return NONATOMIC_HANDLERS[action.space](state)

    # Defensive backstop: every space in SPACE_IDS now has a handler (atomic or
    # non-atomic) in both game modes — `lessons` (card-game occupation play)
    # included — so this is unreachable for a valid id, and an UNKNOWN id fails
    # earlier at the SPACE_INDEX lookup in `_apply_worker_placement`. Kept to
    # guard a future space added to SPACE_IDS without a registered handler.
    raise NotImplementedError(
        f"No handler registered for space {action.space!r}"
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
    new_top = fast_replace(
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
# Scoped used-set reset (CARD_IMPLEMENTATION_PLAN.md II.3)
# ---------------------------------------------------------------------------

def _clear(state: GameState, field: str) -> GameState:
    """Empty the named scoped used-set on BOTH players at a scope boundary.

    Clears both players (not just the active one) because an off-turn card
    firing must see a fresh latch too. A NO-OP when both players' sets are
    already empty — the Family game never populates these, so this returns the
    same `state` object every time there and is byte-identical; only a card game
    that actually latched something pays the rebuild.
    """
    if not any(getattr(p, field) for p in state.players):
        return state
    return fast_replace(state, players=tuple(
        fast_replace(p, **{field: frozenset()}) for p in state.players))


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

    A turn boundary clears the per-turn used-set (II.3) so card "once per turn"
    latches reset for the incoming turn.
    """
    state = _clear(state, "used_this_turn")
    num_players = len(state.players)
    for offset in range(1, num_players):
        candidate = (state.current_player + offset) % num_players
        if state.players[candidate].people_home > 0:
            return fast_replace(state, current_player=candidate)
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

        # Case 2: PREPARATION phase, around the round-card reveal. Two-state,
        # discriminated by the `count == round_number` invariant (round_number
        # still names the round just completed; the reveal is deferred to the
        # RevealCard step, the increment to _complete_preparation):
        #   - card not up yet (count == round_number): push the reveal nature
        #     node; Case 1 returns on the non-empty stack next iteration.
        #   - card up (count > round_number): finish the round setup.
        if state.phase == Phase.PREPARATION:
            if _count_revealed_stage_cards(state) == state.round_number:
                state = push(state, PendingReveal())
            else:
                state = _complete_preparation(state)
            continue

        # Case 3: WORK phase. If any player has workers, an agent decision
        # is awaiting. If neither does, the work phase ends.
        if state.phase == Phase.WORK:
            if all(p.people_home == 0 for p in state.players):
                state = fast_replace(state, phase=Phase.RETURN_HOME)
                continue
            return state

        # Case 4: RETURN_HOME phase. End-of-round bookkeeping.
        if state.phase == Phase.RETURN_HOME:
            state = _resolve_return_home(state)
            continue

        # Case 5: HARVEST_FIELD phase. _resolve_harvest_field does the
        # mechanical FIELD work, resets harvest_conversions_used, pushes FEED
        # pendings, and transitions to HARVEST_FEED. After it returns the
        # stack is non-empty and the outer guard exits on the next iteration.
        if state.phase == Phase.HARVEST_FIELD:
            state = _resolve_harvest_field(state)
            continue

        # Case 6: HARVEST_FEED with empty stack = exit signal. All FEED
        # pendings have been Stop'd. Push BREED pendings and transition.
        if state.phase == Phase.HARVEST_FEED:
            state = _initiate_harvest_breed(state)
            state = fast_replace(state, phase=Phase.HARVEST_BREED)
            continue

        # Case 7: HARVEST_BREED with empty stack = exit signal. Transition
        # to PREPARATION (round < 14) or BEFORE_SCORING (round == 14).
        if state.phase == Phase.HARVEST_BREED:
            if state.round_number >= NUM_ROUNDS:
                state = fast_replace(state, phase=Phase.BEFORE_SCORING)
            else:
                state = fast_replace(state, phase=Phase.PREPARATION)
            continue

        # Case 8: terminal phase. No more steps possible.
        if state.phase == Phase.BEFORE_SCORING:
            return state

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

    # 1. Reset every action space's worker tuple. Unrevealed spaces and any
    #    space no worker landed on this round already have workers=(0, 0);
    #    skip the replace for those so we don't construct identical objects.
    #    Without this guard, every round reconstructs all 25 ActionSpaceStates
    #    even though typically only ~8 actually had workers on them (one per
    #    worker placement that round); profiling showed this was the single
    #    most frequent `dataclasses.replace` call shape in the engine.
    new_spaces = tuple(
        fast_replace(action_space, workers=(0, 0))
        if action_space.workers != (0, 0)
        else action_space
        for action_space in state.board.action_spaces
    )
    new_board = fast_replace(state.board, action_spaces=new_spaces)

    # 2. Return all people home. Newborns NOT cleared here.
    new_players = tuple(
        fast_replace(p, people_home=p.people_total)
        for p in state.players
    )

    state = fast_replace(state, players=new_players, board=new_board)

    # 3. Decide next phase.
    # On a HARVEST_ROUND (4, 7, 9, 11, 13, 14), route to HARVEST_FIELD. The
    # harvest sub-phases (Field/Feed/Breed) own their own transitions and
    # eventually land back in PREPARATION (rounds 1–13) or BEFORE_SCORING
    # (after round 14's HARVEST_BREED — handled in _advance_until_decision).
    if state.round_number in HARVEST_ROUNDS:
        return fast_replace(state, phase=Phase.HARVEST_FIELD)

    return fast_replace(state, phase=Phase.PREPARATION)


def _count_revealed_stage_cards(state: GameState) -> int:
    """Number of stage cards turned up so far (permanents excluded — they are
    always revealed). Equals `round_number` at every WORK decision state: the
    `count == round_number` invariant that drives the PREPARATION two-state walk
    (push reveal vs. complete prep). See HIDDEN_INFO_DESIGN.md §4.3.
    """
    return sum(
        1
        for cards in STAGE_CARDS.values()
        for card_id in cards
        if get_space(state.board, card_id).revealed
    )


def _apply_reveal_card(state: GameState, action: RevealCard) -> GameState:
    """Turn up the named stage card and pop the PendingReveal frame.

    Does ONE thing: set `revealed=True` and pop. It leaves `phase = PREPARATION`
    and does NOT touch round_number / current_player / accumulation — those are
    `_complete_preparation`'s job, run afterwards in the system walk (so the
    `step` alternation guard, which only fires in WORK, is untouched). See
    HIDDEN_INFO_DESIGN.md §4.3–4.4.
    """
    sp = get_space(state.board, action.card)
    new_board = with_space(state.board, action.card, fast_replace(sp, revealed=True))
    return pop(fast_replace(state, board=new_board))


def _complete_preparation(state: GameState) -> GameState:
    """Finish setting up the round whose card has just been revealed.

    Runs in `_advance_until_decision` Case 2 once the round-card reveal has fired
    (count > round_number). Increments round_number, refills every revealed
    accumulation space, distributes future_resources for the new round, clears
    newborns, and transitions to WORK with starting_player active. (Replaces the
    old monolithic `_resolve_preparation`, whose implicit "refill where
    round_revealed <= new_round" reveal is now the explicit RevealCard step;
    this is the post-reveal remainder.)
    """
    # Future: card triggers fire here ("at the start of each round, may do X").

    new_round = state.round_number + 1

    # 1. Refill every revealed accumulation space (the just-revealed card
    #    included — its `revealed` was set by _apply_reveal_card).
    new_spaces_list = list(state.board.action_spaces)
    for i, action_space in enumerate(new_spaces_list):
        if not action_space.revealed:
            continue
        space_id = SPACE_IDS[i]
        # Card-game Meeting Place gives no food, so it is NOT an accumulation
        # space there (reused slot); skip its refill in card mode. Family is
        # unchanged (it accumulates +1 food/round as before).
        if space_id == "meeting_place" and state.mode is GameMode.CARDS:
            continue
        if space_id in BUILDING_ACCUMULATION_RATES:
            rate = BUILDING_ACCUMULATION_RATES[space_id]
            new_spaces_list[i] = fast_replace(
                action_space,
                accumulated=action_space.accumulated + rate,
            )
        elif space_id in FOOD_ANIMAL_ACCUMULATION_RATES:
            _, rate = FOOD_ANIMAL_ACCUMULATION_RATES[space_id]
            new_spaces_list[i] = fast_replace(
                action_space,
                accumulated_amount=action_space.accumulated_amount + rate,
            )
    new_board = fast_replace(state.board, action_spaces=tuple(new_spaces_list))

    # 2. Per-player: distribute future_resources, clear newborns.
    idx = new_round - 1
    new_players = tuple(
        fast_replace(
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
    result = fast_replace(
        state,
        round_number=new_round,
        players=new_players,
        board=new_board,
        phase=Phase.WORK,
        current_player=state.starting_player,
    )
    # New round begins → clear the per-round and (fresh first turn) per-turn
    # used-sets (II.3). No-op in the Family game (both always empty).
    result = _clear(result, "used_this_round")
    result = _clear(result, "used_this_turn")
    return result


# ---------------------------------------------------------------------------
# Harvest phase resolvers (Task 7)
# ---------------------------------------------------------------------------

def _initiate_harvest_feed(state: GameState) -> GameState:
    """Push a PendingHarvestFeed for each player, starting player's frame on top.

    No food is debited here. Food payment is deferred to `CommitConvert`
    (see `_execute_convert` in resolution.py), and the "Cannot withhold
    food tokens" rule is enforced there by paying `min(need, available)`
    unconditionally — the player has no knob to keep food while begging.

    Push order: non-starting player pushed first (bottom of stack), starting
    player pushed second (top). When the starting player Stops, the
    non-starting player's pending becomes top automatically.

    Also exposed standalone so tests can construct a FEED-only state without
    running FIELD mechanics.
    """
    sp = state.starting_player
    push_order = [(sp + 1) % 2, sp]

    for idx in push_order:
        state = push(state, PendingHarvestFeed(
            player_idx=idx,
            initiated_by_id="phase:harvest_feed",
        ))

    return state


def _initiate_harvest_breed(state: GameState) -> GameState:
    """Push a PendingHarvestBreed for each player, starting player's frame on top.

    No pre-debit (breeding doesn't consume food upfront). Push order
    mirrors _initiate_harvest_feed.
    """
    sp = state.starting_player
    push_order = [(sp + 1) % 2, sp]

    for idx in push_order:
        state = push(state, PendingHarvestBreed(
            player_idx=idx,
            initiated_by_id="phase:harvest_breed",
        ))

    return state


def _resolve_harvest_field(state: GameState) -> GameState:
    """Mechanical FIELD work + reset once-per-harvest budget + push FEED
    pendings + transition phase. Called by _advance_until_decision when
    phase == HARVEST_FIELD.

    Three concerns combined (mirrors _resolve_preparation's multi-concern
    shape — justified in TASK_7 Part 2.1):

    1. Mechanical: take 1 crop from each planted field. Grain takes
       precedence over veg per RULES.md (a field is sown with one or the
       other, never both — the elif fallback handles a veg-sown field).
    2. Reset harvest_conversions_used on both players so FEED starts with
       a fresh once-per-harvest budget.
    3. Push FEED pendings via _initiate_harvest_feed and set
       phase=HARVEST_FEED. After this returns, the stack is non-empty
       (one frame per player) and the outer guard returns control to the
       agent.
    """
    new_players = []
    for p in state.players:
        grain_gain = 0
        veg_gain   = 0
        new_grid_rows = []
        for r in range(3):
            new_row = []
            for c in range(5):
                cell = p.farmyard.grid[r][c]
                if cell.cell_type == CellType.FIELD:
                    if cell.grain > 0:
                        grain_gain += 1
                        new_row.append(fast_replace(cell, grain=cell.grain - 1))
                    elif cell.veg > 0:
                        veg_gain += 1
                        new_row.append(fast_replace(cell, veg=cell.veg - 1))
                    else:
                        new_row.append(cell)   # empty field (already harvested or never sown)
                else:
                    new_row.append(cell)
            new_grid_rows.append(tuple(new_row))
        new_grid = tuple(new_grid_rows)

        # Fields cannot lie inside pastures, so the pasture cache is preserved
        # via dataclasses.replace's natural ride-along.
        new_farmyard = fast_replace(p.farmyard, grid=new_grid)
        new_resources = p.resources + Resources(grain=grain_gain, veg=veg_gain)
        new_players.append(fast_replace(
            p,
            farmyard=new_farmyard,
            resources=new_resources,
            harvest_conversions_used=frozenset(),
        ))

    state = fast_replace(state, players=tuple(new_players))

    # Push FEED pendings (one per player, SP on top, food pre-debited) and
    # transition phase. The outer guard returns on the next iteration because
    # the stack is now non-empty.
    state = _initiate_harvest_feed(state)
    return fast_replace(state, phase=Phase.HARVEST_FEED)
