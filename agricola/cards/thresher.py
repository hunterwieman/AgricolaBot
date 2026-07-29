"""Thresher (occupation, C112; Consul Dirigens Expansion; players 1+).

Card text: "Immediately before each time you use the 'Grain Utilization',
'Farmland', or 'Cultivation' action space, you can buy 1 grain for 1 food."

Clarification: "This effect happens before using the space, and must happen
before effects such as Flail C026."

Category 4 (action-space hook). The buy is the player's choice → an OPTIONAL
trigger (register, not register_auto). Fires on the BEFORE-phase of the three
named spaces: "each time you use [space]" fires before the space's own effect
(the Trigger-Timing ruling), and the card's own clarification restates this —
the grain bought here is therefore available to the subsequent Sow/space effect
(and resolves before a later Flail). `triggers_resolved` scoping makes it
re-eligible on each new space use and limits it to at most once per use.

THE PRICE — 1 food, paid through the shared food-payment path (ruling 82
(2026-07-26); corrected 2026-07-27): the at-any-time conversions are legal
payment routes for a food cost, so a plain food-on-hand gate would delete
rules-legal plays. Eligibility is liquidation-aware (``_liquidatable_to``);
with the food on hand ``_apply`` pays and grants directly, and when short it
pushes a raise-only ``PendingFoodPayment`` whose registered resume
(``_pay_and_buy``) debits the raised food and grants the grain. The grain
output lands only after the payment, so the raise bundles run on the
pre-effect state — the bought grain is never its own conversion fuel.

All three spaces (Grain Utilization, Farmland, Cultivation) are non-atomic and so
always hosted — no register_action_space_hook is needed. Played via Lessons; its
on-play is a no-op. See CARD_IMPLEMENTATION_PLAN.md Category 4 and the
Cattle Feeder / Animal Dealer food-payment templates.
"""
from __future__ import annotations

from agricola.cards.specs import register_food_payment_resume, register_occupation
from agricola.cards.triggers import register
from agricola.legality import _liquidatable_to, register_space_enable_extension
from agricola.pending import PendingFoodPayment, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "thresher"
SPACES = frozenset({"grain_utilization", "farmland", "cultivation"})
_FOOD_COST = 1


def _pay_and_buy(state: GameState, idx: int) -> GameState:
    """Debit 1 food and grant 1 grain. Reached directly (food on hand) and as
    the post-food-payment resume (the raise-only frame leaves the food in
    supply for this to debit)."""
    p = state.players[idx]
    new_player = fast_replace(p, resources=p.resources + Resources(food=-_FOOD_COST, grain=1))
    new_players = tuple(
        new_player if i == idx else state.players[i]
        for i in range(len(state.players))
    )
    return fast_replace(state, players=new_players)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if state.pending_stack[-1].space_id not in SPACES:
        return False
    # Payable outright or by liquidating convertible goods to the 1 food.
    return _liquidatable_to(state, idx, state.players[idx],
                            Resources(food=_FOOD_COST))


def _apply(state: GameState, idx: int) -> GameState:
    if state.players[idx].resources.food >= _FOOD_COST:
        return _pay_and_buy(state, idx)
    return push(state, PendingFoodPayment(
        player_idx=idx, food_needed=_FOOD_COST, resume_kind=CARD_ID,
        reserved=Cost(),
    ))


def _space_enabled(state: GameState, idx: int, *, bake_counts: bool) -> bool:
    """Ruling 87 (2026-07-29, the user-ratified rule: an optional before-window
    purchase counts toward "can carry out the action" at placement time): could
    player `idx` complete this space's action via the buy?

    Evaluated EXACTLY — simulate the buy per payment case, then ask the real
    capability predicates on the resulting state — so chained enablers price
    against true post-payment resources: `_can_sow` consults its extension
    registry, so a Drill Harrow route downstream of the buy sees the food the
    buy consumed (3 food + both cards + no seed + no field → refused, the
    post-buy 2 food can't fund the 3-food plow; 4 food → admitted).

    Food >= 1: the single payment route is the direct debit — apply the buy's
    own executor (`_pay_and_buy`: −1 food, +1 grain — one implementation, the
    gate can never drift from the effect) and ask. Short: for each raise bundle
    the machinery would offer, simulate it with the shared
    `_apply_liquidation_bundle`, apply the buy, ask; admit iff some bundle
    passes. The bought grain never funds its own purchase — bundles simulate on
    the pre-grant state, matching `_apply`'s real order.

    Consulted by the PLACEMENT gates only (`_space_enabled_by_card`). The
    in-host flow needs nothing: the buy's trigger already surfaces in the
    host's before-window, and when this route is the only reason the placement
    was admitted, the host's must-take-at-least-one-effect exit structure makes
    the fire the sole legal action — the ruled mandatory-buy behavior, emergent,
    pinned in tests/test_card_thresher_gate.py."""
    from agricola.legality import (
        _apply_liquidation_bundle,
        _can_bake_bread,
        _can_sow,
        _food_payment_commits,
    )

    p = state.players[idx]
    if CARD_ID not in p.occupations:
        return False

    def _enabled(s2: GameState) -> bool:
        p2 = s2.players[idx]
        return _can_sow(s2, p2) or (bake_counts and _can_bake_bread(s2, p2))

    if p.resources.food >= _FOOD_COST:
        return _enabled(_pay_and_buy(state, idx))
    for bundle in _food_payment_commits(state, idx, _FOOD_COST, Cost()):
        post = _apply_liquidation_bundle(state, idx, bundle)
        if _enabled(_pay_and_buy(post, idx)):
            return True
    return False


def _gu_enabled(state: GameState, idx: int) -> bool:
    return _space_enabled(state, idx, bake_counts=True)


def _cultivation_enabled(state: GameState, idx: int) -> bool:
    # Cultivation's other half is plow — grain never enables plowing, so only
    # the sow route counts (when plow is possible the base gate passed anyway).
    return _space_enabled(state, idx, bake_counts=False)


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register("before_action_space", CARD_ID, _eligible, _apply)
register_food_payment_resume(CARD_ID, _pay_and_buy)
# Ruling 87: the buy can be the thing making a placement legal. Farmland gets
# no extension — its action is plow-only, and grain never enables a plow (the
# buy there is a convenience, never the enabling margin).
register_space_enable_extension("grain_utilization", _gu_enabled)
register_space_enable_extension("cultivation", _cultivation_enabled)
