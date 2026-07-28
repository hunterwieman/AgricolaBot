"""Large-Scale Farmer (occupation, B150; Bubulcus Expansion; players 4+).

Card text: "Each time after you use the 'Farm Expansion' or 'Major Improvement'
action space while the other is unoccupied, you can pay 1 food to use that other
space with the same person."

Clarification: "The person ends on the second action space used."
Errata: "The 'jump' to a second action space may only be done once per turn."

A same-worker JUMP card (ruling 81, 2026-07-26 — `agricola/cards/worker_moves.py`):

  1. The jump is an OPTIONAL trigger in the SOURCE's after-window, takeable before
     other after-triggers; firing it moves the acting worker's board marker to the
     destination and runs the destination's FULL action (`relocate_and_use` →
     `engine.initiate_space_use` — a relocation IS a use, firing the destination's
     own before/after events). The destination's frames stack above the source's
     after-window host and resolve completely; the walk then returns to the
     source's after-window for any remaining triggers.
  2. "While the other is unoccupied" is checked AT THE TRIGGER TIME: the
     destination's worker counts must all be zero when eligibility runs.
  3. No placement number is minted (ruling 79 — the PHYSICAL ordinal): the worker
     keeps the number of the placement that started the turn;
     `placements_this_round` is never touched (`relocate_and_use` mints none).

THE TWO SOURCES HOST DIFFERENT EVENTS. Farm Expansion is a space host
(`PendingFarmExpansion`) firing `after_action_space`; the Major Improvement
space's use runs through the composite "build a major OR play a minor" host
(`PendingMajorMinorImprovement`), which fires its OWN event pair —
`after_major_minor_improvement` — so the card registers on BOTH events with one
shared frame-dispatched apply (the Merchant dual-event pattern; a second
`register` for the same card id overwrites `CARDS[card_id]`, which is harmless
only because both registrations share the SAME apply_fn).

PROVENANCE GATE (major side): the card names the action SPACE, but the composite
frame is also pushed by House Redevelopment (`initiated_by_id =
"house_redevelopment"`) and by card grants (Angler `"card:angler"`, Merchant
`"card:merchant"`, ...), which are NOT the space. Only the space-pushed composite
carries `initiated_by_id == "space:major_improvement"` (preserved by the
`ChooseSubAction("improvement")` handler — resolution.py's major_improvement
branch), so that provenance is the gate. The space host's own later
`after_action_space` window (space_id == "major_improvement") is deliberately NOT
a jump surface — the ruled seam is the composite's after-window.

Errata "once per turn" is a `used_this_turn` latch (cleared at every turn
boundary by the engine), set at the moment the fee is paid. The latch is also
what stops the chain-back: the destination's own after-window fires on a FRESH
frame (empty `triggers_resolved`) with the source space now vacated by the move,
so without the latch the jump would immediately be offered in reverse.

Eligibility (never grant a dead end — a jump onto a host with no legal child is
an empty legal set, i.e. a soft-lock, since placement legality normally
guarantees every space host a doable mandatory):

  - the same person must still stand on the source space (it does after a
    placement; the guard keeps `relocate_and_use`'s move-assert unreachable);
  - the destination is unoccupied (ruling item 2);
  - the destination's own action must be legal ON THE STATE THE JUMP LANDS ON —
    the per-space predicate from the card-game placement-legality table, minus
    `_is_available` (the occupancy/availability half is replaced by the
    unoccupied check above):
      Farm Expansion:    `_can_build_room` OR `_can_build_stable` (2 wood),
      Major Improvement: `_can_afford_any_major_improvement` OR
                         `playable_minors(composite_only_ok=True)` OR
                         `owns_improvement_decline_income` (Field Merchant's
                         printed "place just to decline" applies to any use of
                         the space, a jump included — same predicate as the
                         placement gate);
  - the 1 food is payable: on hand (then the predicate is checked on the state
    with the fee debited — with exactly 1 food, a destination reachable only
    via a 1-food minor would be stranded by paying, the Merchant post-payment
    lesson), or raisable by liquidation — a direction-keyed check (ruling 82,
    2026-07-26: the food-payment PRESERVE seam). Toward Farm Expansion, bare
    raise EXISTENCE (`_liquidatable_to`) is the whole check: a work-phase raise
    consumes only crops/animals, disjoint from the wood/reed the destination
    needs (the invariant `tests/test_liquidation_disjointness.py` pins; see
    `_jump_ok`'s caveat for the converter class that would break it). Toward
    Major Improvement, `raisable_food_preserving` with the `_preserve_mi`
    check: the jump is offered iff SOME liquidation bundle leaves the
    destination usable on the post-fee state, and the same check — registered
    frame-side via `register_food_payment_preserve` — filters the raise
    frame's menu down to exactly the preserving bundles, so the player can
    always raise the fee but never into a stranded destination. Probe and
    frame share one simulation (`legality._apply_liquidation_bundle`,
    cook-reaction bonuses included), so they can never disagree. The earlier
    all-bundles-must-pass form withheld the jump whenever ANY bundle failed —
    itself a deletion of a rules-legal line of play, corrected by ruling 82.

"You can pay" → optional trigger (`register`, not `register_auto`); declining is
implicit (Stop/Proceed instead — no SkipTrigger). Once per window via the host's
`triggers_resolved`; once per turn via the latch. Played via Lessons; on-play is
a no-op. 4+-player card: registered but never dealt at 2 players — tests inject
it (the Lodger precedent). Card-only state (the latch) is empty in the Family
game; no Family surface changes.
"""
from __future__ import annotations

from agricola.cards.specs import (
    register_food_payment_preserve,
    register_food_payment_resume,
    register_occupation,
)
from agricola.cards.triggers import owns_improvement_decline_income, register
from agricola.cards.worker_moves import relocate_and_use
from agricola.legality import (
    _can_afford_any_major_improvement,
    _can_build_room,
    _can_build_stable,
    _liquidatable_to,
    playable_minors,
    raisable_food_preserving,
)
from agricola.pending import PendingFoodPayment, PendingMajorMinorImprovement, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "large_scale_farmer"
_FOOD_COST = 1
# The printed pair: each space's "other" space.
_OTHER = {"farm_expansion": "major_improvement",
          "major_improvement": "farm_expansion"}


def _update_player(state: GameState, idx: int, p) -> GameState:
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _debit_food(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    return _update_player(state, idx, fast_replace(
        p, resources=p.resources - Resources(food=_FOOD_COST)))


def _dest_legal(state: GameState, idx: int, dest: str) -> bool:
    """The destination's own action is legal for `idx` on `state` — the card-game
    placement predicate minus `_is_available` (occupancy is the separate
    unoccupied-at-trigger-time check)."""
    p = state.players[idx]
    if dest == "farm_expansion":
        return _can_build_room(state, p) or _can_build_stable(
            state, p, Resources(wood=2))
    # major_improvement — mirror `_legal_major_improvement_cards`.
    return (_can_afford_any_major_improvement(state, p)
            or bool(playable_minors(state, idx, composite_only_ok=True))
            or owns_improvement_decline_income(state, idx))


def _preserve_mi(post_bundle: GameState, idx: int) -> bool:
    """The Major-Improvement-direction preserve check (ruling 82): after a
    fee-raising liquidation bundle, the destination must still be usable ON THE
    POST-FEE state — the fee itself matters here, because a food-costing minor can
    be the only thing making the space usable. Evaluated per bundle by the frame's
    enumerator (only preserving bundles are offered) and by the eligibility probe."""
    return _dest_legal(_debit_food(post_bundle, idx), idx, "major_improvement")


def _jump_ok(state: GameState, idx: int, source: str) -> bool:
    """The shared eligibility core: latch, same-person, unoccupied destination,
    and pay-then-still-usable (see the module docstring)."""
    p = state.players[idx]
    if CARD_ID in p.used_this_turn:                   # errata: once per turn
        return False
    dest = _OTHER[source]
    if any(get_space(state.board, dest).workers):     # "while the other is
        return False                                  #  unoccupied" (item 2)
    if get_space(state.board, source).workers[idx] < 1:   # "the same person"
        return False
    if p.resources.food >= _FOOD_COST:
        # Direct debit is the only payment route with food on hand — check the
        # destination on the exact post-fee state.
        return _dest_legal(_debit_food(state, idx), idx, dest)
    if dest == "farm_expansion":
        # Structurally safe TODAY (ruling 82's one-direction sufficiency): a
        # work-phase raise consumes only crops/animals (the building-resource span
        # converters are harvest-window-scoped, never active at a placement), while
        # Farm Expansion costs wood/reed + pieces — disjoint pools, so bare raise
        # EXISTENCE is the whole check. CAVEAT: if an ANYTIME converter with
        # building-resource input ever lands (the Clay Carrier family), this
        # disjointness breaks and the direction needs the preserve check too.
        return _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))
    # major_improvement: SOME bundle must leave the destination usable after the
    # fee (ruling 82 — the frame then offers exactly those bundles, so the player
    # can always raise the fee but never into a stranded destination; the old
    # all-bundles-must-pass form wrongly withheld the jump whenever ANY bundle
    # failed, deleting a rules-legal line of play).
    return raisable_food_preserving(state, idx, _FOOD_COST, Cost(), _preserve_mi)


def _eligible_farm_expansion(state: GameState, idx: int, triggers_resolved) -> bool:
    """`after_action_space` clause — fires only on the Farm Expansion host."""
    if CARD_ID in triggers_resolved:                  # once per window
        return False
    top = state.pending_stack[-1]
    if getattr(top, "space_id", None) != "farm_expansion":
        return False
    return _jump_ok(state, idx, "farm_expansion")


def _eligible_major_improvement(state: GameState, idx: int, triggers_resolved) -> bool:
    """`after_major_minor_improvement` clause — fires only on the composite the
    Major Improvement SPACE pushed (provenance "space:major_improvement"), never
    on House Redevelopment's step or a card-granted composite."""
    if CARD_ID in triggers_resolved:                  # once per window
        return False
    top = state.pending_stack[-1]
    if top.initiated_by_id != "space:major_improvement":
        return False
    return _jump_ok(state, idx, "major_improvement")


def _pay_and_jump(state: GameState, idx: int) -> GameState:
    """Debit the 1 food, latch the once-per-turn errata, and run the jump.
    Reached directly (food on hand) and as the post-food-payment resume (the
    raise-only frame banked the food; the top frame is the source host again —
    `_execute_food_payment` pops before dispatching)."""
    top = state.pending_stack[-1]
    source = ("major_improvement"
              if isinstance(top, PendingMajorMinorImprovement)
              else top.space_id)                      # PendingFarmExpansion
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(food=_FOOD_COST),
        used_this_turn=p.used_this_turn | {CARD_ID},
    )
    state = _update_player(state, idx, p)
    return relocate_and_use(state, idx, source, _OTHER[source])


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 food and jump. With the food on hand, do it directly; otherwise push
    a raise-only PendingFoodPayment whose resume_kind carries the DESTINATION, so
    the frame's preserve filter (registered for the Major-Improvement direction
    only — ruling 82) offers exactly the destination-preserving bundles. The only
    cost is the 1 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_jump(state, idx)
    top = state.pending_stack[-1]
    source = ("major_improvement"
              if isinstance(top, PendingMajorMinorImprovement)
              else top.space_id)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST,
        resume_kind=f"{CARD_ID}:{_OTHER[source]}", reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
# One shared apply on both events (the Merchant dual-event pattern — the second
# register's CARDS[card_id] overwrite is harmless because apply_fn is identical);
# per-event eligibility carries each side's own gate.
register("after_action_space", CARD_ID, _eligible_farm_expansion, _apply)
register("after_major_minor_improvement", CARD_ID, _eligible_major_improvement, _apply)
# The resume re-reads the source off the host below, so one fn serves both
# direction-keyed resume kinds; the preserve check registers for the
# Major-Improvement direction only (the Farm-Expansion direction is structurally
# safe — see _jump_ok).
register_food_payment_resume(f"{CARD_ID}:major_improvement", _pay_and_jump)
register_food_payment_resume(f"{CARD_ID}:farm_expansion", _pay_and_jump)
register_food_payment_preserve(f"{CARD_ID}:major_improvement", _preserve_mi)
