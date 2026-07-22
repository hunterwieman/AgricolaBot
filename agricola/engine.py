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
    CommitFieldTake,
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
    PendingAccommodate,
    PendingActionSpace,
    PendingBakeBread,
    PendingBasicWishForChildren,
    PendingBuildFences,
    PendingBuildRooms,
    PendingBuildStables,
    PendingBuildMajor,
    PendingCattleMarket,
    PendingChooseCost,
    PendingDraftPick,
    PendingFamilyGrowth,
    PendingFieldPhase,
    PendingFoodPayment,
    PendingGrantedSubAction,
    PendingHarvestBreed,
    PendingHarvestFeed,
    PendingHarvestOccasion,
    PendingHarvestWindow,
    PendingHouseRedevelopment,
    PendingMeetingPlace,
    PendingPigMarket,
    PendingPlayMinor,
    PendingPlayOccupation,
    PendingCardChoice,
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
    _execute_field_take,
    _execute_food_payment,
    _execute_harvest_conversion,
    _execute_play_minor,
    _execute_play_occupation,
    _execute_plow,
    _initiate_meeting_place_cards,
    _execute_renovate,
    _execute_sow,
    _mark_effect_initiated,
    _update_player,
    field_take,
)

# Ensure card registrations run at engine-module load time.
import agricola.cards  # noqa: F401
# The action-space hook surface (II.2): apply_auto_effects fires mandatory
# automatic effects at a hook; should_host_space decides whether an atomic
# placement is hosted by a PendingActionSpace frame. Both are no-ops on the
# Family fast path (empty registries). cards.triggers is a leaf module — safe
# to import here without a load-order cycle.
from agricola.cards.triggers import (
    IMPROVEMENT_DECLINE_INCOME,
    apply_auto_effects,
    note_improvement_action_declined,
    should_host_space,
)
# The harvest timing-window ladder (HARVEST_WINDOWS_DESIGN.md): the ordered window
# table + the virtual-walk decode (the per-player FIELD band), the skip-guard seam,
# and the per-occasion auto firing — all consumed by _advance_harvest. Another leaf
# module — safe to import here without a load-order cycle.
from agricola.cards.round_end import (
    RETURN_SEGMENT_START,
    ROUND_END_STEPS,
    WORK_SEGMENT_END,
)
# The preparation ladder (ruling 54, 2026-07-14): the ordered step table walked
# by _advance_preparation. Another leaf module — no load-order cycle.
from agricola.cards.preparation import (
    PREP_STEPS,
    ROUND_SETUP,
)
from agricola.cards.harvest_windows import (
    BREED_BAND_START,
    FEED_BAND_END,
    FEED_BAND_START,
    HARVEST_WINDOWS,
    WALK_LENGTH,
    apply_harvest_occasion_autos,
    maybe_host_occasion_triggers,
    auto_take_fold_ins,
    choice_take_modifiers,
    sentinel_position,
    walk_position,
    window_skipped,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def step(state: GameState, action: Action) -> GameState:
    """Apply one action and auto-advance through system transitions.

    Preconditions (caller's responsibility — step does NOT validate):
      - action is in legal_actions(state).
      - the game is not terminal — i.e. NOT (phase == BEFORE_SCORING and the pending
        stack is empty). A before-scoring decision frame (Ox Skull's discard) sits at
        BEFORE_SCORING with a non-empty stack and IS a valid step target.

    Postconditions:
      - The action's effect has been applied.
      - The state has been auto-advanced through phase transitions and
        active-player switches until the next agent decision OR a terminal
        state (BEFORE_SCORING with an empty stack).

    Raises:
      - RuntimeError if the game is terminal (BEFORE_SCORING, empty stack).
      - NotImplementedError only as a defensive guard if a PlaceWorker
        targets a space without registered handlers (should not happen for
        any space surfaced by legal_placements).
    """
    if state.phase == Phase.BEFORE_SCORING and not state.pending_stack:
        raise RuntimeError("step called on a terminated game")

    # A PendingCardChoice can empty the stack while phase==WORK (a boundary
    # one-shot's choice after a placement completed). Resolving it is NOT a
    # worker-placement turn, so it must NOT trigger the worker alternation in
    # step 2 (the alternation for the placement already ran the step before).
    # Detect it from the PRE-action top frame (the frame is popped by the action).
    # (Preparation-window frames need no guard: they resolve while
    # phase==PREPARATION, where the alternation clause is already False.)
    _resolving_prep = bool(state.pending_stack) and isinstance(
        state.pending_stack[-1], PendingCardChoice
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
    #    A PendingCardChoice resolution can empty the stack in WORK
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
    # CommitAccommodate lands on any of three market parent pendings OR the bare
    # reconciliation frame PendingAccommodate. `isinstance` handles tuple-of-types
    # natively in _apply_commit_subaction. For a market the effect pivots the host to its
    # after-phase (trailing Stop pops); for PendingAccommodate it pops directly.
    CommitAccommodate:  (
        (PendingSheepMarket, PendingPigMarket, PendingCattleMarket, PendingAccommodate),
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
    # Card game: the mandatory field-phase take at a hosted during-window
    # (HARVEST_WINDOWS_DESIGN.md §4c). The effect records the take occasion on
    # PendingFieldPhase (take_fired=True) and fires the per-occasion autos; the
    # frame stays up for the window's free-order triggers — Proceed exits.
    CommitFieldTake:         (PendingFieldPhase,     _execute_field_take),
    # Card game: raise food to pay a food cost (FOOD_PAYMENT_DESIGN.md). The effect applies
    # the chosen conversion bundle, debits the cost, POPS PendingFoodPayment itself, and
    # resumes the play (play_minor / play_occupation body) — a closed frame, no trailing Stop.
    CommitFoodPayment:       (PendingFoodPayment,    _execute_food_payment),
}


def _apply_place_worker(state: GameState, action: PlaceWorker) -> GameState:
    # CARD action spaces (user ruling 74, 2026-07-21 — played-card-as-action-space,
    # agricola/cards/card_spaces.py): a "card:<card_id>" placement targets the
    # owner's own tableau card, not the board, so it takes its own path — the
    # worker marker lives on the card (CardStore), never in board state. The
    # Family game never generates such an action (empty registry → the space id
    # is never surfaced), so this branch is Family-inert.
    if action.space.startswith("card:"):
        return _apply_place_card_space_worker(state, action)

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


def _apply_place_card_space_worker(state: GameState, action: PlaceWorker) -> GameState:
    """Place a worker on a CARD action space (user ruling 74, 2026-07-21 —
    played-card-as-action-space; registry: `agricola/cards/card_spaces.py`).

    Mirrors a board placement exactly where the rules are shared, and diverges
    only in where the worker marker lives:

    - `people_home` decrements exactly like any placement (the
      `_apply_worker_placement` step-2 accounting), so player alternation and
      the round's all-placed detection — both keyed on `people_home` — just
      work.
    - The occupancy record is the on-card worker marker (a CardStore count via
      `place_card_space_worker`), not a board `workers` tuple: "an occupied
      action space cannot be used again that round" is enforced by the
      placement enumerator reading that marker, and `_return_home_reset`
      clears it.
    - The use is HOSTED with the generic atomic-host lifecycle (the
      `PendingActionSpace` shape — before-autos at the push here, the work at
      Proceed via the registered `use_fn`, the after-window, Stop), so a
      card-space use fires `before_/after_action_space` with
      `space_id = "card:<id>"` — the ruling's "card spaces count as action
      spaces for other cards' hooks" consequence. `picks` (the wide
      placement's payload — Collector's goods combination) rides the host
      frame from the placement to the Proceed work step.
    """
    from agricola.cards.card_spaces import place_card_space_worker

    card_id = action.space.split(":", 1)[1]
    ap = state.current_player
    p = state.players[ap]
    p = place_card_space_worker(
        fast_replace(p, people_home=p.people_home - 1), card_id)
    state = fast_replace(state, players=tuple(
        p if i == ap else state.players[i] for i in range(len(state.players))))
    state = push(state, PendingActionSpace(
        player_idx=ap, initiated_by_id=f"space:{action.space}",
        picks=action.picks))
    return apply_auto_effects(state, "before_action_space", ap)


def _fire_subaction_before_auto(state: GameState, prev_depth: int) -> GameState:
    """If a commit-terminated sub-action leaf was JUST PUSHED — the stack grew past
    `prev_depth` and the new top is a leaf — fire its `before_<PENDING_ID>` automatic
    effects (SUBACTION_HOOK_REFACTOR.md §4d).

    The single central seam for sub-action before-autos — symmetric with
    `_apply_place_worker` firing `before_action_space` when it pushes a space host,
    and with `_enter_after_phase` firing the after-autos at the commit-flip. Called
    at the engine chokepoints where a sub-action leaf can be pushed: after a
    `_choose_subaction_*` handler runs (`_apply_choose_sub_action`), after a
    trigger's `apply_fn` runs (`_apply_fire_trigger`, the card-grant push path —
    Assistant Tiller → PendingPlow, Threshing Board / Oven Firing Boy →
    PendingBakeBread), after a play-card `on_play` runs (which may push — Shifting
    Cultivation → PendingPlow), and after a non-"rerun" food-payment resume.

    `prev_depth` — the stack depth before the possibly-pushing call — is what makes
    "just pushed" checkable. When the call did NOT push (a non-pushing trigger fired
    at a leaf; a goods-only `on_play`), the top is the *same* host leaf whose
    before-autos already fired at its real push, and re-firing would double-pay
    (Bookshelf's +3 food per occupation play; Hand Truck's bake grant at a bake
    Potter fires during). Cards used to defend per-card with a `phase == "before"`
    eligibility read (Wood Workshop); this guard makes the seam itself fire exactly
    once per pushed leaf.

    Gated on `SUBACTION_PENDING_IDS` so it fires only for the sub-action host leaves,
    never for a composite host (`PendingMajorMinorImprovement`, which fires its own
    `before_major_minor_improvement`). A no-op in the Family game (empty AUTO_EFFECTS)
    → byte-identical state.
    """
    if len(state.pending_stack) <= prev_depth:
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
    prev_depth = len(state.pending_stack)
    return _fire_subaction_before_auto(handler(state, action), prev_depth)


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
    prev_depth = len(state.pending_stack)
    if action.variant is not None:
        applied = entry.apply_fn(state, new_top.player_idx, action.variant)
    else:
        applied = entry.apply_fn(state, new_top.player_idx)
    return _fire_subaction_before_auto(applied, prev_depth)


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
    # Improvement-decline income seam (user ruling 74, 2026-07-21 — Field
    # Merchant B103; the ONE registry-gated exception to the pure-pop invariant
    # below, and with the registry EMPTY the guard short-circuits and Stop is
    # exactly the pure pop): a granted NAMED "Minor Improvement" action — a
    # `PendingGrantedSubAction` with `minor_is_action=True` (Sample Stable
    # Maker, Task Artisan; never the flag-False "play a minor" grants of
    # Scholar / Beneficiary / Equipper, whose printed clarification "This
    # effect is not a 'Minor Improvement' action" the flag-keyed detection
    # excludes structurally) — popped via Stop with its play_minor branch never
    # entered IS a decline of that named action, paying the decline income
    # ("minor" kind). An entered branch is a TAKEN action, even when the
    # Braid-Maker swap (`helpers.swap_play_minor_to_build_major`) converted the
    # play into a major build — the swap fires only after the branch was chosen,
    # so this detection structurally cannot fire on it. (For the use-budget
    # wrapper shape, `max_uses > 0`, "never entered" is `uses_done == 0`; no
    # named-action multi-use grant exists today — Furnisher's is flag-False —
    # and whether a PARTIALLY-used one declines its remaining uses is an
    # unsettled rules question a future card must bring to the user.) The frame
    # is card-only, so no Family state can ever reach the isinstance.
    if IMPROVEMENT_DECLINE_INCOME:
        top = state.pending_stack[-1]
        if (isinstance(top, PendingGrantedSubAction)
                and top.minor_is_action
                and "play_minor" in top.subactions
                and (top.uses_done == 0 if top.max_uses > 0
                     else "play_minor" not in top.chosen)):
            state = note_improvement_action_declined(state, top.player_idx, "minor")
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

    A third kind, the per-player timing-window choice hosts (PendingHarvestWindow —
    serving the harvest, round-end, AND preparation ladders), also exits via
    Proceed — a phase host with NO before/after `phase` flip and no "after"
    clause, so Proceed simply POPS it (its window's autos fired mechanically in
    the walk). Handled first, before the action-space-host assertion.

    A fourth kind, the multi-shot sub-action builders (PendingBuildRooms /
    PendingBuildStables / PendingBuildFences): the rooms/stables/pastures were
    already built during the before-phase, so Proceed runs no effect of its own —
    it is purely the explicit work-complete signal that flips them to their
    after-phase (firing after_build_<x> autos via the same `_enter_after_phase`).
    They are sub-action hosts, not action-space hosts, so they are handled before
    that assertion.
    """
    top = state.pending_stack[-1]
    # A per-player harvest-window choice host (card-only, HARVEST_WINDOWS_DESIGN.md):
    # a phase host with no before/after flip — its window's autos fired mechanically in
    # the walk — so Proceed (the decline / work-complete boundary) simply pops; the
    # walk resumes at GameState.harvest_cursor.
    if isinstance(top, PendingHarvestWindow):
        return pop(state)
    # A per-occasion choice host (card-only, HARVEST_WINDOWS_DESIGN.md §4d): the
    # occasion's autos fired before the push, so Proceed declines whatever
    # optional reactions are unfired and pops — back to whatever emitted the
    # occasion (the walk, the FIELD during-frame, or a card's firing frame).
    if isinstance(top, PendingHarvestOccasion):
        return pop(state)
    # The FIELD during-window host (card-only, HARVEST_WINDOWS_DESIGN.md §4): its
    # mandatory take fired via CommitFieldTake (the enumerator withholds Proceed
    # until it has), so Proceed is the free-order window's exit — a pure pop; the
    # walk resumes at GameState.harvest_cursor (already pinned past this window).
    if isinstance(top, PendingFieldPhase):
        assert top.take_fired, (
            "Proceed at a field-phase host before its mandatory take fired")
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
        # Atomic host: the primary effect has not run yet. Mark the work applied
        # FIRST (the commit-executor pattern — the mark must land on the host
        # while it is on top), then run the effect; the deferred flip (ruling 60)
        # fires in _advance_until_decision after the barrier reconciles and after
        # anything the effect pushed resolves. Today's atomic handlers push
        # nothing and grant no animals, so the flip lands within this same step —
        # observably identical to the old inline flip; the mark future-proofs the
        # ordering the day a hosted atomic effect does either. (The hosted set is
        # true-atomic spaces only — never the card-mode handlers that themselves
        # push, e.g. basic_wish / meeting_place.)
        state = _mark_effect_initiated(state)
        before = state.players[top.player_idx].resources
        # Reward-suppression seam (ACTION_REPLACEMENT_DESIGN.md): a card's
        # replace-trigger (Animal Catcher) set `suppressed` in the before-window,
        # so the space grants NOTHING — the `taken` delta below then reads
        # Resources() and the card's own alternate reward is a separate grant, so
        # "got food from a space" reactors (Kindling Gatherer) never fire.
        if not top.suppressed:
            if top.space_id.startswith("card:"):
                # CARD action space (ruling 74 — card_spaces.py): the space's
                # work is the registered use_fn, the ATOMIC_HANDLERS slot of a
                # card space. It receives the host's owner and the placement's
                # `picks` payload carried on the frame. Family-inert (the frame
                # is card-only and the id shape only arises from the registry).
                from agricola.cards.card_spaces import CARD_ACTION_SPACES
                spec = CARD_ACTION_SPACES[top.space_id.split(":", 1)[1]]
                state = spec.use_fn(state, top.player_idx, top.picks)
            else:
                state = ATOMIC_HANDLERS[top.space_id](state)
        # Stamp the goods the acting player obtained from the space (Resources delta
        # across the take) on the host, for after_action_space autos that key on
        # "what you took from the space" (Refactor A). Today's atomic handlers push
        # nothing, so the host is still on top; guard in case a future one does.
        host = state.pending_stack[-1]
        if isinstance(host, PendingActionSpace):
            state = replace_top(state, fast_replace(
                host, taken=state.players[top.player_idx].resources - before))
        return state

    # Proceed-host: flip to the after-phase + fire after_action_space autos
    # (no-op in Family; the after-phase enumerator then offers after-triggers +
    # Stop). The chosen sub-actions all resolved at earlier decision boundaries
    # (each reconciled by the barrier there), so an inline flip is safe at the
    # Proceed itself.
    #
    # Improvement-decline income seam (user ruling 74, 2026-07-21 — Field
    # Merchant B103; registry-gated — empty registry short-circuits, and even
    # populated, `note_improvement_action_declined` pays only cards the
    # DECLINING player OWNS, which no Family player ever does, so the Family
    # path returns the same state object): Proceeding past an offered named
    # improvement branch IS declining that named action, whether or not it was
    # usable ("exiting an improvement action you could not use counts as
    # declining" — the user's ruling; Meeting Place with no playable minor
    # still pays).
    #   - Meeting Place / Basic Wish for Children offer the named "Minor
    #     Improvement" action (their optional minor branch) -> kind "minor".
    #   - House Redevelopment offers the "Major or Minor Improvement" action
    #     (its optional composite step) -> kind "major_or_minor". An ENTERED
    #     composite (improvement_chosen=True) that was then declined via the
    #     composite's own decline route already paid there — the flag keeps
    #     this seam from paying twice.
    # A chosen-then-swapped minor branch (helpers.swap_play_minor_to_build_major
    # — Braid Maker converts the named minor action INTO a major build) is a
    # TAKEN action, never a decline: the swap fires only after the branch was
    # chosen, so `minor_chosen=True` structurally excludes it here. Firing
    # BEFORE `_enter_after_phase` places the income inside the action's work,
    # before the after-window opens.
    if IMPROVEMENT_DECLINE_INCOME:
        if (isinstance(top, (PendingMeetingPlace, PendingBasicWishForChildren))
                and not top.minor_chosen):
            state = note_improvement_action_declined(state, top.player_idx, "minor")
        elif (isinstance(top, PendingHouseRedevelopment)
                and not top.improvement_chosen):
            state = note_improvement_action_declined(
                state, top.player_idx, "major_or_minor")
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


def _fire_boundary_one_shots(state: GameState) -> GameState:
    """Fire owned resource/animal-count one-shot cards whose condition holds — the
    decision-BOUNDARY analog of `_fire_ready_one_shots` (which fires only at the renovate /
    card-play seams, for house-material conditions).

    Called at every agent-decision boundary in `_advance_until_decision`, AFTER
    `_reconcile_accommodation` settles, so a card keyed on an animal count sees the
    ACCOMMODATED animals — Hook Knife's "when you have 8 sheep on your farm" must not fire on
    a transient over-capacity grant the barrier will trim. Each card fires at most once per
    game (`fired_once`, latched before apply so a re-check is idempotent).

    A no-op in the Family game: `BOUNDARY_ONE_SHOTS` may be non-empty (cards register into
    it), but no Family player owns such a card, so the loop makes zero state changes — the
    walk stays byte-identical (the C++ Family gates are unaffected).
    """
    from agricola.cards.triggers import BOUNDARY_ONE_SHOTS
    if not BOUNDARY_ONE_SHOTS:
        return state
    for idx in (state.starting_player, 1 - state.starting_player):
        for cid, (condition_fn, apply_fn) in BOUNDARY_ONE_SHOTS.items():
            p = state.players[idx]
            if cid not in (p.occupations | p.minor_improvements) or cid in p.fired_once:
                continue
            if not condition_fn(state, idx):
                continue
            state = _update_player(state, idx, fast_replace(p, fired_once=p.fired_once | {cid}))
            state = apply_fn(state, idx)
    return state


def _push_before_scoring_choice(state: GameState) -> tuple[GameState, bool]:
    """The before-scoring decision window: at the BEFORE_SCORING boundary, offer any owned
    card's end-game choice (Ox Skull's discard-the-single-cow) as a `PendingCardChoice`.

    Pushes at most ONE frame per call and returns (state, True); the walk re-enters Case 1,
    surfaces it, and the resolver pops it — then this runs again for the next unresolved
    card, until none remain (returns (state, False) and scoring proceeds). The offer is
    latched in `fired_once` AT PUSH (so a "keep" choice, which leaves the option live, is not
    re-offered forever). Push order is starting-player-first; each player's frame resolves
    before the next is offered. A no-op in the Family game (empty registry / no owner).
    """
    from agricola.cards.triggers import BEFORE_SCORING_CARDS
    if not BEFORE_SCORING_CARDS:
        return state, False
    for idx in (state.starting_player, 1 - state.starting_player):
        p = state.players[idx]
        owned = p.occupations | p.minor_improvements
        for cid, options_fn in BEFORE_SCORING_CARDS.items():
            if cid not in owned or cid in p.fired_once:
                continue
            options = options_fn(state, idx)
            if not options:
                continue
            state = _update_player(state, idx, fast_replace(p, fired_once=p.fired_once | {cid}))
            state = push(state, PendingCardChoice(
                player_idx=idx, initiated_by_id=f"card:{cid}", options=tuple(options)))
            return state, True
    return state, False


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

def _reconcile_accommodation(state: GameState) -> tuple[GameState, bool]:
    """The animal-accommodation barrier: if a player was granted animals decision-free
    (helpers.grant_animals sets `animals_need_accommodation`) and they no longer fit the
    farm, surface a PendingAccommodate so the player chooses which animals to keep (the
    excess is cooked to food).

    Called at every agent-decision boundary in _advance_until_decision (Case 1 pending
    frame, Case 3 worker placement) — the single chokepoint every prompt flows through,
    so a grant made anywhere is reconciled at the very next prompt, batched across all
    grants at the same game moment. Flag-gated: the common no-grant path is a single bool
    test over both players; the can_accommodate scan runs only for a flagged player.

    Returns (state, pushed): `pushed` True iff at least one frame was pushed, so the
    caller re-walks (the frame is now the awaiting decision). The flag is cleared for each
    player as it is handled — whether or not a frame is pushed — so the barrier never
    re-pushes for an already-reconciled grant, and a grant that turns out to fit (a fresh
    pasture, say) just clears the flag with no frame. Push order mirrors the harvest
    FEED/BREED hooks: non-starting player first (bottom), starting player last (top), so
    the starting player accommodates first.
    """
    from agricola.cards.capacity_mods import VOLATILE_CAPACITY_CARDS

    p0, p1 = state.players
    if not (p0.animals_need_accommodation or p1.animals_need_accommodation) \
            and not VOLATILE_CAPACITY_CARDS:
        return state, False   # hot path: no grant outstanding, no volatile-capacity card

    from agricola.helpers import accommodates

    pushed = False
    for idx in (1 - state.starting_player, state.starting_player):
        p = state.players[idx]
        needs_check = p.animals_need_accommodation
        if needs_check:
            p = fast_replace(p, animals_need_accommodation=False)
            state = _update_player(state, idx, p)
        # Volatile-capacity re-check (ruling 74, 2026-07-21 — capacity_mods.py has the
        # rationale): each registered fn self-gates on ownership, refreshes its own
        # watermark, and reports whether its capacity input fell since the last
        # boundary. Runs at EVERY boundary (not just flagged ones) — that is the point.
        for _card_id, dropped_fn in VOLATILE_CAPACITY_CARDS:
            state, dropped = dropped_fn(state, idx)
            needs_check = needs_check or dropped
        if needs_check:
            p = state.players[idx]   # re-read: a dropped_fn may have written CardStore
            if not accommodates(
                state, p, p.animals.sheep, p.animals.boar, p.animals.cattle
            ):
                state = push(state, PendingAccommodate(player_idx=idx))
                pushed = True
    return state, pushed


def _assert_animals_accommodated(state: GameState) -> None:
    """Scoring-entry backstop: no player may reach BEFORE_SCORING holding animals their
    farm can't house (scoring counts animal totals directly, so an unreconciled
    over-capacity grant would over-count). Every decision-free grant routes through
    helpers.grant_animals and is reconciled at a decision boundary before scoring, so this
    never fires in correct code — it localizes a missing grant_animals call or barrier if
    one is ever introduced. Stripped under `python -O`, like _assert_nonnegative_state.
    """
    from agricola.helpers import accommodates
    for idx, p in enumerate(state.players):
        assert accommodates(
            state, p, p.animals.sheep, p.animals.boar, p.animals.cattle
        ), (
            f"player {idx} reached scoring over animal capacity: {p.animals} — a "
            f"decision-free grant was not reconciled (see grant_animals / "
            f"_reconcile_accommodation)"
        )


def _advance_until_decision(state: GameState) -> GameState:
    """Walk system-driven phase transitions until the next agent decision
    or game-over. Pure function over state.

    Idempotent: any state returned by this function is stable — running
    it again produces the same state.
    """
    while True:
        # Case 1: a pending frame is active. Decision is awaiting agent — UNLESS
        # the top host's work just completed, in which case auto-advance it to its
        # after-phase (firing after_<event> autos) before returning. Two
        # work-complete signals share the one flip rule:
        #   - a Delegating space host whose single mandatory sub-action just
        #     popped (SPACE_HOST_REFACTOR.md §5 — `subaction_complete`), and
        #   - a commit-terminated host whose executor marked `effect_initiated`
        #     (the DEFERRED after-flip, user ruling 2026-07-14: "after you [do X]"
        #     fires after X's FULL effect — the executor no longer flips inline, so
        #     anything the effect pushed (an on_play's primitive, an oven's
        #     free-bake wrapper) resolves before the after-autos fire).
        # The flip makes phase=="after", so the guard is False next iteration —
        # idempotent.
        #
        # The flip is UNCONDITIONAL (SPACE_HOST_REFACTOR.md §5.1): taking the
        # mandatory sub-action closes the before-window and IMPLICITLY DECLINES any
        # unfired `before_<event>` trigger. before-triggers are surfaced only while
        # the work-complete signal is unset, so a card whose "each time you use
        # [space]" grant the player wants must fire it BEFORE using the space. The
        # (work-complete && phase=="before") state is therefore never enumerated —
        # flipped here before legal_actions is ever called on it; it survives a
        # step only buried under the effect's own pushed frames (the oven free
        # bake is the one Family-reachable case, mirrored in C++). (A prior
        # held-flip kept this window open after the main sub-action so grants
        # could fire "in either order"; order is load-bearing per the rules, so
        # that was a bug — see CARD_AUTHORING_GUIDE.md.)
        #
        # The accommodation barrier runs FIRST (user-approved sequencing,
        # 2026-07-14): a decision-free animal grant inside the effect may have put
        # a player over capacity, and the keep-which choice is part of the effect
        # settling — the after-autos must not fire (nor read transiently
        # over-capacity animal counts) until it resolves. The accommodate frame
        # stacks on top and resolves first; flag-gated no-op on the (usual)
        # no-grant path.
        if state.pending_stack:
            state, pushed = _reconcile_accommodation(state)
            if pushed:
                continue
            top = state.pending_stack[-1]
            if (((getattr(type(top), "DELEGATING", False) and top.subaction_complete)
                    or getattr(top, "effect_initiated", False))
                    and top.phase == "before"):
                state = _enter_after_phase(state)
                continue
            state = _fire_boundary_one_shots(state)   # resource/animal-count one-shots
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

        # Case 2: PREPARATION phase — the preparation ladder (ruling 54,
        # 2026-07-14; `agricola/cards/preparation.py`): round-space collection →
        # the round-card reveal (the nature pause) → start_of_round →
        # replenishment → before_work → start_of_work, then the WORK flip.
        # Paused (a reveal or a window's choice frames) → Case 1 returns the
        # frames next iteration; complete → phase is WORK → Case 3.
        if state.phase == Phase.PREPARATION:
            state, _paused = _advance_preparation(state)
            continue

        # Case 3: WORK phase. If any player has workers, an agent decision
        # is awaiting. If neither does, the work phase ends — but first the
        # round-end ladder's WORK segment runs (end_of_work + after_work,
        # rulings 49/50; a Family no-op).
        if state.phase == Phase.WORK:
            if all(p.people_home == 0 for p in state.players):
                state, paused = _advance_round_end(state)
                if paused:
                    continue           # Case 1 returns the pushed frames
                state = fast_replace(state, phase=Phase.RETURN_HOME)
                continue
            # Accommodation barrier: round-start collection (_collect_future_rewards)
            # may have granted animals past capacity. Reconcile before handing the
            # round's first worker placement. Flag-gated no-op on the no-grant path.
            state, pushed = _reconcile_accommodation(state)
            if pushed:
                continue
            state = _fire_boundary_one_shots(state)   # resource/animal-count one-shots
            return state

        # Case 4: RETURN_HOME phase. The ladder's RETURN segment
        # (start_of_returning_home → returning_home → the reset →
        # after_returning_home → end_of_round), then the round transition.
        if state.phase == Phase.RETURN_HOME:
            state, paused = _advance_round_end(state)
            if paused:
                continue
            state = _round_transition(state)
            continue

        # Cases 5-7: the harvest phases with an empty stack. One unified walk
        # (_advance_harvest) threads the harvest-window ladder
        # (agricola/cards/harvest_windows.py) through the FIELD take, the FEED
        # pendings, and the BREED pendings; it either pushes frames (window choice
        # hosts / FEED / BREED — the Case-1 guard returns them next iteration),
        # transitions between harvest phases, or completes the harvest into
        # PREPARATION / BEFORE_SCORING. Cardless: byte-identical to the old
        # three-case walk (no window ever hosts; the sentinels do exactly the
        # old cases' work).
        if state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
            state = _advance_harvest(state)
            continue

        # Case 8: terminal phase. Before scoring, offer any card's end-game decision
        # (Ox Skull's discard-the-single-cow) — a PendingCardChoice surfaced via Case 1;
        # when none remain, scoring proceeds. Family no-op (empty registry).
        if state.phase == Phase.BEFORE_SCORING:
            state, pushed = _push_before_scoring_choice(state)
            if pushed:
                continue
            if __debug__:
                _assert_animals_accommodated(state)   # unconditional backstop
            return state

        raise AssertionError(f"Unexpected phase in advance loop: {state.phase}")


# ---------------------------------------------------------------------------
# Phase resolvers
# ---------------------------------------------------------------------------

def _advance_round_end(state: GameState):
    """Walk the round-end ladder (rulings 49/50; `round_end.ROUND_END_STEPS`)
    from `state.round_end_cursor` — or the phase-derived segment start: the
    WORK segment (end_of_work, after_work) before the RETURN_HOME flip, the
    RETURN segment (start_of_returning_home → returning_home → the reset →
    after_returning_home → end_of_round) inside RETURN_HOME. Returns
    (state, paused): paused means frames were pushed (the cursor stores the
    resume point); otherwise the segment completed and the cursor is clear.

    Windows resolve window-major (`_process_simple_window`, both players SP
    first) with the harvest SKIP guard OFF — ruling 14's whole-harvest skip
    covers the harvest ladder only (the returning-home phase is distinct
    from the harvest, user 2026-07-12), and Layabout's round-latched
    predicate is id-blind. The `returning_home` window fires BEFORE the
    reset sentinel, so member cards read the still-placed board directly
    (live occupancy is the event data — the Swimming Class design,
    generalized). Constraint on member cards: a WORK-segment trigger must
    not grant a worker placement (Case 3's all-placed gate is the segment's
    resume guard); the placement-granting wordings (Delayed Wayfarer et al.)
    are out of this ladder's scope by design.

    Family fast path: no registrations → every window is two empty dict
    lookups; no frames, no cursor, byte-identical states.
    """
    cur = state.round_end_cursor
    if cur is None:
        cur = 0 if state.phase == Phase.WORK else RETURN_SEGMENT_START
    else:
        state = fast_replace(state, round_end_cursor=None)
    end = (WORK_SEGMENT_END if state.phase == Phase.WORK
           else len(ROUND_END_STEPS) - 1)
    while cur <= end:
        step_id = ROUND_END_STEPS[cur]
        if step_id == "__reset__":
            state = _return_home_reset(state)
            cur += 1
            continue
        state, pushed = _process_simple_window(state, step_id,
                                               skip_guarded=False)
        cur += 1
        if pushed:
            return fast_replace(state, round_end_cursor=cur), True
    return state, False


def _return_home_reset(state: GameState) -> GameState:
    """The mechanical return-home bookkeeping — the ladder's "__reset__"
    sentinel: reset worker placements, return people home. Does NOT clear
    newborns (those need to survive to HARVEST_FEED for the 1-food discount;
    clearing happens in _resolve_preparation of the next round). Does NOT
    increment round_number (that happens in _resolve_preparation)."""
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

    # 3. CARD action spaces (user ruling 74, 2026-07-21 — card_spaces.py):
    #    clear the on-card worker markers so the card spaces are placeable
    #    next round (the meeples themselves went home in step 2's blanket
    #    people_home reset). Registry empty → O(1) no-op, the Family fast
    #    path — byte-identical states.
    from agricola.cards.card_spaces import clear_card_space_workers
    return clear_card_space_workers(state)


def _round_transition(state: GameState) -> GameState:
    """The post-round-end phase transition. On a HARVEST_ROUND (4, 7, 9, 11,
    13, 14), route to HARVEST_FIELD — the harvest sub-phases own their own
    transitions and eventually land back in PREPARATION (rounds 1–13) or
    BEFORE_SCORING (after round 14's HARVEST_BREED). Otherwise PREPARATION."""
    if state.round_number in HARVEST_ROUNDS:
        return fast_replace(state, phase=Phase.HARVEST_FIELD)
    return fast_replace(state, phase=Phase.PREPARATION)


def _resolve_return_home(state: GameState) -> GameState:
    """LEGACY TEST/COMPAT shape — the reset + the phase transition in one
    call (the pre-ladder behavior; many tests drive the round boundary by
    this name). The engine's walk runs the round-end ladder around these
    pieces instead (`_advance_round_end` + `_round_transition`)."""
    return _round_transition(_return_home_reset(state))


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
    # The revealed card belongs to the round being entered; at the reveal the
    # increment has not happened yet, so that is round_number + 1 (uniform —
    # setup's round-1 reveal runs at round_number 0).
    new_board = with_space(state.board, action.card, fast_replace(
        sp, revealed=True, revealed_round=state.round_number + 1))
    return pop(fast_replace(state, board=new_board))


def _advance_preparation(state: GameState, *, assume_revealed: bool = False,
                         force_start: bool = False):
    """Walk the preparation ladder (ruling 54, 2026-07-14;
    `preparation.PREP_STEPS`) from `state.prep_cursor` — or a position derived
    from public state: the post-reveal resume (`__round_setup__`) exactly when
    the revealed-count reads `round_number + 1` (the reveal fired, the
    increment hasn't), else the top. Returns (state, paused): paused means a
    frame is up (the reveal nature node, or a window's choice frames — for
    those the cursor stores the resume point); otherwise the ladder completed
    and the phase has flipped to WORK with the starting player active.

    Windows resolve window-major (`_process_simple_window`, both players SP
    first) with the harvest SKIP guard OFF — ruling 14's whole-harvest skip
    covers the harvest ladder only, and preparation is not part of any
    harvest. The cursor is deliberately NOT set across the reveal pause: the
    resume is derivable from public state, which keeps `prep_cursor`
    Family-constant None (no C++ field — a Family walk pauses only at the
    reveal). At the pre-reveal steps (the `before_round` window and the
    reveal itself) `round_number` still names the just-completed round — the
    round being entered is `round_number + 1` there (Small Animal Breeder's
    "the current round number" reads it so) — and names the new round from
    `__round_setup__` onward, collection included (the revised ruling:
    reveal first, then collection).

    `assume_revealed` / `force_start` serve the `_complete_preparation`
    legacy-compat shape only (tests drive the round boundary by that name on
    fixtures whose stage card was never physically revealed).

    Family fast path: no registrations → every window is two empty dict
    lookups; the mechanical sentinels apply exactly the pre-ladder effects in
    exactly the pre-ladder order (reveal → increment/collect/refill), so
    every Family state is byte-identical to the pre-ladder engine and the
    C++ twin is unchanged.
    """
    cur = state.prep_cursor
    if cur is not None:
        state = fast_replace(state, prep_cursor=None)
    elif force_start:
        cur = 0
    else:
        revealed = _count_revealed_stage_cards(state)
        cur = ROUND_SETUP if revealed == state.round_number + 1 else 0
    n = len(PREP_STEPS)
    while cur < n:
        step_id = PREP_STEPS[cur]
        if step_id == "__collect__":
            state = _enter_new_round(state)
            cur += 1
            continue
        if step_id == "__reveal__":
            if (not assume_revealed
                    and _count_revealed_stage_cards(state) == state.round_number):
                # The nature pause. No cursor across it (see the docstring);
                # RevealCard pops the frame and the walk re-derives the
                # post-reveal resume from the now-incremented revealed count.
                return push(state, PendingReveal()), True
            cur += 1
            continue
        if step_id == "__round_setup__":
            state = fast_replace(state, round_number=state.round_number + 1)
            cur += 1
            continue
        if step_id == "__replenish__":
            state = _refill_accumulation_spaces(state)
            cur += 1
            continue
        state, pushed = _process_simple_window(state, step_id,
                                               skip_guarded=False)
        cur += 1
        if pushed:
            return fast_replace(state, prep_cursor=cur), True
    # Ladder complete: the work phase begins.
    return fast_replace(
        state, phase=Phase.WORK, current_player=state.starting_player), False


def _enter_new_round(state: GameState) -> GameState:
    """The `__collect__` sentinel (ruling 54 as revised: POST-reveal, after
    `__round_setup__` — the card is turned up before the goods on its space
    are taken). `round_number` already names the round being entered, so its
    0-based slot is `round_number - 1`.

    - Last round's newborns become plain adults (`newborns=0` — they survived
      through the harvest for the 1-food feeding discount; nothing reads the
      field between the harvest and here).
    - The per-round / per-turn used-sets clear (II.3; Family no-op).
    - The goods promised on this round's round space are collected
      (`future_resources` — the Well and the Category-8 schedule cards; may
      not be declined, RULES.md) and the consumed slot cleared.
    - Scheduled ANIMALS (`future_rewards`) are granted via the accommodation
      barrier (`_collect_future_rewards`); scheduled EFFECT grants stay in
      the slot for the `round_space_collection` window's triggers (Handplow —
      the same instant's choice host).
    """
    slot = state.round_number - 1  # 0-based slot of the round being entered
    new_players = tuple(
        fast_replace(
            p,
            resources=p.resources + p.future_resources[slot],
            future_resources=(
                p.future_resources[:slot]
                + (Resources(),)
                + p.future_resources[slot + 1:]
            ),
            newborns=0,
        )
        for p in state.players
    )
    state = fast_replace(state, players=new_players)
    state = _clear(state, "used_this_round")
    state = _clear(state, "used_this_turn")
    return _collect_future_rewards(state, slot)


def _refill_accumulation_spaces(state: GameState) -> GameState:
    """The `__replenish__` sentinel — RULES.md's Preparation replenishment.
    Refill every revealed accumulation space (the just-revealed round card
    included — its `revealed` was set by _apply_reveal_card two steps back)."""
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
    return fast_replace(
        state, board=fast_replace(state.board, action_spaces=tuple(new_spaces_list)))


def _complete_preparation(state: GameState) -> GameState:
    """LEGACY TEST/COMPAT shape — the pre-ladder "post-reveal round setup" in
    one call. Many tests drive the round boundary by this name (fast_replace
    round_number/phase, then call this); the ladder walk reproduces the old
    contract: the whole ladder runs from the top with the reveal step assumed
    done (legacy fixtures never physically reveal the stage card), collection
    is slot-clearing so a re-entry is idempotent, and window frames pause the
    walk exactly as the real Case-2 path (the returned state carries them).
    The engine's own walk is `_advance_preparation`, driven from
    `_advance_until_decision` Case 2."""
    out, _paused = _advance_preparation(state, assume_revealed=True,
                                        force_start=True)
    return out


def _collect_future_rewards(state: GameState, slot: int) -> GameState:
    """Distribute every player's promised `future_rewards[slot]` ANIMALS for the round
    being entered (CARD_IMPLEMENTATION_PLAN.md II.5): grant them via `grant_animals` (add
    to the player + flag for the accommodation barrier) and clear the consumed slot. If
    the collected animals exceed the farm's housing capacity, the barrier
    (_reconcile_accommodation, at the round's first worker placement) surfaces a
    PendingAccommodate so the PLAYER chooses which to keep — round-start collection is NOT
    decision-free when it overflows (e.g. Animal Tamer fills the house, then an Acorns
    Basket boar arrives: keep 2 sheep, or trade one for the boar? — the player's call).
    Multiple cards scheduling animals into the same round land here synchronously, so the
    barrier sees the combined total and asks once.

    Effect-card round-start grants (`effect_card_ids`, e.g. Handplow's deferred plow)
    are deliberately NOT consumed here. They stay in the slot and are surfaced as
    OPTIONAL triggers at the ladder's `round_space_collection` window — the same
    instant's choice host (user ruling 2026-07-14: a thing on the round space
    resolves at collection time) — because a granted sub-action is the player's to
    take or decline: a granted plow can be strategically wrong (a new field
    consumes a farmyard cell wanted for a pasture). Force-firing them here would
    remove that choice, so the schedule is left for the window's trigger to
    consume on FIRE.

    A no-op in the Family game: every slot is the default `FutureReward()` (no animals),
    so the guard skips and `state` is returned object-identical (preparation stays
    byte-identical; `grant_animals` / the flag are never reached).
    """
    from agricola.helpers import grant_animals

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
        state = _update_player(state, idx, fast_replace(p, future_rewards=new_rewards))
        # Grant + flag; the barrier reconciles any overflow at the next worker placement.
        state = grant_animals(state, idx, a)
    return state


# (_fire_preparation_hook is GONE — the preparation ladder, ruling 54,
# 2026-07-14: start-of-round hosting is eligibility-driven per window via
# _process_simple_window inside _advance_preparation; see cards/preparation.py.)


# ---------------------------------------------------------------------------
# Harvest phase resolvers (Task 7)
# ---------------------------------------------------------------------------

def _initiate_harvest_feed_for(state: GameState, idx: int):
    """One player's FEED-band sentinel (ruling 40, 2026-07-12: FEED resolves
    whole-phase-per-player). Returns (state, frame_pushed).

    No food is debited here. Food payment is deferred to `CommitConvert`
    (see `_execute_convert` in resolution.py), and the "Cannot withhold
    food tokens" rule is enforced there by paying `min(need, available)`
    unconditionally — the player has no knob to keep food while begging.

    THIS player's feeding-INCOME card autos fire FIRST (the "feeding" event):
    a card printed "in the feeding phase, you get X food" (Town Hall, Milking
    Place, Dentist's payout) must deliver its food before the payment decision
    so the food is payable (HARVEST_WINDOWS_DESIGN.md §5). Under the banding,
    a player's income fires at their OWN band pass — after the earlier
    player's entire FEED segment. Choice-free income only — in-feeding
    CONVERSIONS ride the HARVEST_CONVERSIONS seam on the frame itself. A
    feeding-skipper (Layabout, ruling 14) gets neither the income nor a frame
    — they do not feed at all.
    """
    if window_skipped(state, idx, "feeding"):
        return state, False
    state = apply_auto_effects(state, "feeding", idx)
    state = push(state, PendingHarvestFeed(
        player_idx=idx,
        initiated_by_id="phase:harvest_feed",
    ))
    return state, True


def _initiate_harvest_breed_for(state: GameState, idx: int):
    """One player's BREED-band sentinel (ruling 40) — mirrors
    `_initiate_harvest_feed_for`, without income autos (no "breeding"-event
    income exists; pre-commit breed triggers live on the frame itself, ruling
    20). A breeding-phase skipper gets no frame — no frame = no newborns."""
    if window_skipped(state, idx, "breeding"):
        return state, False
    state = push(state, PendingHarvestBreed(
        player_idx=idx,
        initiated_by_id="phase:harvest_breed",
    ))
    return state, True


def _initiate_harvest_feed(state: GameState) -> GameState:
    """LEGACY TEST HELPER — the pre-ruling-40 shape: BOTH players' payment
    frames at once (starting player's on top), both players' feeding income
    up front. The engine's banded walk pushes one frame per band pass via
    `_initiate_harvest_feed_for` and never calls this; it survives because
    many tests construct bare FEED states with it (their resume path is
    `_advance_harvest`'s legacy None-cursor derivation). New tests should
    drive the real walk instead."""
    sp = state.starting_player
    for idx in (sp, (sp + 1) % 2):
        if not window_skipped(state, idx, "feeding"):
            state = apply_auto_effects(state, "feeding", idx)

    push_order = [(sp + 1) % 2, sp]
    for idx in push_order:
        if window_skipped(state, idx, "feeding"):
            continue
        state = push(state, PendingHarvestFeed(
            player_idx=idx,
            initiated_by_id="phase:harvest_feed",
        ))

    return state


def _initiate_harvest_breed(state: GameState) -> GameState:
    """LEGACY TEST HELPER — the pre-ruling-40 shape: BOTH players' breed
    frames at once. See `_initiate_harvest_feed`'s note; the banded walk uses
    `_initiate_harvest_breed_for`."""
    sp = state.starting_player
    push_order = [(sp + 1) % 2, sp]

    for idx in push_order:
        if window_skipped(state, idx, "breeding"):
            continue
        state = push(state, PendingHarvestBreed(
            player_idx=idx,
            initiated_by_id="phase:harvest_breed",
        ))

    return state


def _has_window_trigger(state: GameState, idx: int, event: str) -> bool:
    """Does player `idx` own an eligible optional trigger registered on this
    window event? False at one empty dict lookup when nothing is registered —
    the Family fast path."""
    from agricola.cards.triggers import TRIGGERS, _owns
    entries = TRIGGERS.get(event, ())
    if not entries:
        return False
    return any(_owns(state.players[idx], e.card_id)
               and e.eligibility_fn(state, idx, frozenset())
               for e in entries)


def _window_trigger_players(state: GameState, window_id: str,
                            *, skip_guarded: bool = True) -> list[int]:
    """The players owed a PendingHarvestWindow choice frame for a WINDOW-MAJOR
    window, in resolve order (starting player first): each non-skipped player
    owning an eligible trigger registered on the window's event. Empty — the
    Family fast path and the autos-only path — when no trigger would surface.
    `skip_guarded=False` — the round-end ladder — bypasses the harvest skip
    guard (see _advance_round_end)."""
    sp = state.starting_player
    return [idx for idx in (sp, (sp + 1) % 2)
            if (not skip_guarded or not window_skipped(state, idx, window_id))
            and _has_window_trigger(state, idx, window_id)]


def _process_simple_window(state: GameState, window_id: str,
                           *, skip_guarded: bool = True):
    """Run one WINDOW-MAJOR simple window — a harvest-ladder window outside
    the bands (see `walk_position`) or a round-end-ladder window
    (`_advance_round_end`, which passes skip_guarded=False: the harvest skip
    covers the harvest ladder only): fire its automatic effects per player
    (starting player first), then push a PendingHarvestWindow choice frame
    per player with an eligible trigger (non-SP first, so the starting player
    decides first). Returns (state, frames_pushed).

    Family fast path: no card registered on the window → two empty registry
    lookups and back."""
    sp = state.starting_player
    for idx in (sp, (sp + 1) % 2):
        if not skip_guarded or not window_skipped(state, idx, window_id):
            state = apply_auto_effects(state, window_id, idx)
    frame_players = _window_trigger_players(state, window_id,
                                            skip_guarded=skip_guarded)
    for idx in reversed(frame_players):
        state = push(state, PendingHarvestWindow(window_id=window_id, player_idx=idx))
    return state, bool(frame_players)


def _process_band_window(state: GameState, window_id: str, idx: int):
    """Run one simple harvest window for ONE player — a FIELD-band position
    (user ruling 3: within the FIELD segment each player resolves all their
    windows before the other player starts). Fire the player's automatic
    effects (skip-guarded), then push their PendingHarvestWindow choice frame
    if they have an eligible trigger. Returns (state, frame_pushed)."""
    if window_skipped(state, idx, window_id):
        return state, False
    state = apply_auto_effects(state, window_id, idx)
    if _has_window_trigger(state, idx, window_id):
        return push(state, PendingHarvestWindow(
            window_id=window_id, player_idx=idx)), True
    return state, False


def _field_phase_step(state: GameState, idx: int):
    """One player's FIELD during-window — harvest window #5, "field_phase"
    (HARVEST_WINDOWS_DESIGN.md §4). Returns (state, hosted): hosted True means
    the during-window host (PendingFieldPhase) is out and OWNS the rest of the
    window (the mandatory take gates its own exit), so the walk resumes PAST
    this position; False means the window is complete for this player.

    The step runs, in order:

    1. **Pre-take window autos, exactly once**: the "field_phase" autos
       (during-window flat state-readers, order-insensitive so anchored
       pre-take — Loom, Butter Churn, Treegardener's wood).
    2. **The during-window host or the inline take**: with an eligible
       "field_phase" trigger — or a choice-bearing take-modifier use — the
       PendingFieldPhase host is pushed; the take then rides it as the
       mandatory CommitFieldTake, orderable around the free-order triggers.
       Otherwise (the common path, and always the Family game) the take runs
       inline: the singular take event (ruling 5) + its per-occasion automatic
       effects — after which the trigger check runs ONCE MORE, because a
       per-occasion consequence can enable a trigger mid-window (Crack
       Weeder's take income affording Cube Cutter's exchange); if one is now
       eligible the host is pushed post-take (take_fired=True — exit-gated
       form).

    A field-phase-skipping player (Lunchtime Beer, when it lands) skips the
    whole window — no autos, no frames, NO take (ruling 1: a skipped phase
    has no boundaries, and no effect either).
    """
    if window_skipped(state, idx, "field_phase"):
        return state, False

    state = apply_auto_effects(state, "field_phase", idx)      # window autos

    # Host the during-window frame when the player has a decision there: an
    # eligible optional trigger, or a choice-bearing take-MODIFIER whose use is
    # picked on the take commit itself (Stable Manure — ruling 11: its extras
    # fold into the one take event, so the choice surfaces as CommitFieldTake
    # variants at the frame).
    if (_has_window_trigger(state, idx, "field_phase")
            or choice_take_modifiers(state, idx)):
        return push(state, PendingFieldPhase(player_idx=idx)), True

    # Inline take (no decision): fold in the auto take-modifiers (Scythe
    # Worker's mandatory-max — empty on the Family fast path) and run the one
    # simultaneous event.
    extras = auto_take_fold_ins(state, idx)
    state, occasion = field_take(state, idx, extra_takes=extras or None)
    state, occ_autos = apply_harvest_occasion_autos(state, idx, occasion)
    # A per-occasion consequence may have just ENABLED a during-window trigger
    # (Crack Weeder's take income making Cube Cutter's exchange affordable):
    # the window isn't over, so re-check and host the frame POST-take — it
    # opens with the take already fired (exit-gated form: triggers + Proceed).
    # Family fast path: an empty registry lookup.
    hosted = False
    if _has_window_trigger(state, idx, "field_phase"):
        state = push(state, PendingFieldPhase(
            player_idx=idx, take_fired=True, occasions=(occasion,)))
        hosted = True
    # The occasion's OPTIONAL reactions (Potato Ridger, Food Merchant) host
    # last, on top — the innermost, just-emitted event resolves first, then
    # any during-window triggers beneath. Family fast path: empty registry.
    state, occ_hosted = maybe_host_occasion_triggers(
        state, idx, occasion, autos_fired=occ_autos)
    return state, hosted or occ_hosted


def _advance_harvest(state: GameState) -> GameState:
    """One step of the harvest-window walk (HARVEST_WINDOWS_DESIGN.md §1-§4).

    Called by _advance_until_decision whenever the phase is a harvest phase and
    the stack is empty. Walks the VIRTUAL ladder (`walk_position`: the raw
    window ladder with the FIELD, FEED, and BREED bands each repeated once per
    player, starting player first — rulings 3 + 40) from the resume point,
    processing simple windows (autos + choice frames), the per-player FIELD
    during-window (`_field_phase_step`), and the per-player FEED/BREED
    sentinels (fire that player's feeding income, push that player's frame) —
    until either frames are pushed (return; the outer Case-1 guard surfaces
    them), or the harvest completes into PREPARATION / BEFORE_SCORING.

    The harvest phase is derived from the walk position (the flip happens at
    each band's entry, so a whole band runs under one phase); the two outer
    windows after the BREED band run under HARVEST_BREED, as before ruling 40.

    Resume point: `state.harvest_cursor` when set — since ruling 40 (banded
    FEED/BREED) the cursor is carried across EVERY mid-walk pause, the Family
    game included (a Family mid-feed state now holds one payment frame and the
    cursor; the C++ twin mirrors this — the first Family-visible harvest-shape
    change of the arc). A None cursor is either the harvest's fresh start (a
    FIELD entry: walk from position 0, resetting both players' once-per-harvest
    conversion budget HERE, before the harvest's first conversion opportunity)
    or a LEGACY hand-built bare FEED/BREED state (tests pushing both players'
    frames at once via the compat initiators): both payments/breedings are
    done, so resume at the SECOND pass's after-window — the banded walk has no
    exact equivalent of the pre-banding both-players-done instant, and the
    first pass's after-window is skipped on this compat path (drive the real
    walk to exercise per-player after-windows).
    """
    cur = state.harvest_cursor
    if cur is None:
        if state.phase == Phase.HARVEST_FIELD:
            cur = 0
            if any(p.harvest_conversions_used for p in state.players):
                state = fast_replace(state, players=tuple(
                    fast_replace(p, harvest_conversions_used=frozenset())
                    for p in state.players))
        elif state.phase == Phase.HARVEST_FEED:
            cur = sentinel_position("after_feeding", 1)
        else:  # Phase.HARVEST_BREED
            cur = sentinel_position("after_breeding", 1)
    else:
        state = fast_replace(state, harvest_cursor=None)

    while cur < WALK_LENGTH:
        w_idx, band_player = walk_position(cur, state.starting_player)
        window_id = HARVEST_WINDOWS[w_idx]

        # The phase follows the walk position: HARVEST_FEED from the FEED
        # band's entry, HARVEST_BREED from the BREED band's entry through the
        # trailing outer windows (idempotent on band resumes).
        if w_idx >= BREED_BAND_START:
            if state.phase != Phase.HARVEST_BREED:
                state = fast_replace(state, phase=Phase.HARVEST_BREED)
        elif FEED_BAND_START <= w_idx <= FEED_BAND_END:
            if state.phase != Phase.HARVEST_FEED:
                state = fast_replace(state, phase=Phase.HARVEST_FEED)

        if window_id == "field_phase":
            state, hosted = _field_phase_step(state, band_player)
            if hosted:
                # The during-window host owns the rest of the window (its
                # mandatory take gates its own exit) — resume PAST it.
                return fast_replace(state, harvest_cursor=cur + 1)
            cur += 1
            continue

        if window_id == "feeding":
            state, pushed = _initiate_harvest_feed_for(state, band_player)
            cur += 1
            if pushed:
                return fast_replace(state, harvest_cursor=cur)
            continue

        if window_id == "breeding":
            state, pushed = _initiate_harvest_breed_for(state, band_player)
            cur += 1
            if pushed:
                return fast_replace(state, harvest_cursor=cur)
            continue

        if band_player is None:
            state, pushed = _process_simple_window(state, window_id)
        else:
            state, pushed = _process_band_window(state, window_id, band_player)
        cur += 1
        if pushed:
            return fast_replace(state, harvest_cursor=cur)

    # The ladder is walked: the harvest is over.
    if state.round_number >= NUM_ROUNDS:
        return fast_replace(state, phase=Phase.BEFORE_SCORING, harvest_cursor=None)
    return fast_replace(state, phase=Phase.PREPARATION, harvest_cursor=None)


def _resolve_harvest_field(state: GameState) -> GameState:
    """Compatibility alias: enter the harvest-window walk at the FIELD phase.

    The pre-window engine resolved the whole FIELD phase (take + FEED push) in
    this one call, and many card tests drive it by this name. The walk is
    equivalent whenever no card is registered on the windows it threads between
    those steps — true for every legacy caller. New code calls _advance_harvest
    via _advance_until_decision instead.
    """
    assert state.phase == Phase.HARVEST_FIELD, state.phase
    return _advance_harvest(state)
