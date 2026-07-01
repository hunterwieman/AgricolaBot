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
    CommitCardChoice,
    CommitChooseCost,
    CommitConvert,
    CommitFoodPayment,
    CommitDraftPick,
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
    Proceed,
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
    ACTION_SPACE_PENDING_IDS,
    SUBACTION_PENDING_IDS,
    PendingActionSpace,
    PendingBakeBread,
    PendingBuildFences,
    PendingBuildRooms,
    PendingBuildStables,
    PendingBuildMajor,
    PendingCattleMarket,
    PendingChooseCost,
    PendingDraftPick,
    PendingFamilyGrowth,
    PendingFoodPayment,
    PendingHarvestBreed,
    PendingHarvestFeed,
    PendingHarvestField,
    PendingPigMarket,
    PendingPlayMinor,
    PendingPlayOccupation,
    PendingCardChoice,
    PendingPlow,
    PendingPreparation,
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
from agricola.state import FutureReward, GameState, get_space, with_space
from agricola.resolution import (
    ATOMIC_HANDLERS,
    CHOOSE_SUBACTION_HANDLERS,
    NONATOMIC_HANDLERS,
    _apply_worker_placement,
    _enter_after_phase,
    _execute_accommodate,
    _execute_bake,
    _execute_breed,
    _execute_build_major,
    _execute_build_pasture,
    _execute_build_room,
    _execute_build_stable,
    _execute_choose_cost,
    _execute_convert,
    _execute_family_growth,
    _execute_food_payment,
    _execute_harvest_conversion,
    _execute_play_minor,
    _execute_play_occupation,
    _execute_plow,
    _initiate_meeting_place_cards,
    _execute_renovate,
    _execute_sow,
    _update_player,
)

# Ensure card registrations run at engine-module load time.
import agricola.cards  # noqa: F401
# The action-space hook surface (II.2): apply_auto_effects fires mandatory
# automatic effects at a hook; should_host_space decides whether an atomic
# placement is hosted by a PendingActionSpace frame. Both are no-ops on the
# Family fast path (empty registries). cards.triggers is a leaf module — safe
# to import here without a load-order cycle.
from agricola.cards.triggers import (
    apply_auto_effects,
    should_host_harvest_field,
    should_host_space,
)


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

    # The start-of-round phase hook (II.6, card-only) resolves its
    # PendingPreparation / PendingCardChoice frames while phase==WORK (they sit on
    # the stack after `_complete_preparation` flips to WORK). Resolving one is NOT a
    # worker-placement turn, so it must NOT trigger the worker alternation in step 2.
    # Detect it from the PRE-action top frame (the frame is popped by the action).
    _resolving_prep = bool(state.pending_stack) and isinstance(
        state.pending_stack[-1], (PendingPreparation, PendingCardChoice)
    )

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
    #
    #    `_resolving_prep` extends that guard to the start-of-round hook: a
    #    PendingPreparation/PendingCardChoice resolution empties the stack in WORK
    #    but is not a worker turn, so it must not alternate (the starting player must
    #    still take the round's first worker turn).
    if state.phase == Phase.WORK and not state.pending_stack and not _resolving_prep:
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
    if isinstance(action, CommitCardChoice):
        return _apply_commit_card_choice(state, action)
    if isinstance(action, CommitSubAction):
        return _apply_commit_subaction(state, action)
    if isinstance(action, FireTrigger):
        return _apply_fire_trigger(state, action)
    if isinstance(action, Stop):
        return _apply_stop(state)
    if isinstance(action, Proceed):
        return _apply_proceed(state)
    if isinstance(action, CommitDraftPick):
        return _apply_draft_pick(state, action)
    if isinstance(action, RevealCard):
        return _apply_reveal_card(state, action)
    raise TypeError(f"Unknown action type: {type(action).__name__}")


# Metadata dispatch table for Commit* sub-actions. Each entry maps a
# CommitSubAction subclass to:
#   (expected_pending_type, effect_fn)
# Co-located with its sole consumer (_apply_commit_subaction below).
#
# The dispatcher NEVER pops — the effect function owns ALL stack manipulation.
# Every commit-terminated host pivots to its after-phase (via _enter_after_phase)
# so cards can surface after-triggers + fire after-automatic effects, and the
# trailing Stop pops; multi-shot hosts replace_top and Stop pops. (There used to
# be a per-entry `auto_pop` flag; it was always False once every sub-action became
# a uniform before/after host, so it was removed — see SUBACTION_HOOK_REFACTOR.md.)
#
# Adding a new sub-action: define a new CommitX subclass + an
# `_execute_x(state, player_idx, commit)` in resolution.py + a row here.
COMMIT_SUBACTION_HANDLERS: dict[type, tuple] = {
    # Commit-terminated sub-action HOSTS (SUBACTION_HOOK_REFACTOR.md): their effect
    # pivots the host frame to its after-phase (via _enter_after_phase); the
    # trailing Stop pops. Uniform before/after host for card hooks.
    CommitSow:          (PendingSow,          _execute_sow),
    CommitBake:         (PendingBakeBread,    _execute_bake),
    CommitPlow:         (PendingPlow,         _execute_plow),
    CommitBuildStable:  (PendingBuildStables, _execute_build_stable),
    CommitBuildRoom:    (PendingBuildRooms,   _execute_build_room),
    CommitRenovate:     (PendingRenovate,     _execute_renovate),
    # CommitChooseCost (card game two-step): lands on PendingChooseCost; the effect
    # debits the chosen payment and POPS the frame itself, returning to the build host.
    CommitChooseCost:   (PendingChooseCost,   _execute_choose_cost),
    # CommitAccommodate lands on any of three market parent pendings.
    # `isinstance` handles tuple-of-types natively in _apply_commit_subaction.
    # The effect pivots the host to its after-phase; the trailing Stop pops.
    CommitAccommodate:  (
        (PendingSheepMarket, PendingPigMarket, PendingCattleMarket),
        _execute_accommodate,
    ),
    # CommitBuildMajor: the effect function owns its own conditional stack
    # manipulation — pop PendingBuildMajor for non-oven majors, or push
    # PendingClayOven / PendingStoneOven (leaving PendingBuildMajor on the stack
    # underneath) for ovens.
    CommitBuildMajor:   (PendingBuildMajor,   _execute_build_major),
    # CommitBuildPasture (multi-shot): the effect increments PendingBuildFences's
    # counters via replace_top and leaves the pending in its before-phase; Proceed
    # flips to the after-phase (firing after_build_fences autos), then Stop pops.
    CommitBuildPasture: (PendingBuildFences,  _execute_build_pasture),
    # Harvest sub-actions (Task 7): the trailing Stop is the explicit exit.
    # PendingHarvestFeed hosts both CommitHarvestConversion (zero or more) and
    # CommitConvert (exactly one), with `conversion_done` gating Stop.
    CommitHarvestConversion: (PendingHarvestFeed,  _execute_harvest_conversion),
    CommitConvert:           (PendingHarvestFeed,  _execute_convert),
    CommitBreed:             (PendingHarvestBreed, _execute_breed),
    # Card game: play one occupation from hand. The effect plays the occupation
    # then pivots PendingPlayOccupation to its after-phase (hosting e.g. Bread
    # Paddle on after_play_occupation); the trailing Stop pops.
    CommitPlayOccupation:    (PendingPlayOccupation, _execute_play_occupation),
    # Card game: play one minor from hand. The effect plays the minor then pivots
    # PendingPlayMinor to its after-phase; the trailing Stop pops.
    CommitPlayMinor:         (PendingPlayMinor,      _execute_play_minor),
    # Card game: the family-growth primitive (mandatory; parameter-free singleton).
    # The effect pivots PendingFamilyGrowth to its after-phase; the trailing Stop pops.
    CommitFamilyGrowth:      (PendingFamilyGrowth,   _execute_family_growth),
    # Card game: raise food to pay a food cost (FOOD_PAYMENT_DESIGN.md). The effect applies
    # the chosen conversion bundle, debits the cost, POPS PendingFoodPayment itself, and
    # resumes the play (play_minor / play_occupation body) — a closed frame, no trailing Stop.
    CommitFoodPayment:       (PendingFoodPayment,    _execute_food_payment),
}


def _apply_place_worker(state: GameState, action: PlaceWorker) -> GameState:
    # Cross-cutting bookkeeping: workers, people_home.
    state = _apply_worker_placement(state, action.space)

    # Card-mode Meeting Place is a non-atomic, SELF-HOSTING space: its handler pushes
    # a PendingMeetingPlace frame that fires before_/after_action_space on its own
    # lifecycle (before at push, after at the Proceed flip). It must therefore NOT
    # enter the generic atomic-host wrapper below — that path is for TRULY-atomic
    # spaces whose handler does not push, and wrapping the pushing meeting-place
    # handler in a second generic PendingActionSpace host produces a double-host that
    # soft-locks the turn (an infinite Proceed<->Stop cycle) the moment any card hooks
    # the space. Dispatch it directly here, ahead of should_host_space. (Family
    # Meeting Place stays atomic — _resolve_meeting_place via ATOMIC_HANDLERS below.)
    if action.space == "meeting_place" and state.mode is GameMode.CARDS:
        return _initiate_meeting_place_cards(state)

    if action.space in ATOMIC_HANDLERS:
        # Card game (II.2): if a card could fire on this atomic space, HOST it
        # with a generic PendingActionSpace frame (before-phase) and fire any
        # before-automatic-effects, instead of running the atomic effect now —
        # the effect runs later at Proceed. Family game: should_host_space is
        # always False (empty hook indexes) → today's atomic fast path, unchanged.
        ap = state.current_player
        if should_host_space(state, action.space, ap):
            state = push(state, PendingActionSpace(
                player_idx=ap, initiated_by_id=f"space:{action.space}"))
            return apply_auto_effects(state, "before_action_space", ap)
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


def _fire_subaction_before_auto(state: GameState) -> GameState:
    """If the stack's top is a commit-terminated sub-action leaf in its before-phase,
    fire its `before_<PENDING_ID>` automatic effects (SUBACTION_HOOK_REFACTOR.md §4d).

    The single central seam for sub-action before-autos — symmetric with
    `_apply_place_worker` firing `before_action_space` when it pushes a space host,
    and with `_enter_after_phase` firing the after-autos at the commit-flip. Called
    at the two engine chokepoints where a sub-action leaf can be pushed: after a
    `_choose_subaction_*` handler runs (`_apply_choose_sub_action`) and after a
    trigger's `apply_fn` runs (`_apply_fire_trigger`, the card-grant push path —
    Assistant Tiller → PendingPlow, Threshing Board / Oven Firing Boy → PendingBakeBread).

    Gated on `SUBACTION_PENDING_IDS` so it fires only for the sub-action host leaves,
    never for a composite host (`PendingMajorMinorImprovement`, which fires its own
    `before_major_minor_improvement`). A no-op in the Family game (empty AUTO_EFFECTS)
    → byte-identical state.
    """
    if not state.pending_stack:
        return state
    top = state.pending_stack[-1]
    if type(top).PENDING_ID not in SUBACTION_PENDING_IDS:
        return state
    # A sub-action leaf is pushed in its before-phase; fire its before-autos there.
    return apply_auto_effects(
        state, f"before_{type(top).PENDING_ID}", top.player_idx,
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
    # The handler pushes the chosen sub-action's frame (or, for the composite/
    # Proceed paths, a non-leaf frame). If that new top is a commit-terminated
    # sub-action leaf, fire its before-automatic effects at this push.
    return _fire_subaction_before_auto(handler(state, action))


def _apply_commit_subaction(
    state: GameState, action: CommitSubAction,
) -> GameState:
    """Generic handler for any CommitSubAction subclass.

    Looks up `(expected_pending_type, effect_fn)` in `COMMIT_SUBACTION_HANDLERS`,
    asserts the expected pending is on top, and applies the effect. The dispatcher
    NEVER pops — the effect function is responsible for ALL stack manipulation it
    needs (pivot to after-phase via `_enter_after_phase`, push a wrapper,
    replace_top, etc.). The trailing Stop pops the host.

    Parent `*_chosen` flags are set earlier, by the `_choose_subaction_*`
    handler that pushed the sub-action pending. This dispatcher does not
    touch parent state.
    """
    assert state.pending_stack, (
        f"{type(action).__name__} called with empty pending_stack"
    )
    pending_type, effect_fn = COMMIT_SUBACTION_HANDLERS[type(action)]
    top = state.pending_stack[-1]
    assert isinstance(top, pending_type), (
        f"{type(action).__name__} expected top={pending_type.__name__}, "
        f"got {type(top).__name__}"
    )
    return effect_fn(state, top.player_idx, action)


def _apply_fire_trigger(
    state: GameState, action: FireTrigger,
) -> GameState:
    from agricola.cards.triggers import CARDS  # local import to avoid load-order surprises
    assert state.pending_stack, "FireTrigger called with empty pending_stack"
    top = state.pending_stack[-1]
    entry = CARDS[action.card_id]
    # Record the fire on the HOST frame FIRST, then apply. A granted-sub-action
    # trigger's apply_fn (Category 4: Assistant Tiller, Oven Firing Boy, …) PUSHES
    # a primitive pending — recording after the push would replace_top the wrong
    # (just-pushed) frame. Recording first keeps the host on top while we stamp
    # triggers_resolved, then apply_fn pushes its sub-decision on top of it. For a
    # non-pushing trigger (Potter, Mushroom) the order swap is end-state-identical.
    new_top = fast_replace(
        top, triggers_resolved=top.triggers_resolved | {action.card_id},
    )
    state = replace_top(state, new_top)
    # A granted-sub-action trigger (Category 4) PUSHES a sub-action leaf primitive
    # (Assistant Tiller → PendingPlow; Threshing Board / Oven Firing Boy →
    # PendingBakeBread). If apply_fn left such a leaf on top, fire its
    # before-automatic effects at this push (the same seam as ChooseSubAction).
    #
    # A play-variant trigger (Scholar) surfaces FireTriggers carrying a `variant`
    # and its apply_fn takes `(state, idx, variant)`; thread it through only when a
    # variant is present so every plain `(state, idx)` apply_fn is unaffected.
    if action.variant is not None:
        applied = entry.apply_fn(state, new_top.player_idx, action.variant)
    else:
        applied = entry.apply_fn(state, new_top.player_idx)
    return _fire_subaction_before_auto(applied)


def _apply_commit_card_choice(
    state: GameState, action: CommitCardChoice,
) -> GameState:
    """Resolve a CommitCardChoice at a PendingCardChoice frame (card game only).

    The frame names the pushing card via its `initiated_by_id` ("card:<id>"); the
    chosen option is `options[action.index]`. Dispatches to that card's registered
    resolver (CARD_CHOICE_RESOLVERS), which applies the option and pops the frame
    (the resolver owns its stack, mirroring trigger apply_fns). Card-only path —
    never reached in the Family game.
    """
    from agricola.cards.triggers import CARD_CHOICE_RESOLVERS

    assert state.pending_stack, "CommitCardChoice called with empty pending_stack"
    top = state.pending_stack[-1]
    assert isinstance(top, PendingCardChoice), (
        f"CommitCardChoice expected PendingCardChoice on top, got {type(top).__name__}"
    )
    card_id = top.initiated_by_id.split(":", 1)[1]
    chosen = top.options[action.index]
    resolver = CARD_CHOICE_RESOLVERS[card_id]
    return resolver(state, top.player_idx, chosen)


def _apply_stop(state: GameState) -> GameState:
    assert state.pending_stack, "Stop called with empty pending_stack"
    # Pure pop (SPACE_HOST_REFACTOR.md §11). Every host's after-automatic effects
    # fire at its own work-complete boundary (Proceed for atomic/Proceed-hosts and
    # the multi-shot builders, the commit for the markets, the auto-advance for
    # Delegating hosts) — BEFORE its after-triggers, fixing the §2 ordering bug — so
    # Stop only ever pops. Do NOT assert the stack is empty afterward: future cards
    # may have deeper stacks where Stop is legal at a non-bottom frame.
    #
    # NOTE: there is deliberately NO "end of turn" firing here. The space-host pop
    # coincides with turn-end only because nothing player-controllable currently sits
    # between the action's resolution and the turn ending; once "at any time" card
    # effects add such a window, an end-of-turn hook fired here would land one window
    # too early (goods would be spendable within the turn). So end-of-turn effects
    # (and Firewood Collector) are DEFERRED until a real post-at-any-time turn-end
    # boundary exists. See CARD_IMPLEMENTATION_PLAN.md (Firewood / end-of-turn).
    return pop(state)


def _settle_build_fences(state: GameState) -> GameState:
    """Pay the deferred Build Fences bill (CARDS only) at the Proceed work-complete
    flip, BEFORE the after-grants fire (COST_MODIFIER_DESIGN.md §9.2 — the settle ->
    pay -> grants order).

    The top frame is a before-phase `PendingBuildFences` whose `accrued_cost` is the
    running wood owed across this action's pasture commits (after per-action frees,
    §9.4). Resolve the whole-action bill through the cost-modifier chokepoint
    (`effective_payments` with base = `accrued_cost.wood`). This is the same base the
    during-building legality already checked as its running total on the LAST pasture, so
    the settle frontier agrees with what was enabled — a per-action-capped conversion
    (Millwright's 2 grain) is counted once against the whole-action total at both points.
    Two shapes:

    - **Singleton frontier** (the common case — no conversion card, or Hedge Keeper, which
      only frees fences and offers no conversion): debit the one payment inline + zero the
      frame's `accrued_cost` here (so a re-entered flip cannot double-debit), then the caller
      (`_apply_proceed`) runs `_enter_after_phase` to flip this frame to its after-phase and
      fire the after-autos (the grants).

    - **>1 payment** (a conversion card — Millwright-on-fences — offers a wood/grain choice):
      push the two-step `PendingChooseCost(action_kind="build_fence")` over the frontier, ONCE,
      against the whole-action total, and do NOT debit / zero / enter-after here. The player
      picks a `CommitChooseCost`; `_execute_choose_cost` debits it, pops the menu back to this
      paused `PendingBuildFences`, then itself zeroes the accrued bill + runs `_enter_after_phase`
      (resume-to-grants), preserving settle -> pay -> grants. `_apply_proceed` detects the pushed
      menu (top is now `PendingChooseCost`, not the build host) and skips its own
      `_enter_after_phase`.
    """
    from agricola.legality import _build_fence_ctx, effective_payments

    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    idx = top.player_idx
    p = state.players[idx]
    payments = effective_payments(
        state, idx,
        _build_fence_ctx(p, top.accrued_cost.wood, build_index=top.pastures_built,
                         space_id=top.initiated_by_id),
    )
    if len(payments) > 1:
        # A conversion (Millwright) surfaces a payment menu over the whole-action total.
        # Defer the debit + accrued-zero + the after-grants to CommitChooseCost /
        # _execute_choose_cost (resume-to-grants).
        return push(state, PendingChooseCost(
            player_idx=idx, initiated_by_id=top.PENDING_ID,
            payments=tuple(payments), action_kind="build_fence"))
    # Singleton: debit the one payment inline + zero the accrued bill (defensive: a
    # re-entered flip can't re-debit). The caller fires the after-grants.
    assert isinstance(payments[0], Resources), "build-fence has no non-resource routes"
    new_p = fast_replace(p, resources=p.resources - payments[0])
    state = fast_replace(
        state,
        players=tuple(new_p if i == idx else state.players[i] for i in range(2)),
    )
    return replace_top(state, fast_replace(state.pending_stack[-1], accrued_cost=Resources()))


def _apply_proceed(state: GameState) -> GameState:
    """The work-complete boundary for the atomic and Proceed-host space frames
    (SPACE_HOST_REFACTOR.md §4.1/§4.3/§11): flip the host to its after-phase and
    fire its after_action_space automatic effects (after the work, before the
    after-triggers — the §2 ordering).

    Two host kinds reach here, both at their before-phase:
      - **Atomic** (`PendingActionSpace`): the space's effect has NOT run yet, so
        run it now (ATOMIC_HANDLERS[space_id]) — the atomic resolver operates on
        current_player and leaves the stack alone, so the host stays on top — and
        then flip + fire.
      - **Proceed-host** (the and/or, and-then parents): the sub-actions already
        ran during the before-phase, so Proceed runs no effect of its own; just
        flip + fire.

    The flip + after-auto firing is `_enter_after_phase` (the same uniform
    "after-window opens" point the sub-action commits and the markets use); the
    derived event for an action-space host is `after_action_space`.

    A third kind, the PendingPreparation start-of-round host (II.6, card-only), also
    exits via Proceed — but it is a phase host with NO before/after `phase` flip and
    no "after" clause, so Proceed simply POPS it (its `start_of_round` autos already
    fired at push). Handled first, before the action-space-host assertion.

    A fourth kind, the multi-shot sub-action builders (PendingBuildRooms /
    PendingBuildStables / PendingBuildFences): the rooms/stables/pastures were
    already built during the before-phase, so Proceed runs no effect of its own —
    it is purely the explicit work-complete signal that flips them to their
    after-phase (firing after_build_<x> autos via the same `_enter_after_phase`).
    They are sub-action hosts, not action-space hosts, so they are handled before
    that assertion.
    """
    top = state.pending_stack[-1]
    if isinstance(top, PendingPreparation):
        return pop(state)
    # Multi-shot granted plow (CARDS only — Swing/Turnwrest/Wheel Plow): the player has
    # plowed >=1 of up to max_plows fields and chooses to finish early. Like the build
    # hosts, the work already happened during the before-phase, so Proceed is purely the
    # explicit work-complete signal — flip to the after-phase (firing after_plow autos),
    # then Stop pops. A single-shot plow flips on its commit and never exposes Proceed.
    if isinstance(top, PendingPlow):
        assert getattr(top, "phase", None) == "before" and top.num_plowed >= 1, (
            f"Proceed expected a before-phase multi-shot plow with >=1 done, got {top!r}")
        return _enter_after_phase(state)
    if isinstance(top, (PendingBuildRooms, PendingBuildStables, PendingBuildFences)):
        assert getattr(top, "phase", None) == "before", (
            f"Proceed expected a before-phase build host, got {top!r}")
        # Cards deferred-tally settle (COST_MODIFIER_DESIGN.md §9.2): a fence build
        # accrued its wood on the frame instead of debiting per-commit, so the bill
        # is paid HERE — before the after-grants (Shepherd's-Crook-style) fire — for
        # the owner-confirmed order settle -> pay -> grants. (Family already debited
        # per-commit in _execute_build_pasture, leaving accrued_cost at its default,
        # so it skips the settle and reaches _enter_after_phase unchanged.)
        if isinstance(top, PendingBuildFences) and state.mode is GameMode.CARDS:
            state = _settle_build_fences(state)
            # When the settle surfaced a >1-payment menu (Millwright), it pushed a
            # PendingChooseCost on top of the still-before-phase PendingBuildFences and
            # deferred the after-grants. Don't fire them here (the top is the menu, not the
            # build host) — _execute_choose_cost resumes to them after the payment.
            if isinstance(state.pending_stack[-1], PendingChooseCost):
                return state
        return _enter_after_phase(state)
    assert (
        type(top).PENDING_ID in ACTION_SPACE_PENDING_IDS
        and getattr(top, "phase", None) == "before"
    ), f"Proceed expected a before-phase action-space host, got {top!r}"

    if isinstance(top, PendingActionSpace):
        # Atomic host: the primary effect has not run yet. (The hosted set is
        # true-atomic spaces only — never the card-mode handlers that themselves
        # push, e.g. basic_wish / meeting_place — so no extra frame is interposed
        # above the host and it remains on top after the effect.)
        state = ATOMIC_HANDLERS[top.space_id](state)

    # Flip to the after-phase + fire after_action_space autos (no-op in Family;
    # the after-phase enumerator then offers after-triggers + Stop).
    return _enter_after_phase(state)


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


def _fire_ready_one_shots(state: GameState, idx: int) -> GameState:
    """Fire any owned one-shot conditional cards whose condition is now met for
    player `idx` (CARD_IMPLEMENTATION_PLAN.md II.3 / §6).

    Level-triggered: called at the two points a standing house-material condition
    can change for the owner — right after a renovate applies, and right after a
    card is played (which catches the "renovated to stone, THEN played Manservant"
    case the action hooks miss). Each card fires at most once per game; the firing
    is recorded in the per-game `fired_once` latch (never cleared), so a re-check
    after a later renovate / card play is idempotent.

    A no-op in the Family game: CONDITIONAL_ONE_SHOTS is empty, so the loop body is
    never entered and `state` is returned unchanged.
    """
    from agricola.cards.triggers import CONDITIONAL_ONE_SHOTS
    if not CONDITIONAL_ONE_SHOTS:
        return state
    p = state.players[idx]
    owned = p.occupations | p.minor_improvements
    for cid, (condition_fn, apply_fn) in CONDITIONAL_ONE_SHOTS.items():
        if cid not in owned or cid in p.fired_once:
            continue
        if not condition_fn(state, idx):
            continue
        # Latch first (so apply_fn / re-entrant sweeps see it fired), then apply.
        p = state.players[idx]
        state = _update_player(state, idx, fast_replace(p, fired_once=p.fired_once | {cid}))
        state = apply_fn(state, idx)
        p = state.players[idx]
    return state


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
        # Case 1: a pending frame is active. Decision is awaiting agent — UNLESS
        # it is a Delegating space host whose single mandatory sub-action just
        # completed (SPACE_HOST_REFACTOR.md §5): then auto-advance it to its
        # after-phase (firing after_<event> autos) before returning. The flip
        # makes phase=="after", so the guard is False next iteration — idempotent.
        #
        # The flip is UNCONDITIONAL (SPACE_HOST_REFACTOR.md §5.1): taking the
        # mandatory sub-action closes the before-window and IMPLICITLY DECLINES any
        # unfired `before_<event>` trigger. before-triggers are surfaced only while
        # subaction_complete == False, so a card whose "each time you use [space]"
        # grant the player wants must fire it BEFORE using the space. The
        # (subaction_complete && phase=="before") state is therefore purely
        # transient — flipped here within the same step, before legal_actions is
        # ever called on it. (A prior held-flip kept this window open after the main
        # sub-action so grants could fire "in either order"; order is load-bearing
        # per the rules, so that was a bug — see CARD_AUTHORING_GUIDE.md.) A no-op in
        # the Family game (no triggers → nothing a hold would have changed anyway).
        if state.pending_stack:
            top = state.pending_stack[-1]
            if (getattr(type(top), "DELEGATING", False)
                    and top.subaction_complete
                    and top.phase == "before"):
                state = _enter_after_phase(state)
                continue
            return state

        # Case 1.5: DRAFT phase with empty stack. Push the next pick frame,
        # or transition to PREPARATION once all pools are empty.
        if state.phase == Phase.DRAFT:
            next_pick = _next_draft_pick(state.draft_pools)
            if next_pick is None:
                state = fast_replace(state, phase=Phase.PREPARATION, draft_pools=None)
            else:
                player_idx, card_type = next_pick
                state = push(state, PendingDraftPick(
                    player_idx=player_idx,
                    card_type=card_type,
                ))
            continue

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


def _next_draft_pick(draft_pools: tuple) -> tuple | None:
    """Return (player_idx, card_type) for the next pick, or None if all pools empty.

    Pick order within each round: P0_occ → P0_min → P1_occ → P1_min.
    Encoded by checking which pool has the maximum size in that priority order.
    """
    p0_occ, p0_min, p1_occ, p1_min = draft_pools
    max_size = max(len(p0_occ), len(p0_min), len(p1_occ), len(p1_min))
    if max_size == 0:
        return None
    if len(p0_occ) == max_size:
        return (0, "occupation")
    if len(p0_min) == max_size:
        return (0, "minor")
    if len(p1_occ) == max_size:
        return (1, "occupation")
    return (1, "minor")


def _apply_draft_pick(state: GameState, action: CommitDraftPick) -> GameState:
    """Remove the picked card from the player's draft pool and add it to their hand.

    After all 4 picks in a round (all pool sizes equal and > 0), swap the pools:
    P0 gets P1's remaining cards and vice versa.
    """
    top = state.pending_stack[-1]
    assert isinstance(top, PendingDraftPick)
    player_idx = top.player_idx
    card_type = top.card_type
    card_id = action.card_id

    p0_occ, p0_min, p1_occ, p1_min = state.draft_pools

    if player_idx == 0 and card_type == "occupation":
        new_pool = tuple(c for c in p0_occ if c != card_id)
        new_pools = (new_pool, p0_min, p1_occ, p1_min)
        sizes = (len(new_pool), len(p0_min), len(p1_occ), len(p1_min))
    elif player_idx == 0 and card_type == "minor":
        new_pool = tuple(c for c in p0_min if c != card_id)
        new_pools = (p0_occ, new_pool, p1_occ, p1_min)
        sizes = (len(p0_occ), len(new_pool), len(p1_occ), len(p1_min))
    elif player_idx == 1 and card_type == "occupation":
        new_pool = tuple(c for c in p1_occ if c != card_id)
        new_pools = (p0_occ, p0_min, new_pool, p1_min)
        sizes = (len(p0_occ), len(p0_min), len(new_pool), len(p1_min))
    else:
        new_pool = tuple(c for c in p1_min if c != card_id)
        new_pools = (p0_occ, p0_min, p1_occ, new_pool)
        sizes = (len(p0_occ), len(p0_min), len(p1_occ), len(new_pool))

    p = state.players[player_idx]
    if card_type == "occupation":
        new_p = fast_replace(p, hand_occupations=p.hand_occupations | {card_id})
    else:
        new_p = fast_replace(p, hand_minors=p.hand_minors | {card_id})
    new_players = state.players[:player_idx] + (new_p,) + state.players[player_idx + 1:]

    # After every pick in a round all 4 pools shrink by 1 each, reaching equal
    # size. Swap at end of round: P0 gets P1's remaining pool and vice versa.
    if sizes[0] == sizes[1] == sizes[2] == sizes[3] and sizes[0] > 0:
        new_pools = (new_pools[2], new_pools[3], new_pools[0], new_pools[1])

    return pop(fast_replace(state, players=new_players, draft_pools=new_pools))


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

    # 2. Per-player: distribute future_resources (goods), clear the consumed slot,
    #    clear newborns. future_rewards (animals + effect hooks) is distributed
    #    separately in step 5 below — it is card-only and may push a decision frame
    #    or fire an effect, so it cannot be folded into this mechanical comprehension.
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

    # 4. Distribute the per-player future_rewards slot for the new round
    #    (CARD_IMPLEMENTATION_PLAN.md II.5) — animals accommodated, effect-card
    #    round-start hooks fired. A no-op in the Family game (every slot is the
    #    default FutureReward(), so the falsy-slot guard skips both branches and
    #    `result` is returned object-identical — byte-identical preparation).
    result = _collect_future_rewards(result, idx)

    # 5. Card-only start-of-round phase hook (CARD_IMPLEMENTATION_PLAN.md II.6):
    #    push a PendingPreparation host frame for each player who owns a
    #    start-of-round card, firing that player's `start_of_round` automatic
    #    effects at push and surfacing its triggers as FireTrigger. The frames must
    #    resolve (each Proceed pops one) before any worker placement, so they sit on
    #    the stack while phase==WORK — _advance_until_decision Case 1 returns control
    #    to the agent for them. Card-dependent (`should_host_preparation`), so the
    #    Family game skips this entirely and _complete_preparation stays
    #    byte-identical (no frame pushed → the C++ Family engine never sees it).
    result = _fire_preparation_hook(result)
    return result


def _collect_future_rewards(state: GameState, slot: int) -> GameState:
    """Distribute every player's promised `future_rewards[slot]` ANIMALS for the
    round being entered (CARD_IMPLEMENTATION_PLAN.md II.5): collected and trimmed to
    the best physically-accommodatable configuration via `pareto_frontier` (no player
    decision — preparation is decision-free; the best-kept frontier point is taken,
    deterministically). The consumed animals are cleared from the slot.

    Effect-card round-start grants (`effect_card_ids`, e.g. Handplow's deferred plow)
    are deliberately NOT consumed here. They stay in the slot and are surfaced as
    OPTIONAL `start_of_round` triggers at the PendingPreparation host (see
    `_fire_preparation_hook`), because a granted sub-action is the player's to take
    or decline — a granted plow can be strategically wrong (a new field consumes a
    farmyard cell wanted for a pasture). Force-firing them here would remove that
    choice, so the schedule is left for the host's trigger to consume on FIRE.

    A no-op in the Family game: every slot is the default `FutureReward()` (no
    animals), so the guard skips and `state` is returned object-identical
    (preparation stays byte-identical). The only in-scope card scheduling animals
    (Acorns Basket) is deferred, so the animal path is exercised by tests today, not
    by a live card — but it keeps the round-start path correct for when it lands.
    """
    from agricola.helpers import pareto_frontier

    for idx, p in enumerate(state.players):
        reward = p.future_rewards[slot]
        a = reward.animals
        if not (a.sheep or a.boar or a.cattle):   # only animals are collected here
            continue                              # (Animals has no __bool__ — check counts)
        # Clear the consumed ANIMALS, preserving any effect_card_ids in the slot.
        new_reward = FutureReward(effect_card_ids=reward.effect_card_ids)
        new_rewards = (
            p.future_rewards[:slot] + (new_reward,) + p.future_rewards[slot + 1:]
        )
        p = fast_replace(p, future_rewards=new_rewards)
        # Gain the animals, then keep the best accommodatable configuration.
        frontier = pareto_frontier(p, reward.animals)
        best = max(frontier, key=lambda fc: (fc[0].sheep + fc[0].boar + fc[0].cattle))
        p = fast_replace(p, animals=best[0])
        state = _update_player(state, idx, p)
    return state


def _fire_preparation_hook(state: GameState) -> GameState:
    """Push a PendingPreparation frame for each owning player + fire their
    `start_of_round` automatic effects (card game only).

    A frame is pushed for a player who either owns a start-of-round card OR has a
    deferred round-start effect scheduled for the round being entered (Handplow — the
    schedule, not card ownership, drives hosting so a played Handplow doesn't host
    every round, only the round its plow comes due). A no-op when neither holds for
    either player — the Family fast path, so `_complete_preparation` stays
    byte-identical. Push order mirrors the harvest FEED/BREED hooks: the non-starting
    player is pushed first (bottom), the starting player second (top), so the starting
    player resolves their start-of-round decisions first. Each player's
    `start_of_round` autos fire at push (after the frame is on the stack, so an
    auto/eligibility read can inspect `top.player_idx`); scheduled OPTIONAL grants
    (Handplow) instead surface as FireTriggers in the host enumerator.
    """
    from agricola.cards.triggers import (
        has_scheduled_round_start_effect,
        owns_start_of_round_card,
        should_host_preparation,
    )

    if not should_host_preparation(state):
        return state

    rn = state.round_number
    sp = state.starting_player
    # Non-starting player first (bottom of stack), starting player second (top).
    for idx in ((sp + 1) % 2, sp):
        p = state.players[idx]
        if not (owns_start_of_round_card(p) or has_scheduled_round_start_effect(p, rn)):
            continue
        state = push(state, PendingPreparation(player_idx=idx))
        state = apply_auto_effects(state, "start_of_round", idx)
    return state


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


def _fire_harvest_field_hook(state: GameState) -> GameState:
    """Fire the field-phase card hook (`harvest_field` automatic effects),
    card-dependent and transient. A no-op when no player owns a harvest-field
    card — the Family fast path, so `_resolve_harvest_field` stays byte-identical.

    When some player owns one, a PendingHarvestField host frame is pushed (the
    uniform host the firing rides through), `apply_auto_effects` runs the
    `harvest_field` autos for each player, and the frame is popped before
    returning. All current harvest-field cards are automatic, so the frame never
    surfaces an agent decision; it is constructed and torn down within this call
    and never reaches a returned state (so the canonical serializer / C++ never
    see it). Effects fire in starting-player-first order, mirroring the FEED /
    BREED push order.
    """
    if not should_host_harvest_field(state):
        return state

    state = push(state, PendingHarvestField())
    sp = state.starting_player
    for idx in (sp, (sp + 1) % 2):
        state = apply_auto_effects(state, "harvest_field", idx)
    return pop(state)


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

    A fourth, card-only concern runs FIRST (before the crop take): the
    field-phase card hook. When some player owns a harvest-field card
    (Loom, Butter Churn, Three-Field Rotation, Scythe Worker), a transient
    PendingHarvestField host frame is pushed, its `harvest_field` automatic
    effects fire for each player, and it is popped — all before the
    mechanical take. Scythe Worker reads the unharvested grain fields here,
    so the firing MUST precede the take. The push is card-dependent
    (`should_host_harvest_field`), so the Family game skips it entirely and
    this resolver stays byte-identical (see CARD_IMPLEMENTATION_PLAN.md II.6).
    """
    state = _fire_harvest_field_hook(state)

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
