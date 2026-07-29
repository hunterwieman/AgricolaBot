"""Full Peasant (occupation, B130; Bubulcus Expansion; players 3+).

Card text: "Each time after you use the "Grain Utilization" or "Fencing" action space
while the other is unoccupied, you can pay 1 food to use the other space with the same
person."
Clarification: "The person ends on the second action space used."
Errata: "ERRATA: The “jump” to a second action space may only be done once per turn."

The first consumer of the same-worker JUMP machinery (`worker_moves.relocate_and_use`),
implemented under user ruling 81 (2026-07-26):

1. (item 1) The jump is an OPTIONAL trigger in the SOURCE space's `after_action_space`
   window — takeable before other after-window triggers. Firing it moves the acting
   worker's board marker source → destination and runs the destination's FULL action
   (`initiate_space_use`): the destination's frames stack above the source's
   after-window host, resolve completely (its own before/after card windows fire — a
   relocation IS a use), and the walk returns to the source's window for any remaining
   triggers / Stop. The clarification falls out structurally: the person ends on the
   second action space used.
2. (item 2) "While the other is unoccupied" is checked at the `after_action_space`
   TRIGGER time: the destination must hold ZERO workers — of any player — when the
   trigger's eligibility is evaluated. This is the plain board worker count, not
   `_is_available`: the occupancy-override / space-block registries are
   placement-legality machinery, not this card's printed condition.
3. (ruling 79, via `relocate_and_use`) The jump mints NO placement number —
   `placements_this_round` is never touched; the worker keeps the number of the
   placement that started the turn, so ordinal-reading cards at the destination read
   correctly.

Eligibility, beyond source ∈ {Grain Utilization, Fencing} at the owner's own host:

- **Once per TURN** (the errata) via the `used_this_turn` latch (cleared by the engine
  at every turn boundary). The latch is also what stops the jump-back chain: after a
  Grain Utilization → Fencing jump, the destination's own after-window would otherwise
  re-offer the trigger (the source is now vacated, i.e. "the other is unoccupied").
  The host's `triggers_resolved` additionally gives once-per-window, as always.
- **Destination revealed.** Both spaces are stage-1 round cards, so one can be in play
  before the other; a space not yet turned up is not in the game and cannot be "used"
  by any means. (This is the `revealed` fact read directly off the board — not
  `_is_available`, whose occupancy machinery item 2 supersedes.)
- **The fee, uniformly for BOTH destinations (ruling 87, 2026-07-29): debit it, then
  ask the destination's own gate on the true post-payment state.** Food on hand → one
  direct route: check `_dest_action_legal` on the fee-debited state. Food short → the
  jump is offered iff SOME liquidation bundle's post-state (fee debited) keeps the
  destination usable (`raisable_food_preserving`), and the raise frame's menu is
  filtered to exactly those bundles (`register_food_payment_preserve`, both resume
  kinds). This revoked ruling 82's "one-direction sufficiency" (the Fencing direction
  used to skip the destination coupling on the crops/animals-vs-wood disjointness
  argument): that shortcut rested on catalog facts — no anytime converter couples food
  to building resources in either direction — that cards like Large Pottery D60 and
  the Grocer/Clay Carrier family will break, in both the too-permissive and
  too-strict directions at once. The uniform shape is catalog-independent: whatever
  inputs the destination gate learns to read (a Thresher-style purchase making food a
  Grain Utilization input; a converter making food a Fencing input), the state it is
  asked about is already the real one.

Both source spaces are non-atomic — always hosted — so no `register_action_space_hook`.
A 3+-player card: registered here but never dealt in the 2-player pool (the web UI's
players filter); tests inject it (the Lodger precedent). Steam Machine interplay is a
deferred seam, deliberately not attempted.
"""
from __future__ import annotations

from agricola.cards.specs import (
    register_food_payment_preserve,
    register_food_payment_resume,
    register_occupation,
)
from agricola.cards.triggers import register
from agricola.cards.worker_moves import relocate_and_use
from agricola.helpers import buildable_fences
from agricola.legality import (
    _any_legal_pasture_commit,
    _can_bake_bread,
    _can_sow,
    _space_enabled_by_card,
    raisable_food_preserving,
)
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "full_peasant"
_FOOD_COST = 1
# The printed pair: source -> the OTHER space (the jump destination).
_OTHER = {"grain_utilization": "fencing", "fencing": "grain_utilization"}


def _debit_food(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, resources=p.resources - Resources(food=_FOOD_COST))
        if i == idx else state.players[i] for i in range(2)))


def _dest_action_legal(state: GameState, idx: int, dest: str) -> bool:
    """The destination's own action is usable by player `idx` on `state` — the
    card-game per-space placement predicate minus `_is_available` (occupancy is the
    ruled trigger-time zero-workers check; reveal is checked by the caller). The
    space-enable registry is consulted exactly as the placement gate does (ruling
    87): a jump IS a use, so a Thresher-style before-window route that would make
    a placement legal makes the jump destination legal too — evaluated here on
    the post-fee state the callers pass, which is what prices the fee + buy chain
    (2 food for Fencing → Grain Utilization via the buy; 1 food refused)."""
    p = state.players[idx]
    if dest == "grain_utilization":
        return (_can_sow(state, p) or _can_bake_bread(state, p)
                or _space_enabled_by_card(state, dest, idx))
    return (buildable_fences(p) >= 1 and _any_legal_pasture_commit(state, p)
            or _space_enabled_by_card(state, dest, idx))


def _preserve_gu(post: GameState, idx: int) -> bool:
    """Grain-Utilization direction (ruling 87): the destination must be usable on the
    post-bundle, POST-FEE state. The fee debit matters the moment the gate learns any
    food-dependent route (a Thresher-style before-window purchase), so it is debited
    unconditionally — uniform with `_preserve_fencing`, never a per-direction premise."""
    return _dest_action_legal(_debit_food(post, idx), idx, "grain_utilization")


def _preserve_fencing(post: GameState, idx: int) -> bool:
    """Fencing direction (ruling 87): same uniform shape. Under the current catalog no
    bundle can touch wood and no gate input reads food, so this filter passes every
    bundle today — it exists so correctness never rests on those catalog facts."""
    return _dest_action_legal(_debit_food(post, idx), idx, "fencing")


_PRESERVE = {"grain_utilization": _preserve_gu, "fencing": _preserve_fencing}


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:            # once per window (enumerator's filter, kept as belt)
        return False
    p = state.players[idx]
    if CARD_ID in p.used_this_turn:             # ERRATA: once per turn (also stops the jump-back chain)
        return False
    dest = _OTHER.get(state.pending_stack[-1].space_id)
    if dest is None:                            # the after-window of some other space
        return False
    sp = get_space(state.board, dest)
    if not sp.revealed:                         # a round card not yet in play cannot be used
        return False
    # Ruling 81 item 2: "while the other is unoccupied" is judged NOW, at trigger
    # time — the destination must hold zero workers (of any player).
    if any(w != 0 for w in sp.workers):
        return False
    # Ruling 87: pay-then-still-usable, uniformly. Food on hand -> the single direct
    # route, destination gate asked on the fee-debited state. Short -> SOME bundle's
    # post-fee state must keep the destination usable (the frame then offers exactly
    # those bundles — never a dead end, never a deleted legal raise line).
    if p.resources.food >= _FOOD_COST:
        return _dest_action_legal(_debit_food(state, idx), idx, dest)
    return raisable_food_preserving(
        state, idx, _FOOD_COST, Cost(), _PRESERVE[dest])


def _pay_and_jump(state: GameState, idx: int) -> GameState:
    """Debit the 1 food, latch the errata's once-per-turn, and jump. Reached directly
    (food on hand) and as the post-food-payment resume (the raise-only frame leaves the
    raised food in supply to debit). On both paths the top frame is the SOURCE's
    after-window host (`_execute_food_payment` pops its frame before resuming), so the
    source is read off it and the destination is the other of the pair."""
    source = state.pending_stack[-1].space_id
    dest = _OTHER[source]
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=p.resources - Resources(food=_FOOD_COST),
        used_this_turn=p.used_this_turn | {CARD_ID},
    )
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return relocate_and_use(state, idx, source, dest)


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 food and jump. With the food on hand, do it directly; otherwise push a
    raise-only PendingFoodPayment — its resume_kind carries the DESTINATION, so the
    frame's preserve filter (registered for BOTH directions — ruling 87) offers
    exactly the bundles that keep the destination usable. The only cost is the 1 food,
    so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_jump(state, idx)
    dest = _OTHER[state.pending_stack[-1].space_id]
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST,
        resume_kind=f"{CARD_ID}:{dest}", reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("after_action_space", CARD_ID, _eligible, _apply)
# The resume re-reads the source off the host below, so one fn serves both
# direction-keyed resume kinds; the preserve check registers for BOTH directions
# (ruling 87 — uniform debit-then-gate; no structurally-safe shortcut).
register_food_payment_resume(f"{CARD_ID}:grain_utilization", _pay_and_jump)
register_food_payment_resume(f"{CARD_ID}:fencing", _pay_and_jump)
register_food_payment_preserve(f"{CARD_ID}:grain_utilization", _preserve_gu)
register_food_payment_preserve(f"{CARD_ID}:fencing", _preserve_fencing)
