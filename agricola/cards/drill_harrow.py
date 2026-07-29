"""Drill Harrow (minor improvement, D17; Dulcinaria Expansion; cost 1 wood).

Card text: "Each time before you take an unconditional 'Sow' action, you can pay 3 food
to plow 1 field."

A pay-food → plow trigger in the exact shape of Ox Goad (FOOD_PAYMENT_DESIGN.md §8),
differing only in event (the BEFORE-Sow sub-action hook) and food amount (3). The card
text's "before you take a Sow action" is the literal `before_sow` event — the before-
phase of the PendingSow host (no separate ruling needed; the text states the phase).

"Unconditional Sow" distinguishes the standard Sow sub-action (Grain Utilization /
Cultivation) from a card-granted *conditional* sow. No conditional-sow card exists in
the implemented set, so every `before_sow` event is an unconditional sow — this fires on
all of them. (If a conditional-sow card is ever added, this eligibility must additionally
inspect the PendingSow's provenance to exclude it; flagged here for that future session.)

THE STRANDING GUARD IS THE PRESERVE PAIR (ruling 87, 2026-07-29). The host is a
PendingSow whose before-phase offers only FireTrigger + CommitSow — no Stop — so once
this trigger resolves, a sow of >= 1 seed is mandatory. The 3-food payment must
therefore never consume the goods that keep that sow legal. Both halves run ONE shared
check, `_preserve_sow` ("a legal sow commit survives: a board seed, or a card-field
sow — which liquidation cannot touch"):

- ELIGIBILITY offers the fire iff the fee is payable by SOME route whose post-payment
  state passes the check (`raisable_food_preserving`; with the 3 food on hand there is
  no liquidation, so the check runs on the current state directly).
- THE RAISE FRAME's menu is filtered to exactly the passing bundles
  (`register_food_payment_preserve` under this card's resume kind) — the frame-side
  half whose ABSENCE was the executed soft-lock of 2026-07-29: eligibility proved a
  seed-preserving bundle EXISTED, but the frame offered every Pareto bundle, including
  one that cooked the last seed (1 grain / 2 sheep / Fireplace / 0 food: the
  {grain+sheep} bundle strands the forced sow; regression-pinned in
  tests/test_card_drill_harrow_preserve.py).

This replaced the hand-rolled `_seed_reserving_liquidatable` (reserve-one-seed
arithmetic), which was also over-strict in one corner: with NO board seed but a legal
card-field sow (unaffected by liquidation — bundles consume only crops/animals), it
refused a perfectly safe fire. `_preserve_sow` admits it.

`_apply` is the guard, `_pay_and_plow` the body (debit 3 food, push the plow). With ≥ 3
food on hand `_apply` runs it directly; short, it pushes a raise-only PendingFoodPayment
whose resume (registered under this card id) debits the raised food then plows.
Once-per-sow via the host's `triggers_resolved`. See PAY_FOOD_PLOW_CARDS.md /
FOOD_PAYMENT_DESIGN.md.
"""
from __future__ import annotations

from agricola.cards.specs import (
    register_food_payment_preserve,
    register_food_payment_resume,
    register_minor,
)
from agricola.cards.triggers import register
from agricola.legality import (
    _can_plow,
    raisable_food_preserving,
    register_sow_extension,
)
from agricola.pending import PendingFoodPayment, PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "drill_harrow"
_FOOD_COST = 3


def _pay_and_plow(state: GameState, idx: int) -> GameState:
    """Debit 3 food, then grant the plow. Reached directly (food on hand) and as the
    post-food-payment resume (the raise-only frame leaves the food in supply to debit)."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(food=_FOOD_COST))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


def _preserve_sow(state: GameState, idx: int) -> bool:
    """The mandatory sow stays completable on this state: a board seed survives, or a
    card-field sow is possible (its inputs — the card's empty stack + a matching good
    such as wood — are never conversion fuel, so no bundle can strand it). The 3-food
    fee needs no debit here: food is not an input to sowing. Shared verbatim between
    eligibility (existence over bundles) and the raise frame's menu filter, so they
    cannot disagree."""
    from agricola.cards.card_fields import can_sow_card_fields  # load-order safe

    p = state.players[idx]
    return (p.resources.grain >= 1 or p.resources.veg >= 1
            or can_sow_card_fields(p))


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per this sow
        return False
    p = state.players[idx]
    if not _can_plow(p):                                   # a plow must be legal
        return False
    if p.resources.food >= _FOOD_COST:
        # No liquidation happens — the fee is pure food, so the sow's goods are
        # untouched; check completability on the current state.
        return _preserve_sow(state, idx)
    # Short: offer iff SOME raise bundle leaves the mandatory sow completable —
    # the frame (below) then offers exactly those bundles.
    return raisable_food_preserving(state, idx, _FOOD_COST, Cost(), _preserve_sow)


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 3 food and grant the plow. With enough food on hand, do it directly; otherwise
    push a raise-only PendingFoodPayment and defer the pay-and-plow to its resume (which
    debits the raised food). The only cost is the 3 food, so nothing is reserved."""
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_plow(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID, reserved=Cost(),
    ))


def _sow_extension(state: GameState, p) -> bool:
    """Ruling 87 (2026-07-29): the Drill Harrow ROUTE makes a sow possible when the
    base check fails — no empty field, but a plowable cell + a board seed + the 3
    food payable by a route that preserves that seed. Registered into `_can_sow`'s
    extension registry, so the placement gates (Grain Utilization / Cultivation),
    the in-host choose gates, and every sow-granting card's eligibility (Sundial,
    Apiary, Confidant, ...) inherit it with zero per-card code — and Thresher's
    space extension consults it on the post-buy state, which is what prices the
    two-card chain correctly.

    Admission guarantees completion (the never-a-dead-end contract this registry
    demands): the sow frame entered on this route offers only this card's fire —
    mandatory by the frame's exit structure, the user-ratified consequence — and
    the fire's preserve pair guarantees a seed survives the payment while the plow
    supplies the field. Card-field sows never need this route: they need no board
    field, and the base check already covers them."""
    if CARD_ID not in p.minor_improvements:
        return False
    if not _can_plow(p):
        return False
    if p.resources.grain < 1 and p.resources.veg < 1:
        return False                 # the route sows a BOARD seed; DH grants no seed
    idx = 0 if p is state.players[0] else 1
    if p.resources.food >= _FOOD_COST:
        return True                  # fee is pure food — the seed is untouched
    return raisable_food_preserving(state, idx, _FOOD_COST, Cost(), _preserve_sow)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register("before_sow", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_plow)
# Ruling 87 (2026-07-29): the frame-side half of the stranding guard — the raise
# menu offers only the sow-preserving bundles (same check as eligibility).
register_food_payment_preserve(CARD_ID, _preserve_sow)
# Ruling 87: the route is itself sow-capability — see _sow_extension.
register_sow_extension(_sow_extension)
