import agricola.cards.forest_trader  # noqa: F401

"""Tests for Forest Trader (occupation, Dulcinaria D125) — the buy-1-building-
resource option on wood/clay accumulation spaces.

Card text: "Each time you use a wood or clay accumulation space, you can also buy
exactly 1 building resource. Wood, clay, and reed cost 1 food each; stone costs 2
food."

An OPTIONAL `before_action_space` play-variant trigger on the (hooked, atomic)
`forest` and `clay_pit` hosts: one `FireTrigger(variant=<resource>)` per affordable
purchase, the host's Proceed as the decline, the host's `triggers_resolved` giving
once-per-use. Firing debits the food price and grants exactly 1 of the resource.
"""
import pytest

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    PLAY_VARIANT_TRIGGERS,
    TRIGGERS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup_env
from agricola.state import get_space


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_resources(state, idx, **kw):
    p = fast_replace(state.players[idx], resources=Resources(**kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _owned_state(idx=0, **resources):
    """Own Forest Trader + exactly the given resources; ready to place."""
    s, _env = setup_env(0)
    s = fast_replace(s, current_player=idx)
    s = _own(s, idx, "forest_trader")
    s = _set_resources(s, idx, **resources)
    return s


def _at_space(space, idx=0, **resources):
    """Own Forest Trader + the given resources, then place on `space`."""
    s = _owned_state(idx=idx, **resources)
    s = step(s, PlaceWorker(space=space))
    return s, idx


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_forest_trader_registered():
    assert "forest_trader" in OCCUPATIONS
    assert "forest_trader" in PLAY_VARIANT_TRIGGERS
    bas = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert "forest_trader" in bas


def test_forest_trader_hooks_forest_and_clay_pit_only():
    s = _owned_state(food=5)
    assert should_host_space(s, "forest", 0)
    assert should_host_space(s, "clay_pit", 0)
    assert not should_host_space(s, "reed_bank", 0)
    assert not should_host_space(s, "fishing", 0)


# ---------------------------------------------------------------------------
# Variant surfacing (affordability boundaries)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space", ["forest", "clay_pit"])
def test_all_four_variants_plus_decline_at_two_food(space):
    s, ap = _at_space(space, food=2)
    la = legal_actions(s)
    for res in ("wood", "clay", "reed", "stone"):
        assert FireTrigger(card_id="forest_trader", variant=res) in la
    assert Proceed() in la    # optional -> decline is the host's Proceed


def test_stone_absent_at_one_food():
    s, ap = _at_space("forest", food=1)
    la = legal_actions(s)
    for res in ("wood", "clay", "reed"):
        assert FireTrigger(card_id="forest_trader", variant=res) in la
    assert FireTrigger(card_id="forest_trader", variant="stone") not in la


def test_no_trigger_at_zero_food():
    # Broke -> no variant is affordable -> the trigger is not offered at all; the
    # host is still pushed (the card is owned), so only its Proceed is legal.
    s, ap = _at_space("forest")   # zero resources
    assert legal_actions(s) == [Proceed()]


# ---------------------------------------------------------------------------
# Each variant buys the right resource at the right price — on both spaces
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space", ["forest", "clay_pit"])
@pytest.mark.parametrize("res,price", [
    ("wood", 1), ("clay", 1), ("reed", 1), ("stone", 2),
])
def test_variant_buys_resource_at_price(space, res, price):
    s, ap = _at_space(space, food=3)
    before = s.players[ap].resources
    s = step(s, FireTrigger(card_id="forest_trader", variant=res))
    after = s.players[ap].resources
    assert after.food == before.food - price
    assert getattr(after, res) == getattr(before, res) + 1
    # Only the food and the bought resource moved.
    for other in ("wood", "clay", "reed", "stone", "grain", "veg"):
        if other != res:
            assert getattr(after, other) == getattr(before, other)


@pytest.mark.parametrize("space,acc_res", [("forest", "wood"), ("clay_pit", "clay")])
def test_purchase_then_space_still_pays_accumulated_goods(space, acc_res):
    # Fire (buy 1 stone), then Proceed takes the accumulated goods and Stop pops.
    s = _owned_state(food=2)
    accumulated = getattr(get_space(s.board, space).accumulated, acc_res)
    assert accumulated > 0
    s = step(s, PlaceWorker(space=space))
    before = s.players[0].resources
    s = step(s, FireTrigger(card_id="forest_trader", variant="stone"))
    s = step(s, Proceed())    # the space's own effect: take the accumulated goods
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())
    assert not s.pending_stack
    after = s.players[0].resources
    assert after.stone == before.stone + 1
    assert after.food == before.food - 2
    assert getattr(after, acc_res) == getattr(before, acc_res) + accumulated


# ---------------------------------------------------------------------------
# Once per use of the space
# ---------------------------------------------------------------------------

def test_only_once_per_space_use():
    s, ap = _at_space("forest", food=5)
    s = step(s, FireTrigger(card_id="forest_trader", variant="wood"))
    # Plenty of food left, but the host's triggers_resolved blocks a second buy.
    la = legal_actions(s)
    assert not any(isinstance(a, FireTrigger) for a in la)
    assert Proceed() in la


# ---------------------------------------------------------------------------
# Decline
# ---------------------------------------------------------------------------

def test_decline_via_proceed_takes_goods_and_keeps_food():
    s = _owned_state(food=4)
    accumulated = get_space(s.board, "forest").accumulated.wood
    s = step(s, PlaceWorker(space="forest"))
    before = s.players[0].resources
    s = step(s, Proceed())   # decline the purchase; Forest still pays out
    s = step(s, Stop())
    assert not s.pending_stack
    after = s.players[0].resources
    assert after.food == before.food          # no food spent
    assert after.wood == before.wood + accumulated
    assert after.stone == before.stone        # nothing bought


# ---------------------------------------------------------------------------
# Not offered elsewhere / hand-only inert
# ---------------------------------------------------------------------------

def test_not_offered_on_other_accumulation_spaces():
    # Reed Bank is neither a wood nor a clay accumulation space; forest_trader
    # doesn't hook it, so it stays on the atomic fast path — no host, no trigger.
    s = _owned_state(food=5)
    s = step(s, PlaceWorker(space="reed_bank"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# Ruling 82 (2026-07-26): each price is payable by raising
# ---------------------------------------------------------------------------

def test_zero_food_with_grain_offers_one_food_goods_and_raise_completes():
    """Boundary pins: at 0 food with 1 grain, each resource is filtered on its
    OWN raise-able price — wood/clay/reed (1 food) ARE offered (the old plain
    food-on-hand gate offered nothing), stone (2 food) is not (max raise is 1).
    Firing wood pushes the raise-only PendingFoodPayment; committing the grain
    bundle completes the buy identically to the on-hand path, and the space's
    own take still lands at Proceed afterwards."""
    from agricola.actions import CommitFoodPayment
    from agricola.pending import PendingFoodPayment
    s = _owned_state(grain=1)                     # 0 food + 1 grain
    accumulated = get_space(s.board, "forest").accumulated.wood
    s = step(s, PlaceWorker(space="forest"))
    la = legal_actions(s)
    for res in ("wood", "clay", "reed"):
        assert FireTrigger(card_id="forest_trader", variant=res) in la
    assert FireTrigger(card_id="forest_trader", variant="stone") not in la
    s = step(s, FireTrigger(card_id="forest_trader", variant="wood"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment) and top.food_needed == 1
    bundles = [a for a in legal_actions(s) if isinstance(a, CommitFoodPayment)]
    assert bundles == [CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0)]
    s = step(s, bundles[0])
    r = s.players[0].resources
    assert r.wood == 1                            # the bought wood (pre-take)
    assert r.food == 0                            # raised 1, debited 1
    assert r.grain == 0                           # the grain was the fuel
    s = step(s, Proceed())                        # the space's own take
    s = step(s, Stop())
    assert not s.pending_stack
    assert s.players[0].resources.wood == 1 + accumulated


def test_food_on_hand_stays_direct():
    """With the price on hand the buy never detours through a raise frame."""
    from agricola.pending import PendingFoodPayment
    s, ap = _at_space("forest", food=2)
    s = step(s, FireTrigger(card_id="forest_trader", variant="stone"))
    assert not any(isinstance(f, PendingFoodPayment) for f in s.pending_stack)
    r = s.players[ap].resources
    assert r.food == 0 and r.stone == 1


def test_hand_only_card_is_inert():
    # In hand (not played): no hosting, no trigger, Forest resolves atomically.
    s, _env = setup_env(0)
    s = fast_replace(s, current_player=0)
    p = fast_replace(s.players[0],
                     hand_occupations=s.players[0].hand_occupations
                     | frozenset({"forest_trader"}))
    s = fast_replace(s, players=(p, s.players[1]))
    s = _set_resources(s, 0, food=5)
    assert not should_host_space(s, "forest", 0)
    food0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.players[0].resources.food == food0
