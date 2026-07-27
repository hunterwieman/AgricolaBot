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
    lesson), or raisable by liquidation (`_liquidatable_to`, the plow_hero
    shape). On the liquidation path the predicate must hold under EVERY
    conversion bundle the raise frame will offer (`_food_payment_commits`, the
    frame's own enumeration, post-states mirrored from `_execute_food_payment`'s
    math): the frame is generic and cannot filter bundles per-card, so a bundle
    that cooked the very good the destination needs (e.g. the grain that paid
    the only playable minor) would strand the jump after payment. Requiring all
    bundles keeps every reachable resume sound. This is conservative in one
    remote corner — when bundles DIFFER (one cooks the needed good, another
    does not) the jump is withheld although paying with the preserving bundle
    would be legal in physical play; an exact treatment needs a per-card
    bundle-filter seam on PendingFoodPayment (the ruling-75 pair-gate shape) and
    is left to a user decision. (The simulation also omits cook-reaction bonuses
    such as Cookery Lesson's food — a strict under-count, so it can only
    withhold, never strand.)

"You can pay" → optional trigger (`register`, not `register_auto`); declining is
implicit (Stop/Proceed instead — no SkipTrigger). Once per window via the host's
`triggers_resolved`; once per turn via the latch. Played via Lessons; on-play is
a no-op. 4+-player card: registered but never dealt at 2 players — tests inject
it (the Lodger precedent). Card-only state (the latch) is empty in the Family
game; no Family surface changes.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import owns_improvement_decline_income, register
from agricola.cards.worker_moves import relocate_and_use
from agricola.helpers import cooking_rates
from agricola.legality import (
    _can_afford_any_major_improvement,
    _can_build_room,
    _can_build_stable,
    _food_payment_commits,
    _liquidatable_to,
    playable_minors,
)
from agricola.pending import PendingFoodPayment, PendingMajorMinorImprovement, push
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
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


def _post_payment_state(state: GameState, idx: int, commit) -> GameState:
    """The state the destination will see after the liquidation bundle `commit`
    (a CommitFoodPayment) and the 1-food fee: mirrors `_execute_food_payment`'s
    raise math (base goods at `cooking_rates`, named converters' 6-tuple input +
    premium food), then the resume's debit. Used only to gate eligibility —
    never applied."""
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS

    sR, bR, cR, vR = cooking_rates(state, idx)
    produced = (commit.grain + commit.veg * vR + commit.sheep * sR
                + commit.boar * bR + commit.cattle * cR)
    conv_cost = Resources()
    conv_food = 0
    for cid in commit.conversions:
        inp, food_out = HARVEST_CONVERSIONS[cid].frontier_fire
        conv_cost = conv_cost + Resources(
            grain=inp[0], veg=inp[1], wood=inp[2],
            clay=inp[3], reed=inp[4], stone=inp[5])
        conv_food += food_out
    p = state.players[idx]
    p = fast_replace(
        p,
        resources=(p.resources
                   - Resources(grain=commit.grain, veg=commit.veg) - conv_cost
                   + Resources(food=produced + conv_food - _FOOD_COST)),
        animals=p.animals - Animals(commit.sheep, commit.boar, commit.cattle),
    )
    return _update_player(state, idx, p)


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
    if not _liquidatable_to(state, idx, p, Resources(food=_FOOD_COST)):
        return False
    bundles = _food_payment_commits(state, idx, _FOOD_COST, Cost())
    return bool(bundles) and all(
        _dest_legal(_post_payment_state(state, idx, c), idx, dest)
        for c in bundles)


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
    a raise-only PendingFoodPayment and defer to its resume. The only cost is the
    1 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_jump(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID,
        reserved=Cost(),
    ))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
# One shared apply on both events (the Merchant dual-event pattern — the second
# register's CARDS[card_id] overwrite is harmless because apply_fn is identical);
# per-event eligibility carries each side's own gate.
register("after_action_space", CARD_ID, _eligible_farm_expansion, _apply)
register("after_major_minor_improvement", CARD_ID, _eligible_major_improvement, _apply)
register_food_payment_resume(CARD_ID, _pay_and_jump)
