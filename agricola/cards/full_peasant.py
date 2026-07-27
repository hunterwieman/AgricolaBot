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
- **The 1 food payable, liquidation-aware** (`_liquidatable_to`, never `food >= 1`) —
  the Plow Hero payment shape: direct debit when the food is on hand, else a raise-only
  `PendingFoodPayment(resume_kind=CARD_ID)` whose registered resume debits the raised
  food and jumps.
- **Never a dead-end: the destination's own action must be legal right now** — the same
  conjuncts as its card-game placement predicate minus availability (handled above):
  Grain Utilization needs a sowable field or a bakeable grain+baker (`_can_sow` /
  `_can_bake_bread`); Fencing needs a fence piece placeable (`buildable_fences`) plus a
  legal pasture commit (`_any_legal_pasture_commit`, the free-fence-aware single
  authority on fence affordability). `_legal_fencing`'s Family-only `wood < 1` fast
  reject is a pure optimization of that same authority; this card is card-game-only, so
  it is not repeated here.

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
    _liquidatable_to,
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


def _dest_action_legal(state: GameState, idx: int, dest: str) -> bool:
    """The destination's own action is usable by player `idx` right now — the
    card-game per-space placement predicate minus `_is_available` (occupancy is the
    ruled trigger-time zero-workers check; reveal is checked by the caller)."""
    p = state.players[idx]
    if dest == "grain_utilization":
        return _can_sow(p) or _can_bake_bread(state, p)
    return buildable_fences(p) >= 1 and _any_legal_pasture_commit(state, p)


def _preserve_gu(post: GameState, idx: int) -> bool:
    """The Grain-Utilization preserve check (ruling 82): after a fee-raising
    liquidation bundle, the destination's own action must still be usable — the
    engine's GU predicate on the POST-BUNDLE state, so a bundle that cooks the last
    sowable crop is withheld while any preserving bundle stays offered. Reuses the
    same predicate as the trigger-time gate, so sow-extending cards (a Potter
    Ceramics-style clay sow, if implemented) compose automatically. The 1-food fee
    itself needs no simulation here: food is not an input to sow or bake."""
    return _dest_action_legal(post, idx, "grain_utilization")


def _fee_payable(state: GameState, idx: int, dest: str) -> bool:
    """Can the 1-food fee be paid — by ANY legal route — without stranding `dest`?

    Direct (food on hand): always destination-safe — the fee is food-only, and
    neither destination consumes food (GU: crops/baker; Fencing: wood + pieces).

    Raised by liquidation, per direction:
    - dest == "fencing": structurally safe TODAY — work-phase liquidation draws only
      on crops and animals (the wood-eating span converters are harvest-window-scoped
      and never active during a placement), while Fencing costs wood + fence pieces:
      disjoint pools, so `_liquidatable_to` existence is the whole check. CAVEAT for
      future cards: if an ANYTIME converter with building-resource input ever lands
      (the Clay Carrier family), this disjointness breaks and the direction needs the
      preserve check too.
    - dest == "grain_utilization": the raise can cook the very crop GU needs, so a
      bundle exists-and-is-offered only if its post-state keeps GU usable
      (`raisable_food_preserving` + the frame's preserve filter — ruling 82; a plain
      food-on-hand gate would make rules-legal moves unplayable, never acceptable)."""
    p = state.players[idx]
    if p.resources.food >= _FOOD_COST:
        return True
    if dest == "fencing":
        return _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST))
    return raisable_food_preserving(
        state, idx, _FOOD_COST, Cost(), _preserve_gu)


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
    if not _dest_action_legal(state, idx, dest):   # never a dead-end
        return False
    return _fee_payable(state, idx, dest)


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
    frame's preserve filter (registered for the Grain-Utilization direction only)
    offers exactly the bundles that keep the destination usable (ruling 82). The
    only cost is the 1 food, so nothing is reserved."""
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
# direction-keyed resume kinds; the preserve check registers for the
# Grain-Utilization direction only (the Fencing direction is structurally safe —
# see _fee_payable).
register_food_payment_resume(f"{CARD_ID}:grain_utilization", _pay_and_jump)
register_food_payment_resume(f"{CARD_ID}:fencing", _pay_and_jump)
register_food_payment_preserve(f"{CARD_ID}:grain_utilization", _preserve_gu)
