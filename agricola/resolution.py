from __future__ import annotations

import dataclasses
from typing import Callable

from agricola.actions import (
    ChooseSubAction,
    CommitAccommodate,
    CommitBake,
    CommitBreed,
    CommitBuildMajor,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitHarvestConversion,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    PlaceWorker,
)
from agricola.constants import (
    COOKING_HEARTH_INDICES,
    FIREPLACE_INDICES,
    MAJOR_IMPROVEMENT_COSTS,
    CellType,
    HouseMaterial,
)
from agricola.fences import (
    NUM_COLS,
    apply_fence_edges_h,
    apply_fence_edges_v,
    compute_new_fence_edges,
)
from agricola.helpers import breeding_food_gained, cooking_rates
from agricola.pasture import compute_pastures_from_arrays
from agricola.pending import (
    PendingBakeBread,
    PendingBuildFences,
    PendingBuildRooms,
    PendingBuildStables,
    PendingBuildMajor,
    PendingClayOven,
    PendingFarmRedevelopment,
    PendingGrainUtilization,
    PendingHarvestBreed,
    PendingHarvestFeed,
    PendingRenovate,
    PendingSow,
    PendingStoneOven,
    pop,
    push,
    replace_top,
)
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import Cell, GameState, PlayerState, get_space, with_space


# ---------------------------------------------------------------------------
# Internal state-update utilities
# ---------------------------------------------------------------------------

def _update_player(state: GameState, ap: int, new_player: PlayerState) -> GameState:
    """Return a new GameState with players[ap] replaced."""
    new_players = (
        new_player if ap == 0 else state.players[0],
        new_player if ap == 1 else state.players[1],
    )
    return fast_replace(state, players=new_players)


def _update_space(state: GameState, space_id: str, **kwargs) -> GameState:
    """Return a new GameState with the named action space updated."""
    old_space = get_space(state.board, space_id)
    new_space = fast_replace(old_space, **kwargs)
    new_board = with_space(state.board, space_id, new_space)
    return fast_replace(state, board=new_board)


def _new_grid_with_cell(
    grid: tuple, row: int, col: int, cell: Cell,
) -> tuple:
    """Return a new 3×5 grid identical to `grid` except at (row, col), which is replaced by `cell`."""
    new_row = tuple(
        cell if c == col else existing
        for c, existing in enumerate(grid[row])
    )
    return tuple(
        new_row if r == row else existing_row
        for r, existing_row in enumerate(grid)
    )


# ---------------------------------------------------------------------------
# Cross-cutting bookkeeping
# ---------------------------------------------------------------------------

def _apply_worker_placement(state: GameState, space_id: str) -> GameState:
    """Place the current player's worker on the space and decrement people_home.

    Handles exactly one worker (the parent/active worker). Wish handlers must
    add the newborn's second worker themselves after calling resolve_atomic's
    cross-cutting step.

    Does not touch current_player, phase, next_starting_player, or round_number.
    """
    ap = state.current_player

    # 1. Update workers on the action space
    old_w = get_space(state.board, space_id).workers
    new_workers = (
        old_w[0] + (1 if ap == 0 else 0),
        old_w[1] + (1 if ap == 1 else 0),
    )
    state = _update_space(state, space_id, workers=new_workers)

    # 2. Decrement active player's people_home
    p = state.players[ap]
    state = _update_player(state, ap, fast_replace(p, people_home=p.people_home - 1))

    return state


# ---------------------------------------------------------------------------
# Per-space handlers
# (each handler receives state AFTER _apply_worker_placement)
# ---------------------------------------------------------------------------

def _resolve_day_laborer(state: GameState) -> GameState:
    ap = state.current_player
    p = state.players[ap]
    return _update_player(state, ap, fast_replace(p, resources=p.resources + Resources(food=2)))


def _resolve_building_accumulation(state: GameState, space_id: str) -> GameState:
    """Shared handler for building-resource accumulation spaces.

    Adds space.accumulated (a Resources object) to the active player's resources,
    then resets accumulated to Resources().
    """
    ap = state.current_player
    p = state.players[ap]
    space_state = get_space(state.board, space_id)
    new_resources = p.resources + space_state.accumulated
    state = _update_player(state, ap, fast_replace(p, resources=new_resources))
    state = _update_space(state, space_id, accumulated=Resources())
    return state


def _resolve_food_accumulation(state: GameState, space_id: str) -> GameState:
    """Shared handler for food accumulation spaces (scalar accumulated_amount)."""
    ap = state.current_player
    p = state.players[ap]
    amount = get_space(state.board, space_id).accumulated_amount
    new_resources = p.resources + Resources(food=amount)
    state = _update_player(state, ap, fast_replace(p, resources=new_resources))
    state = _update_space(state, space_id, accumulated_amount=0)
    return state


def _resolve_fishing(state: GameState) -> GameState:
    return _resolve_food_accumulation(state, "fishing")


def _resolve_forest(state: GameState) -> GameState:
    return _resolve_building_accumulation(state, "forest")


def _resolve_clay_pit(state: GameState) -> GameState:
    return _resolve_building_accumulation(state, "clay_pit")


def _resolve_reed_bank(state: GameState) -> GameState:
    return _resolve_building_accumulation(state, "reed_bank")


def _resolve_grain_seeds(state: GameState) -> GameState:
    ap = state.current_player
    p = state.players[ap]
    return _update_player(state, ap, fast_replace(p, resources=p.resources + Resources(grain=1)))


def _become_starting_player(state: GameState, idx: int) -> GameState:
    """Transfer the starting-player token to player `idx`. Shared by the family
    Meeting Place (food accumulation + SP) and the card Meeting Place (SP only)."""
    return fast_replace(state, starting_player=idx)


def _resolve_meeting_place(state: GameState) -> GameState:
    from agricola.constants import GameMode
    if state.mode is GameMode.CARDS:
        return _initiate_meeting_place_cards(state)
    ap = state.current_player
    # Family game: collect accumulated food, reset, and become starting player.
    state = _resolve_food_accumulation(state, "meeting_place")
    return _become_starting_player(state, ap)


def _initiate_meeting_place_cards(state: GameState) -> GameState:
    """Card-game Meeting Place: become starting player (immediate, no food), then
    OPTIONALLY play one minor. Push the single-optional Proceed-host frame
    (PendingMeetingPlace; SPACE_HOST_REFACTOR.md §7) only when a minor is playable;
    otherwise become-SP is the whole action (atomic). The worker is already placed
    (cross-cutting), so this is always a legal placement. Fires before_action_space
    autos at the push. See CARD_IMPLEMENTATION_PLAN.md I.3."""
    ap = state.current_player
    state = _become_starting_player(state, ap)
    from agricola.legality import playable_minors
    if playable_minors(state, ap):
        from agricola.pending import PendingMeetingPlace
        from agricola.cards.triggers import apply_auto_effects
        state = push(state, PendingMeetingPlace(
            player_idx=ap, initiated_by_id="space:meeting_place",
        ))
        state = apply_auto_effects(state, "before_action_space", ap)
    return state


def _resolve_western_quarry(state: GameState) -> GameState:
    return _resolve_building_accumulation(state, "western_quarry")


def _resolve_vegetable_seeds(state: GameState) -> GameState:
    ap = state.current_player
    p = state.players[ap]
    return _update_player(state, ap, fast_replace(p, resources=p.resources + Resources(veg=1)))


def _resolve_eastern_quarry(state: GameState) -> GameState:
    return _resolve_building_accumulation(state, "eastern_quarry")


def _resolve_wish_for_children(state: GameState, space_id: str) -> GameState:
    """Shared handler for Basic and Urgent Wish for Children.

    _apply_worker_placement has already placed the parent (workers[ap] == 1).
    This handler adds the newborn: workers[ap] becomes 2, people_total += 1,
    newborns += 1. people_home is NOT incremented for the newborn.
    """
    ap = state.current_player

    # Add newborn worker to the space (parent already there from cross-cutting)
    old_w = get_space(state.board, space_id).workers
    new_workers = (
        old_w[0] + (1 if ap == 0 else 0),
        old_w[1] + (1 if ap == 1 else 0),
    )
    state = _update_space(state, space_id, workers=new_workers)

    # Update player: people_total and newborns
    p = state.players[ap]
    new_player = fast_replace(
        p,
        people_total=p.people_total + 1,
        newborns=p.newborns + 1,
    )
    return _update_player(state, ap, new_player)


def _resolve_basic_wish_for_children(state: GameState) -> GameState:
    from agricola.constants import GameMode
    if state.mode is GameMode.CARDS:
        # Non-atomic (mirrors House Redevelopment): a parent frame sequences the
        # mandatory family growth then an optional minor. Growth and minor run as
        # sub-actions of that frame, not here. (Urgent Wish stays atomic.)
        from agricola.pending import PendingBasicWishForChildren
        return push(state, PendingBasicWishForChildren(
            player_idx=state.current_player,
            initiated_by_id="space:basic_wish_for_children",
        ))
    # Family game: atomic family growth (unchanged).
    return _resolve_wish_for_children(state, "basic_wish_for_children")


def _resolve_urgent_wish_for_children(state: GameState) -> GameState:
    return _resolve_wish_for_children(state, "urgent_wish_for_children")


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

ATOMIC_HANDLERS: dict[str, Callable[[GameState], GameState]] = {
    "day_laborer":              _resolve_day_laborer,
    "fishing":                  _resolve_fishing,
    "forest":                   _resolve_forest,
    "clay_pit":                 _resolve_clay_pit,
    "reed_bank":                _resolve_reed_bank,
    "grain_seeds":              _resolve_grain_seeds,
    "meeting_place":            _resolve_meeting_place,
    "western_quarry":           _resolve_western_quarry,
    "vegetable_seeds":          _resolve_vegetable_seeds,
    "eastern_quarry":           _resolve_eastern_quarry,
    "basic_wish_for_children":  _resolve_basic_wish_for_children,
    "urgent_wish_for_children": _resolve_urgent_wish_for_children,
}


# ---------------------------------------------------------------------------
# Non-atomic initiators
# ---------------------------------------------------------------------------
#
# Each `_initiate_<space>` function pushes the space's parent pending and
# returns. The actual resolution of the action happens later, via committed
# sub-actions dispatched by the engine.

def _initiate_grain_utilization(state: GameState) -> GameState:
    """Initiate Grain Utilization by pushing PendingGrainUtilization."""
    return push(state, PendingGrainUtilization(
        player_idx=state.current_player,
        initiated_by_id="space:grain_utilization",
    ))


def _initiate_farmland(state: GameState) -> GameState:
    """Initiate Farmland by pushing the generic Delegating space host
    (PendingSubActionSpace) for "space:farmland"; its single sub-action is plow.
    Fires before_action_space autos at the push (a Family no-op)."""
    from agricola.pending import PendingSubActionSpace
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    state = push(state, PendingSubActionSpace(
        player_idx=ap, initiated_by_id="space:farmland",
    ))
    return apply_auto_effects(state, "before_action_space", ap)


def _initiate_cultivation(state: GameState) -> GameState:
    """Initiate Cultivation by pushing PendingCultivation."""
    from agricola.pending import PendingCultivation
    return push(state, PendingCultivation(
        player_idx=state.current_player,
        initiated_by_id="space:cultivation",
    ))


def _initiate_side_job(state: GameState) -> GameState:
    """Initiate Side Job by pushing PendingSideJob."""
    from agricola.pending import PendingSideJob
    return push(state, PendingSideJob(
        player_idx=state.current_player,
        initiated_by_id="space:side_job",
    ))


def _initiate_sheep_market(state: GameState) -> GameState:
    """Initiate Sheep Market: take all accumulated sheep onto the pending
    (staged, not yet on the player), zero the space's accumulated_amount,
    and push PendingSheepMarket."""
    from agricola.pending import PendingSheepMarket
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    gained = get_space(state.board, "sheep_market").accumulated_amount
    state = _update_space(state, "sheep_market", accumulated_amount=0)
    state = push(state, PendingSheepMarket(
        player_idx=ap, initiated_by_id="space:sheep_market", gained=gained,
    ))
    return apply_auto_effects(state, "before_action_space", ap)


def _initiate_pig_market(state: GameState) -> GameState:
    """Initiate Pig Market — same shape as Sheep Market."""
    from agricola.pending import PendingPigMarket
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    gained = get_space(state.board, "pig_market").accumulated_amount
    state = _update_space(state, "pig_market", accumulated_amount=0)
    state = push(state, PendingPigMarket(
        player_idx=ap, initiated_by_id="space:pig_market", gained=gained,
    ))
    return apply_auto_effects(state, "before_action_space", ap)


def _initiate_cattle_market(state: GameState) -> GameState:
    """Initiate Cattle Market — same shape as Sheep Market."""
    from agricola.pending import PendingCattleMarket
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    gained = get_space(state.board, "cattle_market").accumulated_amount
    state = _update_space(state, "cattle_market", accumulated_amount=0)
    state = push(state, PendingCattleMarket(
        player_idx=ap, initiated_by_id="space:cattle_market", gained=gained,
    ))
    return apply_auto_effects(state, "before_action_space", ap)


def _initiate_major_improvement(state: GameState) -> GameState:
    """Initiate the Major Improvement space by pushing the Delegating space host
    (PendingSubActionSpace) for "space:major_improvement" — the always-wrapper
    (SPACE_HOST_REFACTOR.md §6). Its single sub-action ("improvement") pushes
    PendingMajorMinorImprovement (the composite-action host), giving the space its
    own `action_space` surface (Plumber) above the composite's
    `major_minor_improvement` surface (Merchant). Fires before_action_space autos
    at the push (a Family no-op)."""
    from agricola.pending import PendingSubActionSpace
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    state = push(state, PendingSubActionSpace(
        player_idx=ap, initiated_by_id="space:major_improvement",
    ))
    return apply_auto_effects(state, "before_action_space", ap)


def _initiate_house_redevelopment(state: GameState) -> GameState:
    """Initiate House Redevelopment by pushing PendingHouseRedevelopment."""
    from agricola.pending import PendingHouseRedevelopment
    return push(state, PendingHouseRedevelopment(
        player_idx=state.current_player,
        initiated_by_id="space:house_redevelopment",
    ))


def _initiate_farm_expansion(state: GameState) -> GameState:
    """Initiate Farm Expansion by pushing PendingFarmExpansion."""
    from agricola.pending import PendingFarmExpansion
    return push(state, PendingFarmExpansion(
        player_idx=state.current_player,
        initiated_by_id="space:farm_expansion",
    ))


def _initiate_fencing(state: GameState) -> GameState:
    """Initiate Fencing by pushing the generic Delegating space host
    (PendingSubActionSpace) for "space:fencing"; its single sub-action is
    build_fences. Fires before_action_space autos at the push (a Family no-op)."""
    from agricola.pending import PendingSubActionSpace
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    state = push(state, PendingSubActionSpace(
        player_idx=ap, initiated_by_id="space:fencing",
    ))
    return apply_auto_effects(state, "before_action_space", ap)


def _initiate_farm_redevelopment(state: GameState) -> GameState:
    """Initiate Farm Redevelopment by pushing PendingFarmRedevelopment."""
    return push(state, PendingFarmRedevelopment(
        player_idx=state.current_player,
        initiated_by_id="space:farm_redevelopment",
    ))


def _initiate_lessons(state: GameState) -> GameState:
    """Initiate Lessons (card game) by pushing the Delegating space host
    (PendingSubActionSpace) for "space:lessons" — a single mandatory sub-action
    "play one occupation" (SPACE_HOST_REFACTOR.md §8). The space host's
    ChooseSubAction("play_occupation") computes THIS play's food cost and pushes
    PendingPlayOccupation; Lessons thereby gains the action_space surface for free.
    Fires before_action_space autos at the push."""
    from agricola.pending import PendingSubActionSpace
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    state = push(state, PendingSubActionSpace(
        player_idx=ap, initiated_by_id="space:lessons",
    ))
    return apply_auto_effects(state, "before_action_space", ap)


def _execute_play_occupation(state: GameState, idx: int, action) -> GameState:
    """Play one occupation from hand: debit the frame's cost, move the card
    hand->tableau, then run its on-play effect. Dispatched with auto_pop=True, so
    the PendingPlayOccupation frame is popped by the generic dispatcher afterward."""
    from agricola.cards.specs import OCCUPATIONS
    cid = action.card_id
    top = state.pending_stack[-1]   # PendingPlayOccupation — the play cost lives here
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - top.cost,
        hand_occupations=p.hand_occupations - {cid},
        occupations=p.occupations | {cid},
    )
    state = _update_player(state, idx, p)
    state = OCCUPATIONS[cid].on_play(state, idx)
    # No current occupation on_play pushes a frame, so PendingPlayOccupation is
    # still on top — pivot it to its after-phase (firing after_play_occupation
    # autos); the trailing Stop pops. A future pushing on_play would need the
    # record-before-apply treatment (cf. granted sub-actions).
    return _enter_after_phase(state)


def _execute_play_minor(state: GameState, idx: int, action) -> GameState:
    """Play one minor improvement from hand: debit its printed cost, move it
    hand->tableau (or, for a traveling minor, execute then PASS it to the
    opponent — never kept in the tableau), then run its on-play effect.
    Dispatched with auto_pop=True (PendingPlayMinor pops after). See
    CARD_IMPLEMENTATION_PLAN.md II.4."""
    from agricola.cards.specs import MINORS
    cid = action.card_id
    spec = MINORS[cid]
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - spec.cost.resources,
        animals=p.animals - spec.cost.animals,
        hand_minors=p.hand_minors - {cid},
    )
    if not spec.passing_left:                       # normal minor: keep in tableau
        p = fast_replace(p, minor_improvements=p.minor_improvements | {cid})
    state = _update_player(state, idx, p)
    state = spec.on_play(state, idx)                # immediate effect (runs either way)
    if spec.passing_left:                           # traveling minor: pass to the opponent
        opp = 1 - idx
        state = _update_player(state, opp, fast_replace(
            state.players[opp],
            hand_minors=state.players[opp].hand_minors | {cid},
        ))
    # Pivot PendingPlayMinor to its after-phase (firing after_play_minor autos);
    # the trailing Stop pops. (No current minor on_play pushes a frame.)
    return _enter_after_phase(state)


NONATOMIC_HANDLERS: dict[str, Callable[[GameState], GameState]] = {
    "grain_utilization":    _initiate_grain_utilization,
    "farmland":             _initiate_farmland,
    "cultivation":          _initiate_cultivation,
    "side_job":             _initiate_side_job,
    "sheep_market":         _initiate_sheep_market,
    "pig_market":           _initiate_pig_market,
    "cattle_market":        _initiate_cattle_market,
    "major_improvement":    _initiate_major_improvement,
    "house_redevelopment":  _initiate_house_redevelopment,
    "farm_expansion":       _initiate_farm_expansion,
    "fencing":              _initiate_fencing,
    "farm_redevelopment":   _initiate_farm_redevelopment,
    "lessons":              _initiate_lessons,   # card game only
}


# ---------------------------------------------------------------------------
# Choose-sub-action handlers
# ---------------------------------------------------------------------------
#
# Dispatch keyed by the type of the top-of-stack pending. Each handler
# receives (state, action) and returns the new state with the appropriate
# inner sub-action pending pushed.

def _choose_subaction_grain_utilization(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    if action.name == "sow":
        state = replace_top(state, fast_replace(top, sow_chosen=True))
        return push(state, PendingSow(
            player_idx=top.player_idx,
            initiated_by_id=top.PENDING_ID,
        ))
    if action.name == "bake_bread":
        state = replace_top(state, fast_replace(top, bake_chosen=True))
        return push(state, PendingBakeBread(
            player_idx=top.player_idx,
            initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(
        f"Unknown sub-action {action.name!r} for Grain Utilization"
    )


def _choose_subaction_subactionspace(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    """ChooseSubAction handler for the generic Delegating space host
    (PendingSubActionSpace; SPACE_HOST_REFACTOR.md §4.2/§8). Sets
    `subaction_complete=True` and pushes the single mandatory child, dispatched by
    the host's `space_id`. The child's `initiated_by_id` carries the space's id
    (not the generic "action_space" PENDING_ID) so existing provenance is
    preserved (e.g. PendingPlow.initiated_by_id == "farmland")."""
    top = state.pending_stack[-1]
    space_id = top.space_id
    state = replace_top(state, fast_replace(top, subaction_complete=True))
    p_idx = top.player_idx

    if space_id == "farmland" and action.name == "plow":
        from agricola.pending import PendingPlow
        return push(state, PendingPlow(player_idx=p_idx, initiated_by_id=space_id))
    if space_id == "fencing" and action.name == "build_fences":
        return push(state, PendingBuildFences(
            player_idx=p_idx, initiated_by_id=space_id,
        ))
    if space_id == "major_improvement" and action.name == "improvement":
        # Preserve the composite host's provenance "space:major_improvement"
        # (the old direct-push value), distinct from the House-Redev path's
        # "house_redevelopment".
        from agricola.pending import PendingMajorMinorImprovement
        return push(state, PendingMajorMinorImprovement(
            player_idx=p_idx, initiated_by_id=top.initiated_by_id,
        ))
    if space_id == "lessons" and action.name == "play_occupation":
        # Card game: compute THIS play's occupation cost (mirrors the old Lessons
        # initiator) and push the play-occupation primitive.
        from agricola.pending import PendingPlayOccupation
        from agricola.legality import occupation_cost
        cost = occupation_cost(len(state.players[p_idx].occupations))
        return push(state, PendingPlayOccupation(
            player_idx=p_idx, initiated_by_id="space:lessons", cost=cost,
        ))
    raise ValueError(
        f"Unknown sub-action {action.name!r} for space host {space_id!r}"
    )


def _choose_subaction_cultivation(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    from agricola.pending import PendingPlow
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    if action.name == "plow":
        state = replace_top(state, fast_replace(top, plow_chosen=True))
        return push(state, PendingPlow(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    if action.name == "sow":
        state = replace_top(state, fast_replace(top, sow_chosen=True))
        return push(state, PendingSow(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for Cultivation")


def _choose_subaction_side_job(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    if action.name == "build_stables":
        state = replace_top(state, fast_replace(top, stable_chosen=True))
        return push(state, PendingBuildStables(
            player_idx=p_idx,
            initiated_by_id=top.PENDING_ID,
            cost=Resources(wood=1),
            max_builds=1,
        ))
    if action.name == "bake_bread":
        state = replace_top(state, fast_replace(top, bake_chosen=True))
        return push(state, PendingBakeBread(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for Side Job")


def _choose_subaction_major_minor_improvement(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    if action.name == "build_major":
        state = replace_top(state, fast_replace(top, major_chosen=True))
        return push(state, PendingBuildMajor(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    if action.name == "play_minor":
        # Card game: the OR-alternative. Mark minor_chosen (so the parent won't
        # also offer build_major) and push the play-minor frame; you picked the
        # minor branch, so you play exactly one (PendingPlayMinor has no decline —
        # the skip, where allowed, is the parent's Stop before choosing).
        from agricola.pending import PendingPlayMinor
        state = replace_top(state, fast_replace(top, minor_chosen=True))
        return push(state, PendingPlayMinor(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for Major/Minor Improvement")


def _choose_subaction_clay_oven(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    if action.name == "bake_bread":
        state = replace_top(state, fast_replace(top, bake_chosen=True))
        return push(state, PendingBakeBread(
            player_idx=top.player_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for Clay Oven")


def _choose_subaction_stone_oven(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    top = state.pending_stack[-1]
    if action.name == "bake_bread":
        state = replace_top(state, fast_replace(top, bake_chosen=True))
        return push(state, PendingBakeBread(
            player_idx=top.player_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for Stone Oven")


def _choose_subaction_house_redevelopment(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    from agricola.pending import PendingMajorMinorImprovement
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    p = state.players[p_idx]
    if action.name == "renovate":
        # Compute renovation cost at push time. The pending carries the cost
        # so future card triggers / alternate-formula choose handlers can
        # vary it without changing _execute_renovate.
        num_rooms = sum(
            1 for r in range(3) for c in range(5)
            if p.farmyard.grid[r][c].cell_type == CellType.ROOM
        )
        if p.house_material == HouseMaterial.WOOD:
            cost = Resources(clay=num_rooms, reed=1)  # 1 clay per room, 1 reed total
        else:  # CLAY — STONE filtered out by _can_renovate at parent enumerator
            cost = Resources(stone=num_rooms, reed=1)
        state = replace_top(state, fast_replace(top, renovate_chosen=True))
        return push(state, PendingRenovate(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID, cost=cost,
        ))
    if action.name == "improvement":
        state = replace_top(state, fast_replace(top, improvement_chosen=True))
        return push(state, PendingMajorMinorImprovement(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for House Redevelopment")


def _choose_subaction_farm_expansion(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    from agricola.constants import ROOM_COSTS
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    p = state.players[p_idx]
    if action.name == "build_rooms":
        state = replace_top(state, fast_replace(top, room_chosen=True))
        return push(state, PendingBuildRooms(
            player_idx=p_idx,
            initiated_by_id=top.PENDING_ID,
            cost=ROOM_COSTS[p.house_material],
            max_builds=None,
        ))
    if action.name == "build_stables":
        state = replace_top(state, fast_replace(top, stable_chosen=True))
        return push(state, PendingBuildStables(
            player_idx=p_idx,
            initiated_by_id=top.PENDING_ID,
            cost=Resources(wood=2),
            max_builds=None,
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for Farm Expansion")


def _choose_subaction_farm_redevelopment(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    """Choose handler for Farm Redevelopment.

    Mirrors `_choose_subaction_house_redevelopment` with the optional branch
    swapped from "improvement" to "build_fences". Renovate cost is computed
    here at push time using the same formula as House Redevelopment.
    """
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFarmRedevelopment)
    p_idx = top.player_idx
    p = state.players[p_idx]
    if action.name == "renovate":
        num_rooms = sum(
            1 for r in range(3) for c in range(5)
            if p.farmyard.grid[r][c].cell_type == CellType.ROOM
        )
        if p.house_material == HouseMaterial.WOOD:
            cost = Resources(clay=num_rooms, reed=1)
        else:  # CLAY (STONE filtered out by _can_renovate at the parent enumerator)
            cost = Resources(stone=num_rooms, reed=1)
        state = replace_top(state, fast_replace(top, renovate_chosen=True))
        return push(state, PendingRenovate(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID, cost=cost,
        ))
    if action.name == "build_fences":
        state = replace_top(state, fast_replace(top, build_fences_chosen=True))
        return push(state, PendingBuildFences(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for Farm Redevelopment")


def _choose_subaction_basic_wish_for_children(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    """Card-game choose handler for Basic Wish (mirrors House Redevelopment).
    `family_growth` (mandatory first) pushes the PendingFamilyGrowth primitive;
    `play_minor` (optional, after growth) pushes the mandatory PendingPlayMinor.
    The parent's *_done/_chosen flag is set at choose-time (invariant 7)."""
    top = state.pending_stack[-1]
    if action.name == "family_growth":
        from agricola.pending import PendingFamilyGrowth
        state = replace_top(state, fast_replace(top, family_growth_done=True))
        return push(state, PendingFamilyGrowth(
            player_idx=top.player_idx, initiated_by_id=top.PENDING_ID,
        ))
    if action.name == "play_minor":
        from agricola.pending import PendingPlayMinor
        state = replace_top(state, fast_replace(top, minor_chosen=True))
        return push(state, PendingPlayMinor(
            player_idx=top.player_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for Basic Wish for Children")


def _choose_subaction_meeting_place(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    """Card-game Meeting Place choose handler: `play_minor` pushes the mandatory
    PendingPlayMinor (become-SP already happened immediately in the resolver)."""
    top = state.pending_stack[-1]
    if action.name == "play_minor":
        from agricola.pending import PendingPlayMinor
        state = replace_top(state, fast_replace(top, minor_chosen=True))
        return push(state, PendingPlayMinor(
            player_idx=top.player_idx, initiated_by_id=top.PENDING_ID,
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for Meeting Place")


def _execute_family_growth(state: GameState, idx: int, action) -> GameState:
    """Run the family-growth primitive: add one newborn on the space named by the
    PendingFamilyGrowth frame's initiated_by_id (the wish space). Reuses the shared
    growth logic; dispatched with auto_pop=True (the frame pops after)."""
    space_id = state.pending_stack[-1].initiated_by_id
    state = _resolve_wish_for_children(state, space_id)
    return _enter_after_phase(state)   # pivot PendingFamilyGrowth -> after; Stop pops


CHOOSE_SUBACTION_HANDLERS: dict[type, Callable[[GameState, ChooseSubAction], GameState]] = {}
# Populated below after parent pending types are imported.
from agricola.pending import (
    PendingBasicWishForChildren,
    PendingCultivation,
    PendingFarmExpansion,
    PendingHouseRedevelopment,
    PendingMajorMinorImprovement,
    PendingMeetingPlace,
    PendingSideJob,
    PendingSubActionSpace,
)
CHOOSE_SUBACTION_HANDLERS[PendingGrainUtilization] = _choose_subaction_grain_utilization
CHOOSE_SUBACTION_HANDLERS[PendingSubActionSpace] = _choose_subaction_subactionspace
CHOOSE_SUBACTION_HANDLERS[PendingCultivation] = _choose_subaction_cultivation
CHOOSE_SUBACTION_HANDLERS[PendingSideJob] = _choose_subaction_side_job
CHOOSE_SUBACTION_HANDLERS[PendingMajorMinorImprovement] = _choose_subaction_major_minor_improvement
CHOOSE_SUBACTION_HANDLERS[PendingClayOven] = _choose_subaction_clay_oven
CHOOSE_SUBACTION_HANDLERS[PendingStoneOven] = _choose_subaction_stone_oven
CHOOSE_SUBACTION_HANDLERS[PendingHouseRedevelopment] = _choose_subaction_house_redevelopment
CHOOSE_SUBACTION_HANDLERS[PendingFarmExpansion] = _choose_subaction_farm_expansion
CHOOSE_SUBACTION_HANDLERS[PendingFarmRedevelopment] = _choose_subaction_farm_redevelopment
CHOOSE_SUBACTION_HANDLERS[PendingBasicWishForChildren] = _choose_subaction_basic_wish_for_children
CHOOSE_SUBACTION_HANDLERS[PendingMeetingPlace] = _choose_subaction_meeting_place


# ---------------------------------------------------------------------------
# Sub-action effect functions (used by engine.py)
# ---------------------------------------------------------------------------

def _enter_after_phase(state: GameState) -> GameState:
    """Open a host frame's after-window: flip the top frame to `phase="after"`
    (no pop) and fire its after-automatic effects, then return.

    The single, uniform "after-window opens" point (SUBACTION_HOOK_REFACTOR.md).
    Called by every commit-terminated sub-action effect at its commit, by the
    animal markets, and (with the Proceed boundary) by the and/or-space parents.
    The fired event is derived from the now-"after" frame via
    `legality.trigger_event` — `after_action_space` for an action-space host,
    `after_<PENDING_ID>` for a sub-action host (e.g. `after_renovate`). A no-op
    in the Family game (empty AUTO_EFFECTS); the after-phase enumerator then
    surfaces any after-triggers + Stop, and Stop pops.
    """
    from agricola.cards.triggers import apply_auto_effects
    from agricola.legality import trigger_event
    new_top = fast_replace(state.pending_stack[-1], phase="after")
    state = replace_top(state, new_top)
    return apply_auto_effects(state, trigger_event(new_top), new_top.player_idx)


def _execute_sow(
    state: GameState,
    player_idx: int,
    commit: CommitSow,
) -> GameState:
    """Sow grain and/or veg onto empty field cells.

    Per RULES.md: 1 grain from supply → 3 grain on field (1 from supply + 2
    from general supply). 1 veg from supply → 2 veg on field (1 from supply
    + 1 from general supply). Empty field cells are filled in canonical
    (row, col) order; grain is sown first if both are committed.

    Preconditions: legality has verified grain + veg <= empty_fields and
    grain <= p.resources.grain and veg <= p.resources.veg.
    """
    grain = commit.grain
    veg = commit.veg
    p = state.players[player_idx]

    # Subtract from supply.
    new_resources = p.resources - Resources(grain=grain, veg=veg)

    # Walk the grid in canonical order, filling empty fields.
    g_remaining, v_remaining = grain, veg
    new_grid_rows = []
    for r in range(3):
        new_row = []
        for c in range(5):
            cell = p.farmyard.grid[r][c]
            if (cell.cell_type == CellType.FIELD
                    and cell.grain == 0 and cell.veg == 0):
                # Empty field — fill grain first, then veg.
                if g_remaining > 0:
                    new_row.append(fast_replace(cell, grain=3))
                    g_remaining -= 1
                elif v_remaining > 0:
                    new_row.append(fast_replace(cell, veg=2))
                    v_remaining -= 1
                else:
                    new_row.append(cell)
            else:
                new_row.append(cell)
        new_grid_rows.append(tuple(new_row))

    assert g_remaining == 0 and v_remaining == 0, (
        f"Sow targets exceeded empty field count; legality should have caught this. "
        f"grain remaining={g_remaining}, veg remaining={v_remaining}"
    )

    new_farmyard = fast_replace(p.farmyard, grid=tuple(new_grid_rows))
    new_player = fast_replace(
        p, resources=new_resources, farmyard=new_farmyard,
    )
    state = _update_player(state, player_idx, new_player)
    return _enter_after_phase(state)   # pivot PendingSow -> after; Stop pops


def _execute_bake(
    state: GameState, player_idx: int, commit: CommitBake,
) -> GameState:
    """Bake `commit.grain` grain into food using greedy-by-rate allocation
    across all owned baking improvements.

    Calls `baking_specs_for_player` to collect (cap, rate) tuples from
    major improvements (via `BAKING_IMPROVEMENT_SPECS`) plus any card-
    registered baking sources (via `BAKING_SPEC_EXTENSIONS`). Sources are
    consumed in rate-descending order: each source gets up to its `cap`
    grain (or all remaining grain if its cap is None).

    Precondition (enforced by `_enumerate_pending_bake_bread`):
    `commit.grain` does not exceed the player's per-action grain cap.
    """
    from agricola.legality import baking_specs_for_player
    specs = baking_specs_for_player(state, player_idx)
    grain_remaining = commit.grain
    food = 0
    for cap, rate in sorted(specs, key=lambda s: s[1], reverse=True):
        used = grain_remaining if cap is None else min(cap, grain_remaining)
        food += used * rate
        grain_remaining -= used
        if grain_remaining == 0:
            break
    assert grain_remaining == 0, (
        f"CommitBake(grain={commit.grain}) exceeds player's per-action grain cap"
    )
    p = state.players[player_idx]
    new_player = fast_replace(
        p,
        resources=p.resources + Resources(food=food, grain=-commit.grain),
    )
    state = _update_player(state, player_idx, new_player)
    return _enter_after_phase(state)   # pivot PendingBakeBread -> after; Stop pops


def _execute_plow(
    state: GameState, player_idx: int, commit: CommitPlow,
) -> GameState:
    """Plow the cell at (commit.row, commit.col).

    Precondition (enforced by `_enumerate_pending_plow`): (row, col) is a
    legal plow cell (EMPTY, non-enclosed, adjacent to existing field or
    the first field on the farm).
    """
    p = state.players[player_idx]
    new_grid = _new_grid_with_cell(
        p.farmyard.grid, commit.row, commit.col, Cell(cell_type=CellType.FIELD),
    )
    new_farmyard = fast_replace(p.farmyard, grid=new_grid)
    new_player = fast_replace(p, farmyard=new_farmyard)
    state = _update_player(state, player_idx, new_player)
    return _enter_after_phase(state)   # pivot PendingPlow -> after; Stop pops


def _execute_build_stable(
    state: GameState, player_idx: int, commit: CommitBuildStable,
) -> GameState:
    """Multi-shot stable build: place one stable, increment num_built, leave
    PendingBuildStables on top (dispatcher's auto_pop=False).

    The cost is on the pending frame (set at push time by the choose
    handler) — different callers (Side Job, Farm Expansion, future cards)
    specify different costs.

    Recomputes Farmyard.pastures explicitly: a stable placed inside an
    existing pasture changes that pasture's num_stables (and capacity).
    Although no pasture can yet exist in current scope (Fencing is
    unimplemented and no other resolver builds fences), this is the
    documented convention for pasture-changing resolvers
    (ENGINE_IMPLEMENTATION.md §4.1 — the Farmyard.pastures caching
    exception) — fixes the latent bug in Task 5C's version and means
    Fencing won't have to revisit this function later.
    """
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildStables)
    p = state.players[player_idx]
    new_grid = _new_grid_with_cell(
        p.farmyard.grid, commit.row, commit.col, Cell(cell_type=CellType.STABLE),
    )
    new_farmyard = fast_replace(
        p.farmyard,
        grid=new_grid,
        pastures=compute_pastures_from_arrays(
            new_grid, p.farmyard.horizontal_fences, p.farmyard.vertical_fences,
        ),
    )
    new_player = fast_replace(
        p, resources=p.resources - top.cost, farmyard=new_farmyard,
    )
    state = _update_player(state, player_idx, new_player)
    return replace_top(state, fast_replace(top, num_built=top.num_built + 1))


def _execute_build_room(
    state: GameState, player_idx: int, commit: CommitBuildRoom,
) -> GameState:
    """Multi-shot room build: place one room, increment num_built, leave
    PendingBuildRooms on top (dispatcher's auto_pop=False).

    Pasture cache is unaffected: rooms cannot legally land in enclosed
    cells (RULES.md "House and Rooms"); `_legal_room_cells` enforces this.

    people_total is unchanged here — a newly built room is empty until
    populated by a Wish for Children action.
    """
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms)
    p = state.players[player_idx]
    new_grid = _new_grid_with_cell(
        p.farmyard.grid, commit.row, commit.col, Cell(cell_type=CellType.ROOM),
    )
    new_farmyard = fast_replace(p.farmyard, grid=new_grid)
    new_player = fast_replace(
        p, resources=p.resources - top.cost, farmyard=new_farmyard,
    )
    state = _update_player(state, player_idx, new_player)
    return replace_top(state, fast_replace(top, num_built=top.num_built + 1))


def _execute_renovate(
    state: GameState, player_idx: int, commit: CommitRenovate,
) -> GameState:
    """Renovate all rooms to the next material tier, paying `pending.cost`.

    The cost is on the pending frame (set at push time by the choose
    handler). Material transition (WOOD->CLAY or CLAY->STONE) is derived
    from the player's current `house_material`.
    """
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingRenovate)
    p = state.players[player_idx]
    if p.house_material == HouseMaterial.WOOD:
        new_material = HouseMaterial.CLAY
    elif p.house_material == HouseMaterial.CLAY:
        new_material = HouseMaterial.STONE
    else:
        raise AssertionError("CommitRenovate illegal on stone house")
    new_player = fast_replace(
        p, resources=p.resources - pending.cost, house_material=new_material,
    )
    state = _update_player(state, player_idx, new_player)
    return _enter_after_phase(state)   # pivot PendingRenovate -> after; Stop pops


def _execute_build_major(
    state: GameState, player_idx: int, commit: CommitBuildMajor,
) -> GameState:
    """Apply CommitBuildMajor end-to-end: pay cost, assign ownership,
    handle Well's future-resources, set build_chosen, and either pop
    PendingBuildMajor (non-oven majors) or push the oven wrapper
    (Clay/Stone Oven, hosting the optional free Bake Bread).

    Dispatched via the generic `_apply_commit_subaction` path with
    `auto_pop=False` — the dispatcher does NOT pop after the effect runs.
    This function owns all its own stack manipulation: pop for non-ovens
    (line below), or push the wrapper for ovens (leaving PendingBuildMajor
    in place underneath).
    """
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor)
    p = state.players[player_idx]
    cost = MAJOR_IMPROVEMENT_COSTS[commit.major_idx]

    # 1. Pay: either deduct cost, or return a Fireplace (Cooking Hearth only).
    if commit.return_fireplace_idx is None:
        new_player = fast_replace(p, resources=p.resources - cost)
        state = _update_player(state, player_idx, new_player)
    else:
        assert commit.major_idx in COOKING_HEARTH_INDICES, (
            "return_fireplace_idx only valid for Cooking Hearth purchase"
        )
        assert commit.return_fireplace_idx in FIREPLACE_INDICES
        owners = state.board.major_improvement_owners
        assert owners[commit.return_fireplace_idx] == player_idx, (
            "must own the Fireplace being returned"
        )
        new_owners = tuple(
            None if i == commit.return_fireplace_idx else owners[i]
            for i in range(len(owners))
        )
        state = fast_replace(
            state,
            board=fast_replace(state.board, major_improvement_owners=new_owners),
        )

    # 2. Assign the new major to the player.
    owners = state.board.major_improvement_owners
    new_owners = tuple(
        player_idx if i == commit.major_idx else owners[i]
        for i in range(len(owners))
    )
    state = fast_replace(
        state,
        board=fast_replace(state.board, major_improvement_owners=new_owners),
    )

    # 3. Well's special effect: +1 food on each of the next 5 round spaces.
    if commit.major_idx == 4:  # Well
        p = state.players[player_idx]
        new_future = list(p.future_resources)
        # future_resources[r] holds goods promised for round r+1 (0-indexed).
        for r in range(state.round_number, min(state.round_number + 5, 14)):
            new_future[r] = new_future[r] + Resources(food=1)
        new_player = fast_replace(p, future_resources=tuple(new_future))
        state = _update_player(state, player_idx, new_player)

    # 4. Pivot PendingBuildMajor to its after-phase (no pop), firing
    #    after_build_major automatic effects. Done BEFORE pushing any oven
    #    wrapper so that when the wrapper's free bake pops back, this frame is
    #    already "after" (offering after_build_major triggers + Stop). `phase`
    #    now carries what `build_chosen` used to — the after-gate keys on it.
    state = _enter_after_phase(state)

    # 5. Branch on major_idx for the oven wrappers; otherwise leave the
    #    after-phase frame for its trailing Stop.
    if commit.major_idx == 5:  # Clay Oven
        return push(state, PendingClayOven(
            player_idx=player_idx, initiated_by_id="build_major",
        ))
    if commit.major_idx == 6:  # Stone Oven
        return push(state, PendingStoneOven(
            player_idx=player_idx, initiated_by_id="build_major",
        ))

    # Non-oven: the after-phase PendingBuildMajor stays; Stop pops it.
    return state


def _execute_build_pasture(
    state: GameState, player_idx: int, commit: CommitBuildPasture,
) -> GameState:
    """Multi-shot pasture build: place one pasture's fences, increment the
    PendingBuildFences counters, leave the pending on top (auto_pop=False).

    Steps:
      1. Pack commit.cells to a bitmap.
      2. Determine new-pasture vs subdivision (against the BEFORE-commit
         farmyard) so the ordering-rule flag is correctly updated.
      3. Compute new fence edges + wood cost via `compute_new_fence_edges`.
      4. Apply the new edges to the fence arrays.
      5. Recompute the pasture decomposition (`compute_pastures_from_arrays`).
         This is the second pasture-changing effect function in the engine
         (alongside `_execute_build_stable`).
      6. Debit wood.
      7. Update player.
      8. Increment counters on PendingBuildFences and OR in subdivision_started
         if this commit was a subdivision.
    """
    p = state.players[player_idx]
    farmyard = p.farmyard

    # 1. Pack cells to bitmap.
    cells_bm = sum(1 << (r * NUM_COLS + c) for (r, c) in commit.cells)

    # 2. Determine new-pasture vs subdivision (pre-commit farmyard).
    existing_pasture_cells_bm = 0
    for P in farmyard.pastures:
        for (r, c) in P.cells:
            existing_pasture_cells_bm |= 1 << (r * NUM_COLS + c)
    is_subdivision = bool(cells_bm & existing_pasture_cells_bm)

    # 3. Compute new-edge deltas + cost.
    h_new, v_new, wood_cost = compute_new_fence_edges(farmyard, cells_bm)

    # 4. Apply fence-array updates.
    new_h = apply_fence_edges_h(farmyard.horizontal_fences, h_new)
    new_v = apply_fence_edges_v(farmyard.vertical_fences, v_new)

    # 5. Recompute pasture decomposition.
    new_pastures = compute_pastures_from_arrays(farmyard.grid, new_h, new_v)
    new_farmyard = fast_replace(
        farmyard, horizontal_fences=new_h, vertical_fences=new_v,
        pastures=new_pastures,
    )

    # 6 + 7. Debit wood + update player.
    new_resources = p.resources - Resources(wood=wood_cost)
    new_player = fast_replace(
        p, farmyard=new_farmyard, resources=new_resources,
    )
    state = _update_player(state, player_idx, new_player)

    # 8. Bump pending counters + ordering-rule flag. No auto-pop; Stop pops.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    new_top = fast_replace(
        top,
        pastures_built=top.pastures_built + 1,
        fences_built=top.fences_built + wood_cost,
        subdivision_started=top.subdivision_started or is_subdivision,
    )
    return replace_top(state, new_top)


def _execute_accommodate(
    state: GameState, player_idx: int, commit: CommitAccommodate,
) -> GameState:
    """Finalize animal market: set player's (sheep, boar, cattle) to the
    chosen frontier point, convert any excess to food at the player's
    cooking rates.

    Lands directly on PendingSheepMarket / PendingPigMarket /
    PendingCattleMarket (no separate sub-action pending exists for animal
    markets). Reads `pending.gained` to determine which animal type was
    newly gained from the space.

    Dispatched with auto_pop=False (4b): instead of popping, this is the market's
    before->after pivot — it applies the accommodation, flips the host frame to
    `phase="after"`, and fires after_action_space automatic effects at that flip
    (the work-complete boundary, before the after-triggers — SPACE_HOST_REFACTOR.md
    §11). The after-phase enumerator then offers any after-triggers + Stop, and Stop
    pops (pure pop now — engine._apply_stop fires nothing).
    """
    from agricola.pending import PendingSheepMarket, PendingPigMarket, PendingCattleMarket
    pending = state.pending_stack[-1]
    assert isinstance(pending, (PendingSheepMarket, PendingPigMarket, PendingCattleMarket))
    p = state.players[player_idx]
    # Animal markets don't convert veg; slice to the (sheep, boar, cattle) triple.
    rates = cooking_rates(state, player_idx)[:3]

    # Compute "available" per type (player's existing + gained for this market only).
    s_avail = p.animals.sheep + (pending.gained if isinstance(pending, PendingSheepMarket) else 0)
    b_avail = p.animals.boar  + (pending.gained if isinstance(pending, PendingPigMarket) else 0)
    c_avail = p.animals.cattle + (pending.gained if isinstance(pending, PendingCattleMarket) else 0)

    # Food = excess released at cooking rates.
    food = (
        (s_avail - commit.sheep)  * rates[0]
        + (b_avail - commit.boar)   * rates[1]
        + (c_avail - commit.cattle) * rates[2]
    )

    new_animals = Animals(sheep=commit.sheep, boar=commit.boar, cattle=commit.cattle)
    new_resources = p.resources + Resources(food=food)
    new_player = fast_replace(p, animals=new_animals, resources=new_resources)
    state = _update_player(state, player_idx, new_player)
    # Pivot to the after-phase (do NOT pop) and fire after_action_space autos at
    # this work-complete boundary (before the after-triggers). _enter_after_phase
    # flips the frame + fires the derived `after_action_space` event.
    return _enter_after_phase(state)


# ---------------------------------------------------------------------------
# Harvest sub-action effect functions (Task 7)
# ---------------------------------------------------------------------------

def _execute_harvest_conversion(
    state: GameState, player_idx: int, commit: CommitHarvestConversion,
) -> GameState:
    """Fire one once-per-harvest conversion on PendingHarvestFeed.

    Adds `conversion_id` to `player.harvest_conversions_used` (so the
    enumerator no longer offers it this harvest), pays the input cost, adds the
    full food_out to the player's supply, and invokes the optional
    side_effect_fn. The produced food flows into `p.resources.food` and is paid
    out (or kept as surplus) at the final `_execute_convert` call — there is no
    food_owed bookkeeping on the pending. Declining a craft is implicit (commit
    CommitConvert without firing it), so this handler only ever fires.

    auto_pop=False — the pending stays on top to host further craft
    decisions plus the final CommitConvert.
    """
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS

    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestFeed)
    p = state.players[player_idx]
    spec = HARVEST_CONVERSIONS[commit.conversion_id]

    new_used = p.harvest_conversions_used | {commit.conversion_id}

    # Pay input cost, add full food_out to supply.
    new_resources = p.resources - spec.input_cost + Resources(food=spec.food_out)

    new_player = fast_replace(
        p,
        resources=new_resources,
        harvest_conversions_used=new_used,
    )
    state = _update_player(state, player_idx, new_player)

    # Optional non-food effect (e.g. future Stone Sculptor's +1 point).
    if spec.side_effect_fn is not None:
        state = spec.side_effect_fn(state, player_idx)

    return state


def _execute_convert(
    state: GameState, player_idx: int, commit: CommitConvert,
) -> GameState:
    """Apply the player's chosen goods-to-food conversion on PendingHarvestFeed
    AND pay the feeding cost from the resulting supply.

    `commit.{grain, veg, sheep, boar, cattle}` are CONSUMED amounts —
    subtracted from the player's supply. `food_produced` is computed via
    cooking_rates and added to the player's supply alongside any food the
    player was already holding. The full feeding cost is then paid from the
    combined pool in a single step:

        need            = 2*people_total - newborns
        total_available = p.resources.food + food_produced
        food_paid       = min(need, total_available)
        food_remaining  = total_available - food_paid   # surplus stays in supply
        begging_added   = need - food_paid

    The "Cannot withhold food tokens" rule (RULES.md Feeding Phase) is
    enforced structurally by `min(need, total_available)`: the player has
    no knob to keep food while taking begging markers.

    Begging markers are assigned here, not at Stop — preserving the
    Stop-only-pops convention.

    After commit, only Stop is legal on this pending (`conversion_done=True`).

    auto_pop=False — the trailing Stop is the explicit exit, matching the
    other multi-stage pendings.
    """
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestFeed)
    p = state.players[player_idx]
    sR, bR, cR, vR = cooking_rates(state, player_idx)

    food_produced = (
        commit.grain
        + commit.veg    * vR
        + commit.sheep  * sR
        + commit.boar   * bR
        + commit.cattle * cR
    )

    need            = 2 * p.people_total - p.newborns
    total_available = p.resources.food + food_produced
    food_paid       = min(need, total_available)
    food_remaining  = total_available - food_paid
    begging_added   = need - food_paid

    new_resources = Resources(
        wood  = p.resources.wood,
        clay  = p.resources.clay,
        reed  = p.resources.reed,
        stone = p.resources.stone,
        food  = food_remaining,
        grain = p.resources.grain - commit.grain,
        veg   = p.resources.veg   - commit.veg,
    )
    new_animals = Animals(
        sheep  = p.animals.sheep  - commit.sheep,
        boar   = p.animals.boar   - commit.boar,
        cattle = p.animals.cattle - commit.cattle,
    )
    new_player = fast_replace(
        p,
        resources=new_resources,
        animals=new_animals,
        begging_markers=p.begging_markers + begging_added,
    )
    state = _update_player(state, player_idx, new_player)
    return replace_top(state, fast_replace(top, conversion_done=True))


def _execute_breed(
    state: GameState, player_idx: int, commit: CommitBreed,
) -> GameState:
    """Apply the chosen post-breed configuration on PendingHarvestBreed.

    `commit.(sheep, boar, cattle)` is a Pareto-optimal point from
    `breeding_frontier(p, rates[:3])` (the legality enumerator guarantees this;
    per the engine's "step does not verify legality" rule we do not re-check it).
    Sets the player's animals to the chosen counts and adds the breeding food to
    supply, computed via `breeding_food_gained` — the same formula
    `breeding_frontier` tabulates, so the value matches the frontier entry by
    construction without recomputing the whole frontier. Mirrors the direct-formula
    style of the sibling `_execute_accommodate` / `_execute_convert` handlers.

    auto_pop=False; trailing Stop is the explicit exit.
    """
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestBreed)
    p = state.players[player_idx]

    rates_3 = cooking_rates(state, player_idx)[:3]
    chosen  = Animals(sheep=commit.sheep, boar=commit.boar, cattle=commit.cattle)
    food_gained = breeding_food_gained(p.animals, chosen, rates_3)

    new_player = fast_replace(
        p,
        animals=chosen,
        resources=p.resources + Resources(food=food_gained),
    )
    state = _update_player(state, player_idx, new_player)
    return replace_top(state, fast_replace(top, breed_chosen=True))
