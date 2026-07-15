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
    CommitChooseCost,
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
from agricola.helpers import breeding_food_gained, cooking_rates, feeding_requirement
from agricola.pasture import compute_pastures_from_arrays
from agricola.pending import (
    BreedingOutcome,
    HarvestEntry,
    HarvestOccasion,
    PendingBakeBread,
    PendingBuildFences,
    PendingBuildRooms,
    PendingChooseCost,
    PendingBuildStables,
    PendingFieldPhase,
    PendingGrantedSubAction,
    PendingBuildMajor,
    PendingClayOven,
    PendingFarmRedevelopment,
    PendingFoodPayment,
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
from agricola.resources import Animals, Cost, Resources
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
    """Family-game Meeting Place (atomic): collect accumulated food, reset the slot,
    and become starting player.

    The CARD-game Meeting Place is NON-atomic and self-hosting: it is dispatched
    directly to `_initiate_meeting_place_cards` in `engine._apply_place_worker`,
    ahead of the generic atomic-host wrapper, so this atomic resolver runs only in
    the Family game. (Routing card-mode Meeting Place through the wrapper would
    double-host the pushing card handler and soft-lock the turn.)"""
    ap = state.current_player
    state = _resolve_food_accumulation(state, "meeting_place")
    return _become_starting_player(state, ap)


def _initiate_meeting_place_cards(state: GameState) -> GameState:
    """Card-game Meeting Place: become starting player (immediate, no food), then
    OPTIONALLY play one minor. Always push the single-optional Proceed-host frame
    (PendingMeetingPlace; SPACE_HOST_REFACTOR.md §7) — uniform with how the Major
    Improvement space is always-wrapped. The before-phase offers ChooseSubAction
    ("play_minor") only when a minor is playable, otherwise just before-triggers +
    Proceed (the decline). Always wrapping ensures cards hooking the space via
    before_/after_action_space fire even when no minor is playable. The worker is
    already placed (cross-cutting). Fires before_action_space autos at the push.
    See CARD_IMPLEMENTATION_PLAN.md I.3."""
    ap = state.current_player
    state = _become_starting_player(state, ap)
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

    # Growth-room-override CONSUME (user-approved extension, 2026-07-14): Basic
    # Wish is the room-gated wish space (Urgent Wish has no room gate, so an
    # override is never load-bearing there). If this growth is committing while
    # the normal spare-room gate FAILS right now (rooms <= people, pre-newborn),
    # a registered override made it possible — latch the first permitting card's
    # id into the owner's `fired_once`, spending its "once this game" use. A
    # growth taken with a spare room consumes nothing. Empty registry (the
    # entire Family game) → this block is a no-op and the path byte-identical.
    if space_id == "basic_wish_for_children":
        from agricola.legality import GROWTH_ROOM_OVERRIDE_EXTENSIONS, _num_rooms
        if GROWTH_ROOM_OVERRIDE_EXTENSIONS:
            p = state.players[ap]
            if p.people_total >= _num_rooms(p):   # the normal room gate fails
                for card_id, fn in GROWTH_ROOM_OVERRIDE_EXTENSIONS:
                    if fn(state, ap):
                        p = state.players[ap]
                        state = _update_player(state, ap, fast_replace(
                            p, fired_once=p.fired_once | {card_id}))
                        break

    # Update player: people_total and newborns
    return _grow_family(state, ap)


def _grow_family(state: GameState, idx: int) -> GameState:
    """The people-increment of a family growth, factored out of the wish resolver:
    people_total += 1, newborns += 1, no board placement, no room gate (the
    caller's concern). The whole effect of a card-granted growth
    (PendingFamilyGrowth.place_on_space=False), and the second half of a wish-space
    growth."""
    p = state.players[idx]
    new_player = fast_replace(
        p,
        people_total=p.people_total + 1,
        newborns=p.newborns + 1,
    )
    return _update_player(state, idx, new_player)


def _resolve_basic_wish_for_children(state: GameState) -> GameState:
    from agricola.constants import GameMode
    if state.mode is GameMode.CARDS:
        # Non-atomic Proceed-host (and-then; SPACE_HOST_REFACTOR.md §4.3): push the
        # parent frame and fire before_action_space autos, exactly like Meeting Place
        # (`_initiate_meeting_place_cards`). Growth and minor run as sub-actions of
        # that frame, not here. Urgent Wish stays atomic.
        from agricola.pending import PendingBasicWishForChildren
        from agricola.cards.triggers import apply_auto_effects
        ap = state.current_player
        state = push(state, PendingBasicWishForChildren(
            player_idx=ap,
            initiated_by_id="space:basic_wish_for_children",
        ))
        return apply_auto_effects(state, "before_action_space", ap)
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
    """Initiate Grain Utilization by pushing PendingGrainUtilization.
    Fires before_action_space autos at the push (a Family no-op)."""
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    state = push(state, PendingGrainUtilization(
        player_idx=ap,
        initiated_by_id="space:grain_utilization",
    ))
    return apply_auto_effects(state, "before_action_space", ap)


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
    """Initiate Cultivation by pushing PendingCultivation.
    Fires before_action_space autos at the push (a Family no-op)."""
    from agricola.pending import PendingCultivation
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    state = push(state, PendingCultivation(
        player_idx=ap,
        initiated_by_id="space:cultivation",
    ))
    return apply_auto_effects(state, "before_action_space", ap)


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
    """Initiate House Redevelopment by pushing PendingHouseRedevelopment.
    Fires before_action_space autos at the push (a Family no-op)."""
    from agricola.pending import PendingHouseRedevelopment
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    state = push(state, PendingHouseRedevelopment(
        player_idx=ap,
        initiated_by_id="space:house_redevelopment",
    ))
    return apply_auto_effects(state, "before_action_space", ap)


def _initiate_farm_expansion(state: GameState) -> GameState:
    """Initiate Farm Expansion by pushing PendingFarmExpansion.
    Fires before_action_space autos at the push (a Family no-op)."""
    from agricola.pending import PendingFarmExpansion
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    state = push(state, PendingFarmExpansion(
        player_idx=ap,
        initiated_by_id="space:farm_expansion",
    ))
    return apply_auto_effects(state, "before_action_space", ap)


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
    """Initiate Farm Redevelopment by pushing PendingFarmRedevelopment.
    Fires before_action_space autos at the push (a Family no-op)."""
    from agricola.cards.triggers import apply_auto_effects
    ap = state.current_player
    state = push(state, PendingFarmRedevelopment(
        player_idx=ap,
        initiated_by_id="space:farm_redevelopment",
    ))
    return apply_auto_effects(state, "before_action_space", ap)


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
    """Play one occupation from hand: debit the frame's (route-supplied) cost, move the card
    hand->tableau, mark the host's work applied (`_mark_effect_initiated`), THEN run its
    (variant-aware) on_play and fire one-shots; the trailing Stop pops. The DEFERRED flip
    (user ruling 2026-07-14) — the same order as `_execute_play_minor` — happens in
    _advance_until_decision once the host is back on top, so the after_play_occupation autos
    fire only after on_play (and anything it pushed) has fully resolved. The mark must be set
    while the host is still on top. A play-variant occupation (Roof
    Ballaster) folds its chosen variant's SURCHARGE into the cost — re-derived from the same
    variants_fn the enumerator used; the variant's BENEFIT (e.g. stone) is granted in its
    on_play, not debited there.

    Food-shortfall guard (FOOD_PAYMENT_DESIGN.md §5): if the cost's food exceeds food on hand,
    push a PendingFoodPayment to RAISE the shortfall into supply (no debit) and re-run this exact
    play. The guard is re-entrant — on the re-run the food is sufficient, so it debits and plays
    normally. Occupation costs are food-only today, so there is nothing to reserve."""
    from agricola.cards.specs import OCCUPATIONS, PLAY_OCCUPATION_VARIANTS
    cid = action.card_id
    top = state.pending_stack[-1]   # PendingPlayOccupation — the play cost lives here
    p = state.players[idx]
    cost = top.cost                 # Resources (food-only for Lessons / Scholar)
    variants_fn = PLAY_OCCUPATION_VARIANTS.get(cid)
    if variants_fn is not None and action.variant is not None:
        cost = cost + dict(variants_fn(state, idx))[action.variant]
    if p.resources.food < cost.food:                 # raise the shortfall, then re-run
        return push(state, PendingFoodPayment(
            player_idx=idx, food_needed=cost.food, resume_kind="rerun",
            reserved=Cost(resources=fast_replace(cost, food=0)), action=action))
    p = fast_replace(
        p, resources=p.resources - cost,
        hand_occupations=p.hand_occupations - {cid},
        occupations=p.occupations | {cid},
    )
    state = _update_player(state, idx, p)
    # Stamp WHICH card landed on the host before the flip, so after_play_occupation
    # autos/triggers can read it (Clutterer's text-filtered count).
    state = replace_top(state, fast_replace(state.pending_stack[-1],
                                            played_card_id=cid))
    # DEFER the after-flip (user ruling 2026-07-14): mark the work applied while the host
    # is still on top; _advance_until_decision flips it (firing after_play_occupation
    # autos) once everything on_play pushes has resolved — so a reaction's payout can
    # never fund this card's own effect. Occupation-counting autos (Education Bonus)
    # still see the new card: the tableau add above precedes the deferred flip too.
    state = _mark_effect_initiated(state)
    prev_depth = len(state.pending_stack)
    # Variant-aware on-play: a card that registered a play-variant (Roof Ballaster) has its
    # on_play called with the chosen variant; every other occupation keeps (state, idx).
    if cid in PLAY_OCCUPATION_VARIANTS:
        state = OCCUPATIONS[cid].on_play(state, idx, action.variant)
    else:
        state = OCCUPATIONS[cid].on_play(state, idx)
    # One-shot conditional latch (II.3 / §6): playing a card can satisfy a standing
    # house-material condition the instant it enters the tableau. No-op in the Family game.
    from agricola.engine import _fire_ready_one_shots
    state = _fire_ready_one_shots(state, idx)
    # If on_play pushed a sub-action leaf, fire its before-autos at the push — the same seam
    # as _execute_play_minor / the granted-sub-action trigger path (depth-guarded: a
    # goods-only on_play leaves the flipped host on top; nothing must re-fire).
    from agricola.engine import _fire_subaction_before_auto
    return _fire_subaction_before_auto(state, prev_depth)


def _execute_play_minor(state: GameState, idx: int, action) -> GameState:
    """Play one minor from hand: debit its (cost-modifier-resolved) cost, move it
    hand->tableau (or, for a traveling minor, PASS it to the opponent — never kept), then run
    its on_play. The chosen resource payment rides on `action.payment` (the frontier point
    picked at enumeration — §3.4); the animal cost (if any) rides on the spec.

    Food-shortfall guard (FOOD_PAYMENT_DESIGN.md §5): if the payment's food exceeds food on
    hand, RESERVE the cost's convertible goods (its non-food resources + animals) and push a
    PendingFoodPayment to raise the shortfall into supply (no debit), then re-run this play.
    Reserving keeps the frame from cooking a good the cost still needs (no double-spend); on the
    re-run the food is sufficient, so it debits the full cost and plays normally."""
    from agricola.cards.specs import MINORS
    cid = action.card_id
    spec = MINORS[cid]
    p = state.players[idx]
    pay = action.payment
    assert isinstance(pay, Resources), "minor cost routes are resource-only"
    # The ANIMAL portion is not card-modifiable and does not ride on `payment` (a
    # Resources vector); it comes from the chosen "/"-alternative (`action.cost`) when
    # set, else the printed `spec.cost` — the ordinary single-cost case.
    chosen_animals = (action.cost.animals if action.cost is not None
                      else spec.cost.animals)
    if p.resources.food < pay.food:                  # raise the shortfall, then re-run
        reserved = Cost(resources=fast_replace(pay, food=0), animals=chosen_animals)
        return push(state, PendingFoodPayment(
            player_idx=idx, food_needed=pay.food, resume_kind="rerun",
            reserved=reserved, action=action))
    p = fast_replace(
        p, resources=p.resources - pay, animals=p.animals - chosen_animals,
        hand_minors=p.hand_minors - {cid},
    )
    if not spec.passing_left:                       # normal minor: keep in tableau
        p = fast_replace(p, minor_improvements=p.minor_improvements | {cid})
    state = _update_player(state, idx, p)
    if spec.passing_left:                           # traveling minor: pass to the opponent
        opp = 1 - idx
        state = _update_player(state, opp, fast_replace(
            state.players[opp],
            hand_minors=state.players[opp].hand_minors | {cid},
        ))
    # Stamp WHICH card landed on the host before the flip, so after_play_minor
    # autos/triggers can read it (Clutterer's text-filtered count — a traveling
    # minor is stamped too, though it has already been passed on).
    state = replace_top(state, fast_replace(state.pending_stack[-1],
                                            played_card_id=cid))
    # DEFER the after-flip (user ruling 2026-07-14): mark the work applied while the host
    # is still on top; _advance_until_decision flips it once everything on_play pushes
    # (Shifting Cultivation's plow) has resolved — firing the after_play_minor autos AND
    # the coarse "any improvement built" event (Junk Room) there, so neither payout can
    # fund this card's own effect. Family no-ops (empty AUTO_EFFECTS).
    state = _mark_effect_initiated(state)
    prev_depth = len(state.pending_stack)
    # Run the immediate effect (whether kept or passed). A pushing on_play lands its primitive
    # on top of the marked (still-before-phase) host, which flips once it pops.
    # When the commit carries a `variant`, the chosen route
    # is threaded as a 3rd arg — a play-variant minor (PLAY_MINOR_VARIANTS — Facades Carving),
    # whose surcharge was already debited (folded into `payment`), OR a labeled-alternative-cost
    # minor (`cost_labels` — Canvas Sack), whose real alternative cost was already debited via
    # `payment`. Either way on_play grants only the benefit. `variant is None` -> the ordinary
    # 2-arg call (every plain minor; Family never plays minors, so this stays inert there).
    if action.variant is not None:
        state = spec.on_play(state, idx, action.variant)
    else:
        state = spec.on_play(state, idx)
    # One-shot conditional latch (II.3 / §6); a no-op in the Family game.
    from agricola.engine import _fire_ready_one_shots
    state = _fire_ready_one_shots(state, idx)
    # If on_play pushed a sub-action leaf (Shifting Cultivation → PendingPlow), fire its
    # before-autos at the push — the same seam as the granted-sub-action trigger path
    # (depth-guarded: a goods-only on_play leaves the flipped host on top; nothing re-fires,
    # which is what used to require Wood Workshop's per-card phase gate).
    from agricola.engine import _fire_subaction_before_auto
    return _fire_subaction_before_auto(state, prev_depth)


def note_animal_cook(state: GameState, idx: int) -> GameState:
    """An animal was just cooked (converted to food via a cooking improvement) by player
    `idx`. Fire the reaction of each owned card registered for animal-cook events (Cookery
    Lesson's "used a cooking improvement this turn"). Called at the two work-phase cook sites
    after the animal→food conversion. Detecting the ACTUAL cook — not an animal-count change —
    is load-bearing: an animal spent as a card cost, discarded, or exchanged is not a cook and
    must not fire this. Empty registry / no owner -> no-op (Family byte-identical)."""
    from agricola.cards.triggers import ANIMAL_COOK_REACTIONS
    if not ANIMAL_COOK_REACTIONS:
        return state
    owned = state.players[idx].occupations | state.players[idx].minor_improvements
    for cid, react_fn in ANIMAL_COOK_REACTIONS.items():
        if cid in owned:
            state = react_fn(state, idx)
    return state


def _execute_food_payment(state: GameState, idx: int, action) -> GameState:
    """Apply the chosen crops/animals-to-food conversion bundle at PendingFoodPayment, pop the
    frame, and resume the action the food was for (FOOD_PAYMENT_DESIGN.md §5/§6).

    RAISE-ONLY: this only PRODUCES food (each consumed good at its `cooking_rates` rate, banking
    any overshoot); it does NOT debit. The resumed action debits the full cost itself, from the
    now-sufficient supply. `action` holds CONSUMED amounts (the enumerator inverted the frontier
    over goods MINUS the frame's reserved cost goods, so nothing here touches a reserved good).

    `action.conversions` (rulings 34/37, 2026-07-12): each named once-per-harvest converter
    fires as part of the bundle — its building-resource input is debited, its food added, and
    its SHARED budget marked in `harvest_conversions_used` (the same entry the feed-phase
    craft seam checks). Pure converters only (ruling 37), so no side effects run here."""
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS

    top = state.pending_stack[-1]   # PendingFoodPayment
    sR, bR, cR, vR = cooking_rates(state, idx)
    produced = (action.grain + action.veg * vR
                + action.sheep * sR + action.boar * bR + action.cattle * cR)
    conv_cost = Resources()
    conv_food = 0
    for cid in action.conversions:
        inp, food_out = HARVEST_CONVERSIONS[cid].frontier_fire
        conv_cost = conv_cost + Resources(
            wood=inp[0], clay=inp[1], reed=inp[2], stone=inp[3])
        conv_food += food_out
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=(p.resources - Resources(grain=action.grain, veg=action.veg)
                   - conv_cost + Resources(food=produced + conv_food)),
        animals=p.animals - Animals(action.sheep, action.boar, action.cattle),
    )
    if action.conversions:
        p = fast_replace(p, harvest_conversions_used=(
            p.harvest_conversions_used | frozenset(action.conversions)))
    state = _update_player(pop(state), idx, p)   # pop PendingFoodPayment; host back on top
    if action.sheep + action.boar + action.cattle > 0:   # an animal was cooked to pay
        state = note_animal_cook(state, idx)
    return _resume(state, idx, top)


def _resume(state: GameState, idx: int, top: PendingFoodPayment) -> GameState:
    """Dispatch the post-food-payment continuation, recorded as DATA on the popped frame (a
    frozen/hashable/JSON-serializable frame can't hold a closure — §6). The food was raised into
    supply but NOT debited; the continuation debits the full cost itself.

    `resume_kind == "rerun"` re-dispatches the stored commit through the normal handler table —
    the unified path for play-minor / play-occupation / build-major and future food-bearing
    builds. The executor's own food-shortfall guard now passes (food is sufficient), so it debits
    the full cost and runs to completion; its host is back on top after the pop, so its after-phase
    pivot / any pushing on_play land exactly as on the direct path. A re-run is NOT wrapped in
    `_fire_subaction_before_auto` — the re-dispatched executor owns its own firing, and wrapping
    would re-fire its host's before-autos in the after-phase.

    Any other `resume_kind` is a card id with a registered GRANT continuation (Ox Goad: debit the
    food + push a plow). A grant leaves a fresh sub-action leaf on top, so its before-autos ARE
    fired here, mirroring `_apply_fire_trigger`'s post-apply seam for the food-on-hand path."""
    if top.resume_kind == "rerun":
        from agricola.engine import COMMIT_SUBACTION_HANDLERS
        _ptype, effect_fn = COMMIT_SUBACTION_HANDLERS[type(top.action)]
        return effect_fn(state, idx, top.action)
    from agricola.cards.specs import FOOD_PAYMENT_RESUMES
    from agricola.engine import _fire_subaction_before_auto
    resume_fn = FOOD_PAYMENT_RESUMES.get(top.resume_kind)
    assert resume_fn is not None, (
        f"unknown PendingFoodPayment resume_kind: {top.resume_kind!r}"
    )
    prev_depth = len(state.pending_stack)
    return _fire_subaction_before_auto(resume_fn(state, idx), prev_depth)


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
        from agricola.cards.cost_mods import free_fence_budget_for
        return push(state, PendingBuildFences(
            player_idx=p_idx, initiated_by_id=space_id,
            free_fence_budget=free_fence_budget_for(
                state, p_idx, build_fences_action=True, space_id="fencing"),
        ))
    if space_id == "major_improvement" and action.name == "improvement":
        # Preserve the composite host's provenance "space:major_improvement"
        # (the old direct-push value), distinct from the House-Redev path's
        # "house_redevelopment". The composite is itself a host: fire
        # before_major_minor_improvement autos at its push (SPACE_HOST_REFACTOR.md
        # §6) — a Family no-op (empty registry).
        from agricola.pending import PendingMajorMinorImprovement
        from agricola.cards.triggers import apply_auto_effects
        state = push(state, PendingMajorMinorImprovement(
            player_idx=p_idx, initiated_by_id=top.initiated_by_id,
        ))
        return apply_auto_effects(state, "before_major_minor_improvement", p_idx)
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
        # The renovation cost is resolved through `effective_payments` at enumeration
        # time (and debited from `CommitRenovate.payment`), not stored on the frame —
        # so cost-modifier cards apply without a per-frame cost cache
        # (COST_MODIFIER_DESIGN.md §3.3).
        state = replace_top(state, fast_replace(top, renovate_chosen=True))
        return push(state, PendingRenovate(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    if action.name == "improvement":
        # The composite is itself a host: fire before_major_minor_improvement autos
        # at its push (SPACE_HOST_REFACTOR.md §6) — a Family no-op (empty registry).
        from agricola.cards.triggers import apply_auto_effects
        state = replace_top(state, fast_replace(top, improvement_chosen=True))
        state = push(state, PendingMajorMinorImprovement(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
        return apply_auto_effects(state, "before_major_minor_improvement", p_idx)
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
        # Cost resolved via `effective_payments` / `CommitRenovate.payment`, not stored
        # on the frame (COST_MODIFIER_DESIGN.md §3.3); mirrors House Redevelopment.
        state = replace_top(state, fast_replace(top, renovate_chosen=True))
        return push(state, PendingRenovate(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
        ))
    if action.name == "build_fences":
        from agricola.cards.cost_mods import free_fence_budget_for
        state = replace_top(state, fast_replace(top, build_fences_chosen=True))
        return push(state, PendingBuildFences(
            player_idx=p_idx, initiated_by_id=top.PENDING_ID,
            free_fence_budget=free_fence_budget_for(
                state, p_idx, build_fences_action=True, space_id="farm_redevelopment"),
        ))
    raise ValueError(f"Unknown sub-action {action.name!r} for Farm Redevelopment")


def _choose_subaction_granted_subaction(
    state: GameState, action: ChooseSubAction,
) -> GameState:
    """Card-game choose handler for an OPTIONAL granted sub-action set (Field Fences /
    Trellis → build_fences; Dwelling Plan → renovate; Beneficiary → play_occupation and/or
    play_minor). Adds the chosen category to the wrapper's `chosen` and pushes the real
    primitive frame carrying the grant's own provenance (so a fence grant's positional
    discount + seeded free-fence budget apply; an occupation play carries the frame's
    `occ_cost`, exactly as Lessons supplies its route cost at push). Declining is the
    wrapper's Stop, not handled here. Dispatches on the chosen category (`action.name`)."""
    top = state.pending_stack[-1]
    p_idx = top.player_idx
    if action.name not in top.subactions or action.name in top.chosen:
        raise ValueError(
            f"sub-action {action.name!r} not an untaken granted category "
            f"(granted {top.subactions!r}, taken {sorted(top.chosen)!r})")
    state = replace_top(state, fast_replace(top, chosen=top.chosen | {action.name}))
    if action.name == "renovate":
        return push(state, PendingRenovate(
            player_idx=p_idx, initiated_by_id=top.initiated_by_id))
    if action.name == "build_fences":
        from agricola.cards.cost_mods import free_fence_budget_for
        return push(state, PendingBuildFences(
            player_idx=p_idx, initiated_by_id=top.initiated_by_id,
            free_fence_budget=free_fence_budget_for(
                state, p_idx, build_fences_action=True, space_id=top.initiated_by_id),
        ))
    if action.name == "play_occupation":
        from agricola.pending import PendingPlayOccupation
        return push(state, PendingPlayOccupation(
            player_idx=p_idx, initiated_by_id=top.initiated_by_id, cost=top.occ_cost))
    if action.name == "play_minor":
        from agricola.pending import PendingPlayMinor
        return push(state, PendingPlayMinor(
            player_idx=p_idx, initiated_by_id=top.initiated_by_id))
    raise ValueError(f"Unknown granted sub-action {action.name!r}")


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
    """Run the family-growth primitive, then pivot PendingFamilyGrowth to its
    after-phase (Stop pops).

    Space path (place_on_space=True, the default): add one newborn on the space
    named by the frame's initiated_by_id (the wish space), via the shared wish
    resolver. Card-grant path (place_on_space=False; user ruling, Group A1): the
    newborn occupies NO action space — increment the frame owner's
    people_total/newborns only (`initiated_by_id` is a "card:<id>" provenance
    string, not a space)."""
    top = state.pending_stack[-1]
    if top.place_on_space:
        state = _resolve_wish_for_children(state, top.initiated_by_id)
    else:
        state = _grow_family(state, idx)
    return _mark_effect_initiated(state)   # deferred flip → after; Stop pops


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
CHOOSE_SUBACTION_HANDLERS[PendingGrantedSubAction] = _choose_subaction_granted_subaction
CHOOSE_SUBACTION_HANDLERS[PendingBasicWishForChildren] = _choose_subaction_basic_wish_for_children
CHOOSE_SUBACTION_HANDLERS[PendingMeetingPlace] = _choose_subaction_meeting_place


# ---------------------------------------------------------------------------
# Sub-action effect functions (used by engine.py)
# ---------------------------------------------------------------------------

def _enter_after_phase(state: GameState) -> GameState:
    """Open a host frame's after-window: flip the top frame to `phase="after"`
    (no pop) and fire its after-automatic effects, then return.

    The single, uniform "after-window opens" point (SUBACTION_HOOK_REFACTOR.md).
    Called by the Proceed boundaries (and/or-space parents, atomic hosts, the
    multi-shot builders' settle) and — for the commit-terminated hosts — by
    `_advance_until_decision` once the host's `effect_initiated` signal is set
    and the host is back on top (the deferred flip: user ruling 2026-07-14,
    "after you [do X]" fires after X's FULL effect, pushed frames included; the
    commit executors call `_mark_effect_initiated` instead of flipping inline).
    The fired event is derived from the now-"after" frame via
    `legality.trigger_event` — `after_action_space` for an action-space host,
    `after_<PENDING_ID>` for a sub-action host (e.g. `after_renovate`). For the
    two improvement hosts the coarse "any improvement built" event
    (`after_build_improvement` — Junk Room) fires here too, right after the
    derived event, so it defers with the flip. A no-op in the Family game
    (empty AUTO_EFFECTS); the after-phase enumerator then surfaces any
    after-triggers + Stop, and Stop pops.
    """
    from agricola.cards.triggers import apply_auto_effects
    from agricola.legality import trigger_event
    top = state.pending_stack[-1]
    if getattr(top, "effect_initiated", False):
        new_top = fast_replace(top, phase="after", effect_initiated=False)
    else:
        new_top = fast_replace(top, phase="after")
    state = replace_top(state, new_top)
    state = apply_auto_effects(state, trigger_event(new_top), new_top.player_idx)
    from agricola.pending import PendingBuildMajor, PendingPlayMinor
    if isinstance(new_top, (PendingBuildMajor, PendingPlayMinor)):
        state = apply_auto_effects(state, "after_build_improvement", new_top.player_idx)
    return state


def _mark_effect_initiated(state: GameState) -> GameState:
    """Signal that the top commit-terminated host's work has been applied: set
    `effect_initiated` so `_advance_until_decision` flips the host to its
    after-phase (firing the after-autos via `_enter_after_phase`) once the host
    is next on top — i.e. after every frame the effect pushed (an on_play's
    primitive, an oven's free-bake wrapper) has resolved.

    Replaces the old inline `_enter_after_phase` call at each commit executor's
    tail (user ruling 2026-07-14): firing after-autos before the effect's pushed
    frames resolve let a reaction's payout (Bonehead's wood) fund the effect it
    was reacting to (Established Person's fences). Must be called while the host
    is still on top, BEFORE the executor pushes anything. For an executor whose
    effect pushes nothing, the flip happens within the same `step` — observably
    identical to the old inline flip.
    """
    return replace_top(
        state, fast_replace(state.pending_stack[-1], effect_initiated=True))


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

    Sow boosts (Tinsmith Master; user ruling 2026-07-15 — the per-field
    "+1 crop, you can" is declinable, carried as counts on the commit): the
    first `boost_grain` grain-fields planted this commit hold 4 grain instead
    of 3, the first `boost_veg` veg-fields 3 veg instead of 2 — "one extra
    crop on top of the usual stack" (the card's clarification), taken from
    the general supply like the stack's other non-seed crops, so the supply
    debit is unchanged. Fields are interchangeable at sow time, so boosting
    the first N in canonical order loses nothing. A boosted card-stack sow
    (`boost_card_sows`, a sub-multiset of `card_sows`'s grain/veg entries)
    likewise plants sow_amount + 1 on its stack. Family commits carry zero
    boosts, so both paths are byte-identical there.

    Preconditions: legality has verified grain + veg <= empty_fields,
    grain <= p.resources.grain and veg <= p.resources.veg, boost_grain <=
    grain, boost_veg <= veg, boost_card_sows a sub-multiset of card_sows'
    crop entries, and boosts nonzero only for an owner of a SOW_BOOST_CARDS
    member.
    """
    grain = commit.grain
    veg = commit.veg
    boost_g, boost_v = commit.boost_grain, commit.boost_veg
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
                    new_row.append(fast_replace(cell, grain=4 if boost_g else 3))
                    boost_g = max(0, boost_g - 1)
                    g_remaining -= 1
                elif v_remaining > 0:
                    new_row.append(fast_replace(cell, veg=3 if boost_v else 2))
                    boost_v = max(0, boost_v - 1)
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
    assert boost_g == 0 and boost_v == 0, (
        f"Sow boosts exceeded sown field counts; legality should have caught this. "
        f"boost_grain remaining={boost_g}, boost_veg remaining={boost_v}"
    )

    new_farmyard = fast_replace(p.farmyard, grid=tuple(new_grid_rows))

    # Card-field sows (user rulings 45-48, 2026-07-12): each (card_id, good)
    # pair spends 1 `good` from supply and plants the card's declared stack
    # (3 for grain-like goods, 2 for veg-like) on one empty stack. Family
    # commits never carry card_sows, so this block is card-only.
    new_store = p.card_state
    if commit.card_sows:
        from agricola.cards.card_fields import (
            EMPTY_STACK,
            card_field_stacks,
            sow_amount,
            stack_with,
            stacks_to_store,
        )
        # Boosted card-stack sows (Tinsmith Master): each boost_card_sows entry
        # marks one matching (card_id, good) sow as planting +1 on its stack.
        boost_cs: dict[tuple, int] = {}
        for pair in commit.boost_card_sows:
            boost_cs[pair] = boost_cs.get(pair, 0) + 1
        probe = fast_replace(p, card_state=new_store)
        for cid, good in commit.card_sows:
            amount = sow_amount(cid, good)
            if boost_cs.get((cid, good), 0):
                amount += 1
                boost_cs[(cid, good)] -= 1
            stacks = list(card_field_stacks(probe, cid))
            slot = stacks.index(EMPTY_STACK)   # legality guaranteed an empty stack
            stacks[slot] = stack_with(EMPTY_STACK, good, amount)
            new_store = stacks_to_store(new_store, cid, stacks)
            probe = fast_replace(p, card_state=new_store)
            new_resources = new_resources - Resources(**{good: 1})
        assert not any(boost_cs.values()), (
            "boost_card_sows exceeded card_sows' matching entries; "
            "legality should have caught this")
        assert min(
            new_resources.wood, new_resources.stone,
            new_resources.grain, new_resources.veg) >= 0, (
            "card sow overspent supply; legality should have caught this")

    new_player = fast_replace(
        p, resources=new_resources, farmyard=new_farmyard,
        card_state=new_store,
    )
    state = _update_player(state, player_idx, new_player)
    return _mark_effect_initiated(state)   # deferred flip → after; Stop pops


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
    return _mark_effect_initiated(state)   # deferred flip → after; Stop pops


def _execute_plow(
    state: GameState, player_idx: int, commit: CommitPlow,
) -> GameState:
    """Plow the cell at (commit.row, commit.col).

    Precondition (enforced by `_enumerate_pending_plow`): (row, col) is a
    legal plow cell (EMPTY, non-enclosed, adjacent to existing field or
    the first field on the farm).

    Base plow (every Family plow + single-grant plow cards' one plow): flip the frame to
    its after-phase on this one commit, then Stop pops. A BASE plow (a Farmland /
    Cultivation host plow, `initiated_by_id` not "card:…") leaves `num_plowed` at its
    default 0 so its frame is byte-identical to the pre-multi-shot engine (the C++ Family
    gate). A CARD-grant plow always counts `num_plowed` (only meaningful in CARDS mode,
    where the field is anyway emitted) so a multi-tile grant's CardStore debit reads the
    fields actually plowed — even a one-tile grant (`max_plows==1`).

    Multi-shot grant (`max_plows>1`; Swing/Turnwrest/Wheel Plow): stay in the before-phase
    so another CommitPlow / early Proceed is offered, until the budget is spent or no
    further (non-stranding) cell remains, at which point flip to the after-phase.
    """
    p = state.players[player_idx]
    new_grid = _new_grid_with_cell(
        p.farmyard.grid, commit.row, commit.col, Cell(cell_type=CellType.FIELD),
    )
    new_farmyard = fast_replace(p.farmyard, grid=new_grid)
    new_player = fast_replace(p, farmyard=new_farmyard)
    state = _update_player(state, player_idx, new_player)

    top = state.pending_stack[-1]
    is_card_grant = top.initiated_by_id.startswith("card:")
    if not is_card_grant:
        # Base Farmland/Cultivation plow: single-shot, num_plowed untouched (default 0) →
        # byte-identical Family frame.
        return _mark_effect_initiated(state)   # deferred flip → after; Stop pops
    # Card grant: count this plow (for the per-grant CardStore tile debit at after_plow).
    num_plowed = top.num_plowed + 1
    state = replace_top(state, fast_replace(top, num_plowed=num_plowed))
    # Multi-shot: stay in before-phase while budget AND a legal next cell remain (recomputed
    # against the board this plow just produced — adjacency can open/close targets).
    if num_plowed < top.max_plows and _more_plows_available(state, state.pending_stack[-1]):
        return state
    return _mark_effect_initiated(state)   # budget spent / no next cell → deferred flip


def _more_plows_available(state: GameState, top) -> bool:
    """True iff another granted plow could legally follow, under the same cell rule the
    enumerator uses (non-stranding on Farmland via `must_preserve_base`, else any legal
    plow cell). Used only by multi-shot grants; a single-shot plow flips to after on its
    first commit and never reaches here."""
    from agricola.legality import _legal_plow_cells, safe_plow_cells
    p = state.players[top.player_idx]
    cells = safe_plow_cells(p) if top.must_preserve_base else _legal_plow_cells(p)
    return bool(cells)


def _execute_build_stable(
    state: GameState, player_idx: int, commit: CommitBuildStable,
) -> GameState:
    """Multi-shot stable build: place one stable, increment num_built, leave
    PendingBuildStables on top (the dispatcher never pops; Proceed flips it to its
    after-phase and Stop pops).

    The base cost stays on the pending frame (`top.cost`) — it is caller-dependent
    (Side Job 1 wood, Farm Expansion 2 wood, card grants 0), not derivable from player
    state. It is resolved per stable through the cost-modifier chokepoint with that base:
    a singleton frontier (always in Family — debit it inline + record any per-action
    conversion budget) or, when a cost card offers >1 payment, the two-step
    `PendingChooseCost`. CommitBuildStable stays geometry-only. Like build-rooms, the
    rules treat "Build Stables" as ONE action building all stables at once; the engine
    spreads it into per-stable commits, so a per-action budget (Millwright) is shared
    across them (handled by the chokepoint's `record`/reset, not here).

    Recomputes Farmyard.pastures explicitly: a stable placed inside an existing pasture
    changes that pasture's num_stables (and capacity); the documented convention for
    pasture-changing resolvers (ENGINE_IMPLEMENTATION.md §4.1).
    """
    from agricola.legality import _build_stable_ctx, effective_payments
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildStables)
    p = state.players[player_idx]
    # Resolve this stable's payment frontier (base = the frame's caller-supplied cost)
    # BEFORE placing it; build_index = the 0-based stable within this multi-shot action.
    payments = effective_payments(
        state, player_idx, _build_stable_ctx(p, top.cost, top.num_built))
    # Place the stable geometry + advance the multi-shot counter.
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
    p = fast_replace(p, farmyard=new_farmyard)
    state = _update_player(state, player_idx, p)
    state = replace_top(state, fast_replace(top, num_built=top.num_built + 1))
    if len(payments) == 1:
        # Singleton frontier (always in Family == top.cost): debit inline + record any
        # per-action conversion-budget usage (Millwright); stay on the build host.
        assert isinstance(payments[0], Resources), "build-stable has no non-resource routes"
        from agricola.cards.cost_mods import record_conversion_usage
        p = state.players[player_idx]
        state = _update_player(
            state, player_idx, fast_replace(p, resources=p.resources - payments[0]))
        return record_conversion_usage("build_stable", state, player_idx, payments[0])
    # >1 payment (a cost-modifier card offers a choice): defer the debit to the two-step.
    return push(state, PendingChooseCost(
        player_idx=player_idx, initiated_by_id=top.PENDING_ID,
        payments=tuple(payments), action_kind="build_stable"))


def _execute_build_room(
    state: GameState, player_idx: int, commit: CommitBuildRoom,
) -> GameState:
    """Multi-shot room build: place one room, increment num_built, leave
    PendingBuildRooms on top (the dispatcher never pops; Proceed flips it to its
    after-phase and Stop pops).

    Pasture cache is unaffected: rooms cannot legally land in enclosed
    cells (RULES.md "House and Rooms"); `_legal_room_cells` enforces this.

    people_total is unchanged here — a newly built room is empty until
    populated by a Wish for Children action.
    """
    from agricola.legality import _build_room_ctx, effective_payments
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms)
    p = state.players[player_idx]
    # Resolve this room's payment frontier through the cost-modifier chokepoint BEFORE
    # placing it (build_index = the 0-based room within this multi-shot session).
    # Singleton in the Family game (= ROOM_COSTS), possibly several with a cost card.
    payments = effective_payments(state, player_idx, _build_room_ctx(p, top.num_built))
    # Place the room geometry + advance the multi-shot counter (the geometry is
    # committed regardless of how the payment is then resolved).
    new_grid = _new_grid_with_cell(
        p.farmyard.grid, commit.row, commit.col, Cell(cell_type=CellType.ROOM),
    )
    p = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=new_grid))
    state = _update_player(state, player_idx, p)
    state = replace_top(state, fast_replace(top, num_built=top.num_built + 1))
    if len(payments) == 1:
        # Singleton frontier (always in Family): debit inline, stay on the build host.
        assert isinstance(payments[0], Resources), "build-room has no non-resource routes"
        p = state.players[player_idx]
        state = _update_player(
            state, player_idx, fast_replace(p, resources=p.resources - payments[0]))
        # Record any per-action conversion-budget usage (Millwright) — a Family no-op.
        from agricola.cards.cost_mods import record_conversion_usage
        return record_conversion_usage("build_room", state, player_idx, payments[0])
    # >1 payment (a cost-modifier card offers a choice): defer the debit to a
    # PendingChooseCost two-step pushed on top of the build host (card game only).
    return push(state, PendingChooseCost(
        player_idx=player_idx, initiated_by_id=top.PENDING_ID,
        payments=tuple(payments), action_kind="build_room"))


def _execute_choose_cost(
    state: GameState, player_idx: int, commit: CommitChooseCost,
) -> GameState:
    """Debit the chosen payment for a two-step build and pop the PendingChooseCost
    frame, returning to the build host underneath (card game only — §3.7).

    Two underlying-build shapes, by `action_kind`:

    - **build_room / build_stable** (per-build two-step): pop returns to the multi-shot
      build host (`PendingBuildRooms` / `PendingBuildStables`) in its before-phase, which
      then offers the next build / Proceed / Stop. Unchanged.

    - **build_fence** (whole-action settle two-step): the parent is the paused before-phase
      `PendingBuildFences` whose Proceed settle surfaced this menu. After the debit+pop we
      complete that settle — zero the frame's `accrued_cost` (a re-entered flip can't
      re-debit) and run `_enter_after_phase` to fire the after-grants — finishing the
      settle -> pay -> grants order `_apply_proceed` deferred when it saw the menu pushed
      (COST_MODIFIER_DESIGN.md §9.2)."""
    top = state.pending_stack[-1]
    assert isinstance(top, PendingChooseCost)
    assert isinstance(commit.payment, Resources), "build cost routes are resource-only"
    action_kind = top.action_kind
    p = state.players[player_idx]
    state = _update_player(
        state, player_idx, fast_replace(p, resources=p.resources - commit.payment))
    # Record per-action conversion-budget usage (Millwright) against the underlying
    # build's action kind, BEFORE popping back to the build host.
    from agricola.cards.cost_mods import record_conversion_usage
    state = record_conversion_usage(action_kind, state, player_idx, commit.payment)
    state = pop(state)
    if action_kind == "build_fence":
        # Resume the paused fence settle: zero the accrued bill on the build host below,
        # then fire the after-grants (the after-host the menu pushed in front of).
        parent = state.pending_stack[-1]
        assert isinstance(parent, PendingBuildFences) and parent.phase == "before", (
            f"build_fence choose-cost expected a before-phase PendingBuildFences parent, "
            f"got {parent!r}")
        state = replace_top(state, fast_replace(parent, accrued_cost=Resources()))
        return _enter_after_phase(state)
    return state


def _execute_renovate(
    state: GameState, player_idx: int, commit: CommitRenovate,
) -> GameState:
    """Renovate all rooms to the next material tier, paying `commit.payment`.

    The chosen payment rides on the commit (the renovate frontier point picked at
    enumeration time — COST_MODIFIER_DESIGN.md §3.2), not on the frame. Renovate has
    no non-resource routes, so `payment` is always a `Resources` (asserted). Material
    transition (WOOD->CLAY or CLAY->STONE) is derived from `house_material`.
    """
    pending = state.pending_stack[-1]
    assert isinstance(pending, PendingRenovate)
    p = state.players[player_idx]
    # The target tier rides on the commit (the renovate-target model): usually the next
    # tier, but a card (Conservator) can make wood→stone legal. Resolution upgrades to
    # exactly `commit.to_material` rather than deriving the next tier.
    assert p.house_material is not HouseMaterial.STONE, (
        "CommitRenovate illegal on a stone house"
    )
    new_material = commit.to_material
    assert isinstance(commit.payment, Resources), (
        "renovate has no non-resource payment routes"
    )
    new_player = fast_replace(
        p, resources=p.resources - commit.payment, house_material=new_material,
    )
    state = _update_player(state, player_idx, new_player)
    # Record any per-action conversion-budget usage (Millwright on renovate) — a Family
    # no-op. Renovate is a single build, so this just sets the count that after_renovate
    # then resets; the budget never binds within one renovate.
    from agricola.cards.cost_mods import record_conversion_usage
    state = record_conversion_usage("renovate", state, player_idx, commit.payment)
    # One-shot conditional latch (II.3 / §6): a renovate can satisfy a standing
    # house-material condition (Manservant's stone house, Clay Hut Builder's
    # no-longer-wooden). Fire any now-ready one-shots for this player BEFORE the
    # after-phase pivot. A no-op in the Family game (no conditional registered).
    from agricola.engine import _fire_ready_one_shots
    state = _fire_ready_one_shots(state, player_idx)
    return _mark_effect_initiated(state)   # deferred flip → after; Stop pops


def _execute_build_major(
    state: GameState, player_idx: int, commit: CommitBuildMajor,
) -> GameState:
    """Apply CommitBuildMajor end-to-end: pay cost, assign ownership,
    handle Well's future-resources, set build_chosen, and either pop
    PendingBuildMajor (non-oven majors) or push the oven wrapper
    (Clay/Stone Oven, hosting the optional free Bake Bread).

    Dispatched via the generic `_apply_commit_subaction` path — the dispatcher
    never pops after the effect runs. This function owns all its own stack
    manipulation: pop for non-ovens
    (line below), or push the wrapper for ovens (leaving PendingBuildMajor
    in place underneath).

    Food-shortfall guard (FOOD_PAYMENT_DESIGN.md §9): a cost-card payment (Wood Expert's
    "1 food instead of up to 2 wood") may name food the player can't cover. If so, push a
    raise-only PendingFoodPayment to raise it and RE-RUN this exact build with the food now
    in supply (the unified produce-then-pay path). The major's building resources are
    `reserved` so the conversion never spends them; they are also disjoint from the food
    fuel today, so this is robust to a future at-any-time clay->food card. Re-entrant: on the
    re-run the food is sufficient, so it pays and builds normally.
    """
    from agricola.cost import ReturnImprovement
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor)
    p = state.players[player_idx]

    if isinstance(commit.payment, Resources) and p.resources.food < commit.payment.food:
        return push(state, PendingFoodPayment(
            player_idx=player_idx, food_needed=commit.payment.food, resume_kind="rerun",
            reserved=Cost(resources=fast_replace(commit.payment, food=0)), action=commit))

    # 1. Pay the chosen PaymentOption (§3.2/§4.5): a Resources vector (the printed
    #    cost or a cost-card variant) is deducted; a ReturnImprovement route returns
    #    the named Fireplace (Cooking Hearth only) instead of paying clay.
    if isinstance(commit.payment, ReturnImprovement):
        fp = commit.payment.improvement_idx
        assert commit.major_idx in COOKING_HEARTH_INDICES, (
            "Fireplace-return only valid for a Cooking Hearth purchase"
        )
        assert fp in FIREPLACE_INDICES
        owners = state.board.major_improvement_owners
        assert owners[fp] == player_idx, "must own the Fireplace being returned"
        new_owners = tuple(
            None if i == fp else owners[i] for i in range(len(owners))
        )
        state = fast_replace(
            state,
            board=fast_replace(state.board, major_improvement_owners=new_owners),
        )
    else:
        new_player = fast_replace(p, resources=p.resources - commit.payment)
        state = _update_player(state, player_idx, new_player)

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

    # 2b. Building a Cooking Hearth by RETURNING a Fireplace is the "upgrade a
    #     Fireplace to a Cooking Hearth" event — the only route that counts as an
    #     upgrade (a clay-paid Cooking Hearth keeps the Fireplace and is NOT an
    #     upgrade). The discriminator lives only on `commit.payment` (a
    #     ReturnImprovement), so this is the one place that can fire the hook. Its
    #     consumer is Vegetable Slicer (A41). A no-op in the Family game (empty
    #     AUTO_EFFECTS) — the same additive pattern as the after_build_improvement
    #     fire below, so the C++ Family differential gates stay green untouched.
    if isinstance(commit.payment, ReturnImprovement):
        from agricola.cards.triggers import apply_auto_effects
        state = apply_auto_effects(state, "upgrade_to_cooking_hearth", player_idx)

    # 3. Well's special effect: +1 food on each of the next 5 round spaces.
    if commit.major_idx == 4:  # Well
        p = state.players[player_idx]
        new_future = list(p.future_resources)
        # future_resources[r] holds goods promised for round r+1 (0-indexed).
        for r in range(state.round_number, min(state.round_number + 5, 14)):
            new_future[r] = new_future[r] + Resources(food=1)
        new_player = fast_replace(p, future_resources=tuple(new_future))
        state = _update_player(state, player_idx, new_player)

    # 4. DEFER the after-flip (user ruling 2026-07-14): mark the work applied while
    #    this host is still on top. _advance_until_decision flips it — firing the
    #    after_build_major autos AND the coarse "any improvement built" event
    #    (Junk Room) — once any oven wrapper pushed below has fully resolved, so a
    #    reaction's payout can never fund (or be read by) the oven's free bake.
    #    When the wrapper's free bake pops back, the flip happens before the next
    #    enumeration, so the frame then offers after_build_major triggers + Stop
    #    exactly as before. `phase=="after"` still carries what `build_chosen`
    #    used to — the after-gate keys on it.
    state = _mark_effect_initiated(state)

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
    PendingBuildFences counters, leave the pending on top in its before-phase (the
    dispatcher never pops; Proceed flips to the after-phase, then Stop pops — the
    uniform multi-shot before/after host, like PendingBuildStables / _Rooms).

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
    from agricola.constants import GameMode
    from agricola.legality import _build_fence_ctx, effective_payments
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

    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)

    # 3b. Payment. Two paths, branched on game mode (COST_MODIFIER_DESIGN.md §9.3):
    #
    #   FAMILY — per-commit debit (the 2a path, unchanged). Resolve this pasture's
    #   payment frontier through the cost-modifier chokepoint (base = the
    #   geometry-derived wood cost) and debit it inline, exactly as the old
    #   `Resources(wood=wood_cost)` debit did. The frontier is always a singleton
    #   (no cost cards in Family).
    #
    #   CARDS — deferred accrue, NO debit here. Apply this commit's POSITIONAL per-edge
    #   frees (§9.4 source 1, Briar Hedge / Field Fences) then its slice of the per-action
    #   free-fence budget (source 2), accrue the paid wood onto the frame, and settle the
    #   whole-action bill once at the Proceed flip (Part C).
    if state.mode is GameMode.FAMILY:
        payments = effective_payments(
            state, player_idx,
            _build_fence_ctx(p, wood_cost, build_index=top.pastures_built,
                             space_id=top.initiated_by_id),
        )
        assert len(payments) == 1, "build-fence frontier is a singleton in the Family game"
        assert isinstance(payments[0], Resources), "build-fence has no non-resource routes"
        new_resources = p.resources - payments[0]
        new_accrued = top.accrued_cost
        new_budget = top.free_fence_budget
        new_card_state = p.card_state
        supply_drawn = wood_cost                          # Family: every piece from supply
    else:  # CARDS: deferred accrue, no debit (settled at the Proceed flip).
        from agricola.cards.cost_mods import (
            positional_free_edge_count, spend_fence_pools)
        positional_free = positional_free_edge_count(
            state, player_idx, farmyard, h_new, v_new,
            initiated_by_id=top.initiated_by_id,
            build_fences_action=top.build_fences_action)
        after_positional = wood_cost - positional_free      # source 1: positional edges
        free_used = min(after_positional, top.free_fence_budget)  # source 2: per-action budget
        after_budget = after_positional - free_used
        pool_used, new_card_state = spend_fence_pools(p, after_budget)  # source 3: persistent pool
        paid = after_budget - pool_used
        new_budget = top.free_fence_budget - free_used
        new_resources = p.resources                      # no debit; deferred to settle
        new_accrued = top.accrued_cost + Resources(wood=paid)
        supply_drawn = wood_cost - pool_used   # pool pieces come from the card, not supply

    # Fence PIECES drawn from the SUPPLY pile (location 4) = every new edge except those built
    # from a card's reserve (Ash Trees pool, drawn from the card). A positional/budget WOOD
    # free still draws a SUPPLY piece (only the wood is waived), so `supply_drawn` excludes
    # only the pool pieces. In Family every fence comes from supply, so the field stays exactly
    # `15 - fences_built`.
    new_supply = p.fences_in_supply - supply_drawn

    # 4. Apply fence-array updates.
    new_h = apply_fence_edges_h(farmyard.horizontal_fences, h_new)
    new_v = apply_fence_edges_v(farmyard.vertical_fences, v_new)

    # 5. Recompute pasture decomposition.
    new_pastures = compute_pastures_from_arrays(farmyard.grid, new_h, new_v)
    new_farmyard = fast_replace(
        farmyard, horizontal_fences=new_h, vertical_fences=new_v,
        pastures=new_pastures,
    )

    # 6 + 7. Update player (Family debits payment[0]; Cards leaves resources intact). Both
    # decrement the fence supply pile by the supply pieces drawn; CARDS also decrements any
    # spent card pool (new_card_state).
    new_player = fast_replace(
        p, farmyard=new_farmyard, resources=new_resources,
        fences_in_supply=new_supply, card_state=new_card_state,
    )
    state = _update_player(state, player_idx, new_player)

    # 8. Bump pending counters + ordering-rule flag + fold in the deferred-tally
    #    fields. No auto-pop; stays in the before-phase (Proceed flips to after,
    #    then Stop pops).
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    new_top = fast_replace(
        top,
        pastures_built=top.pastures_built + 1,
        fences_built=top.fences_built + wood_cost,
        subdivision_started=top.subdivision_started or is_subdivision,
        accrued_cost=new_accrued,
        free_fence_budget=new_budget,
    )
    return replace_top(state, new_top)


def _execute_accommodate(
    state: GameState, player_idx: int, commit: CommitAccommodate,
) -> GameState:
    """Set the player's (sheep, boar, cattle) to the chosen frontier point and cook any
    excess to food at the player's cooking rates. Serves TWO landing frames:

    - Animal markets (PendingSheepMarket / PendingPigMarket / PendingCattleMarket): the
      newly-gained animals are STAGED on `pending.gained` (not yet on the player), so
      "available" = existing + gained. This is the market's before->after PIVOT — it
      applies the accommodation, flips the host to `phase="after"`, and fires
      after_action_space autos at that work-complete boundary (SPACE_HOST_REFACTOR.md
      §11); the trailing Stop pops.

    - Reconciliation (PendingAccommodate): the animals are ALREADY on the player (a
      decision-free grant put them over capacity via helpers.grant_animals), so
      "available" = the player's current animals (nothing staged). This frame has no
      action-space lifecycle, so it POPS instead of pivoting; the flag was already
      cleared by engine._reconcile_accommodation when it pushed the frame.
    """
    from agricola.pending import (
        PendingSheepMarket, PendingPigMarket, PendingCattleMarket, PendingAccommodate,
    )
    pending = state.pending_stack[-1]
    p = state.players[player_idx]
    # Animal markets / accommodation don't convert veg; slice to (sheep, boar, cattle).
    rates = cooking_rates(state, player_idx)[:3]

    # "Available" per type. Reconciliation reads the player's current animals (the grant
    # already landed there); each market adds only its own staged `gained`.
    if isinstance(pending, PendingAccommodate):
        s_avail, b_avail, c_avail = p.animals.sheep, p.animals.boar, p.animals.cattle
    else:
        assert isinstance(pending, (PendingSheepMarket, PendingPigMarket, PendingCattleMarket))
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
    if (s_avail - commit.sheep) + (b_avail - commit.boar) + (c_avail - commit.cattle) > 0:
        state = note_animal_cook(state, player_idx)   # excess animals cooked to food
    if isinstance(pending, PendingAccommodate):
        return pop(state)          # bare reconciliation: no host lifecycle, just pop
    # Market: mark the work applied (do NOT pop); _advance_until_decision flips the
    # frame to its after-phase within this same step (the accommodate pushes nothing),
    # firing the derived `after_action_space` autos before the after-triggers.
    return _mark_effect_initiated(state)


# ---------------------------------------------------------------------------
# Harvest sub-action effect functions (Task 7)
# ---------------------------------------------------------------------------

def field_take(
    state: GameState, idx: int, *, source: str = "take",
    extra_takes: dict | None = None,
    skip_cells: frozenset = frozenset(),
    bonus: Resources | None = None,
) -> tuple[GameState, HarvestOccasion]:
    """The field-phase take, bare: harvest 1 crop from each of player `idx`'s
    planted fields — one singular event (user ruling 5; all per-field
    consequences arrive at once) — and emit its `HarvestOccasion` manifest.
    Grain takes precedence over veg per RULES.md (a field is sown with one or
    the other, never both — the elif handles a veg-sown field).

    `extra_takes` folds the take-MODIFIER cards into this same event (user
    ruling 11: all field-phase harvesting is simultaneous — Scythe Worker's
    per-grain-field extra, Stable Manure's chosen extras): a per-cell map of
    ADDITIONAL units to harvest beyond the base 1. The manifest entry for a
    cell then carries the combined `amount`, and `emptied` reflects the NET
    result — so every occasion consumer sees one event with everything in it
    (Grain Sieve counts the extras, per the ruling). Callers build the map via
    `harvest_windows.auto_take_fold_ins` / `fold_chosen_modifiers`; an extra
    on a cell the base take doesn't touch (unplanted) or beyond its crops is a
    fold-fn bug and asserts.

    Deliberately bare — no conversion-budget reset, no occasion-auto firing,
    no frame bookkeeping. Those are HARVEST machinery and live with the
    callers that are the harvest: the walk's inline path and
    `_execute_field_take` below. Bumper Crop / Harvest Festival Planning
    trigger the field-phase EFFECT, not the phase (user ruling 4), so they
    will call this directly with their own `source` and NO fold-ins (both
    implemented modifiers are harvest-event-scoped, ruling 12) — phase-keyed
    occasion consumers then stay silent while unscoped ones still see the
    occasion.

    `skip_cells` + `bonus` carry a REPLACE-kind modifier (Grain Thief: "leave
    the grain on the field and take 1 grain from the general supply instead"):
    a skipped planted field is untouched by the take — no base 1, no extras
    (asserted), and NO manifest entry, because the field was not harvested
    (the "instead" replacement; RATIFIED reading (user ruling 2026-07-06) — a replaced field
    is invisible to every harvested-from-a-field consumer: Grain Sieve,
    Lynchet, Food Merchant, and it can donate nothing to Stable Manure /
    Scythe Worker). `bonus` is the replacement's general-supply goods, added
    to the player's gains but NOT to the manifest (not harvested).

    Card-fields (user rulings 45-47, 2026-07-12; `agricola/cards/card_fields`)
    are iterated after the board scan, inside the SAME one event: each
    non-empty stack of each owned card-field yields 1 of its take-precedence
    good (+ any fold-in extras), emitting a `source="card:<id>"` entry per
    stack — entries per-TILE readers ignore (ruling 32) and per-FIELD/unit
    readers count. `extra_takes` and `skip_cells` address a card stack by the
    key ("card", card_id, stack_idx). Family states own no card-fields, so
    the block is inert there and the Family manifest is byte-identical.
    """
    p = state.players[idx]
    extras = extra_takes or {}
    assert not (set(extras) & skip_cells), (
        f"take fold-in targets replaced cells: {set(extras) & skip_cells}")
    entries = []
    grain_gain = 0
    veg_gain = 0
    new_grid_rows = []
    for r in range(3):
        new_row = []
        for c in range(5):
            cell = p.farmyard.grid[r][c]
            if cell.cell_type == CellType.FIELD:
                if (r, c) in skip_cells:
                    assert cell.grain > 0 or cell.veg > 0, (
                        f"replace-kind skip names unplanted field ({r},{c})")
                    new_row.append(cell)   # replaced: untouched, no entry
                    continue
                extra = extras.get((r, c), 0)
                if cell.grain > 0:
                    n = 1 + extra
                    assert n <= cell.grain, (
                        f"take fold-in over-harvests cell ({r},{c}): "
                        f"{n} > {cell.grain} grain")
                    grain_gain += n
                    new_row.append(fast_replace(cell, grain=cell.grain - n))
                    entries.append(HarvestEntry(
                        source=f"cell:{r},{c}", crop="grain", amount=n,
                        emptied=cell.grain == n))
                elif cell.veg > 0:
                    n = 1 + extra
                    assert n <= cell.veg, (
                        f"take fold-in over-harvests cell ({r},{c}): "
                        f"{n} > {cell.veg} veg")
                    veg_gain += n
                    new_row.append(fast_replace(cell, veg=cell.veg - n))
                    entries.append(HarvestEntry(
                        source=f"cell:{r},{c}", crop="veg", amount=n,
                        emptied=cell.veg == n))
                else:
                    assert not extra, (
                        f"take fold-in names empty field ({r},{c})")
                    new_row.append(cell)   # empty field (already harvested or never sown)
            else:
                assert (r, c) not in extras, (
                    f"take fold-in names non-field cell ({r},{c})")
                new_row.append(cell)
        new_grid_rows.append(tuple(new_row))

    # Card-fields — the same one event, after the board scan (rulings 45-47).
    new_store = p.card_state
    card_gain = Resources()
    card_keys_seen: set = set()
    from agricola.cards.card_fields import (   # local import: load-order safe
        card_field_stacks,
        owned_card_fields,
        stack_after_take,
        stack_take_good,
        stacks_to_store,
    )
    for cid in owned_card_fields(p):
        stacks = list(card_field_stacks(p, cid))
        changed = False
        for i, stack in enumerate(stacks):
            key = ("card", cid, i)
            card_keys_seen.add(key)
            good, n = stack_take_good(stack)
            if n == 0:
                assert key not in extras, (
                    f"take fold-in names empty card stack {key}")
                continue
            if key in skip_cells:
                continue   # replaced (Grain Thief): untouched, no entry
            take = 1 + extras.get(key, 0)
            assert take <= n, (
                f"take fold-in over-harvests card stack {key}: {take} > {n} {good}")
            card_gain = card_gain + Resources(**{good: take})
            stacks[i] = stack_after_take(stack, good, take)
            changed = True
            entries.append(HarvestEntry(
                source=f"card:{cid}", crop=good, amount=take,
                emptied=n == take))
        if changed:
            new_store = stacks_to_store(new_store, cid, stacks)
    stray = {k for k in extras if isinstance(k, tuple) and len(k) == 3
             and k not in card_keys_seen}
    stray |= {k for k in skip_cells if isinstance(k, tuple) and len(k) == 3
              and k not in card_keys_seen}
    assert not stray, f"take fold-in names unknown card stacks: {stray}"

    # Fields cannot lie inside pastures, so the pasture cache is preserved
    # via fast_replace's natural ride-along.
    new_farmyard = fast_replace(p.farmyard, grid=tuple(new_grid_rows))
    new_resources = (p.resources + Resources(grain=grain_gain, veg=veg_gain)
                     + card_gain)
    if bonus is not None:
        new_resources = new_resources + bonus
    new_player = fast_replace(p, farmyard=new_farmyard,
                              resources=new_resources, card_state=new_store)
    state = _update_player(state, idx, new_player)
    return state, HarvestOccasion(source=source, entries=tuple(entries))


def emit_harvest_occasion(
    state: GameState, idx: int, occasion: HarvestOccasion,
) -> GameState:
    """Record a card-granted harvesting occasion and fire its consequences —
    the seam a during-window additional-harvest trigger (Stable Manure, Scythe
    E73) calls from its apply_fn AFTER applying its own goods movement
    (HARVEST_WINDOWS_DESIGN.md §4d: each such fire is its OWN occasion, source
    "card:<id>", separate from the take).

    Appends the occasion to the top PendingFieldPhase's frame-scoped manifest
    when one is up (the normal case — the trigger fired from that host), then
    fires the per-occasion automatic effects. Also callable frameless: a bare
    `field_take` caller (Bumper Crop, ruling 4) emits its occasion this way so
    non-phase-keyed occasion consumers still attach."""
    from agricola.cards.harvest_windows import (
        apply_harvest_occasion_autos,
        maybe_host_occasion_triggers,
    )

    top = state.pending_stack[-1] if state.pending_stack else None
    if isinstance(top, PendingFieldPhase):
        state = replace_top(state, fast_replace(
            top, occasions=top.occasions + (occasion,)))
    state, occ_autos = apply_harvest_occasion_autos(state, idx, occasion)
    state, _hosted = maybe_host_occasion_triggers(
        state, idx, occasion, autos_fired=occ_autos)
    return state


def _execute_field_take(
    state: GameState, player_idx: int, commit,
) -> GameState:
    """Run the mandatory take at a PendingFieldPhase host (card game only):
    fold the take-modifiers into one combined take — the auto fold-ins
    (Scythe Worker) plus the commit's chosen (card_id, variant) pairs
    (Stable Manure; user ruling 11: one simultaneous event) — apply it,
    record the take occasion on the frame (`take_fired=True` — Proceed
    becomes legal), then fire the per-occasion automatic effects. The frame
    is recorded BEFORE the autos fire (the record-first rule of
    `_apply_fire_trigger`: an auto that pushes a frame must land ON TOP of
    the already-updated host). No pop — the window's free-order triggers
    remain available; Proceed exits.

    The once-per-harvest conversion-budget reset is NOT here — it happens
    unconditionally at harvest entry in the walk (engine._advance_harvest),
    so a future phase-skipping player (Lunchtime Beer) still gets a fresh
    budget and future anytime-in-harvest conversions (design doc §10) start
    the harvest reset."""
    from agricola.cards.harvest_windows import (
        apply_harvest_occasion_autos,
        fold_chosen_modifiers,
        maybe_host_occasion_triggers,
    )

    top = state.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and not top.take_fired, top
    plan = fold_chosen_modifiers(state, player_idx,
                                 getattr(commit, "modifiers", ()))
    assert plan is not None, (
        "infeasible modifier combination reached the executor — the "
        "enumerator's feasibility filter must drop it")
    state, occasion = field_take(state, player_idx,
                                 extra_takes=plan.extras or None,
                                 skip_cells=plan.skipped,
                                 bonus=plan.bonus)
    state = replace_top(state, fast_replace(
        top, take_fired=True, occasions=top.occasions + (occasion,)))
    state, occ_autos = apply_harvest_occasion_autos(state, player_idx, occasion)
    state, _hosted = maybe_host_occasion_triggers(
        state, player_idx, occasion, autos_fired=occ_autos)
    return state


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

    The pending stays on top to host further craft decisions plus the final
    CommitConvert. A variant-bearing conversion (spec.variants_fn set — Craft
    Brewery) has the chosen variant threaded into its side_effect_fn.
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

    # Optional non-food effect (e.g. Beer Keg's point). A variant-bearing
    # conversion (spec.variants_fn set — Craft Brewery) receives the chosen
    # variant as a 3rd arg.
    if spec.side_effect_fn is not None:
        if spec.variants_fn is not None:
            state = spec.side_effect_fn(state, player_idx, commit.variant)
        else:
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

        need            = helpers.feeding_requirement (2*people_total −
                          newborns + any owned card folds — Child's Toy)
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

    The trailing Stop is the explicit exit, matching the other multi-stage
    pendings.
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

    need            = feeding_requirement(state, player_idx)
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

    The dispatcher never pops; the trailing Stop is the explicit exit.
    """
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestBreed)
    p = state.players[player_idx]

    from agricola.cards.capacity_mods import sheep_min_parents

    rates_3 = cooking_rates(state, player_idx)[:3]
    sheep_min = sheep_min_parents(p)
    chosen  = Animals(sheep=commit.sheep, boar=commit.boar, cattle=commit.cattle)
    food_gained = breeding_food_gained(p.animals, chosen, rates_3, sheep_min)

    new_player = fast_replace(
        p,
        animals=chosen,
        resources=p.resources + Resources(food=food_gained),
    )
    state = _update_player(state, player_idx, new_player)
    state = replace_top(state, fast_replace(top, breed_chosen=True))

    # The breeding-OUTCOME event (card game only; empty registry = Family
    # no-op): which newborns were actually placed, by the same kept-newborn
    # indicator `breeding_food_gained` uses (pre >= 2 and post >= 3 — an
    # unaccommodated newborn is never placed, so "you must be able to
    # accommodate each newborn in order to get it" is inherent). Fired with
    # the frame already stamped breed_chosen (record-first) — its consumers
    # write CardStore latches that the frame's "breeding_outcome" triggers
    # (the sow grants) read before Stop.
    from agricola.cards.harvest_windows import (
        BREEDING_OUTCOME_AUTOS,
        apply_breeding_outcome_autos,
    )
    if BREEDING_OUTCOME_AUTOS:
        pre = p.animals
        # The fired-and-kept indicator, sheep threshold card-aware (a
        # single-parent card — Dolly's Mother — breeds from 1, so its newborn
        # must be reported too; the m=2 hardcoding here was the trap).
        outcome = BreedingOutcome(
            sheep=int(pre.sheep >= sheep_min and chosen.sheep >= sheep_min + 1),
            boar=int(pre.boar >= 2 and chosen.boar >= 3),
            cattle=int(pre.cattle >= 2 and chosen.cattle >= 3),
        )
        state = apply_breeding_outcome_autos(state, player_idx, outcome)
    return state
