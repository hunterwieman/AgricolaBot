"""Hunting Trophy (minor D82): boar cost + cook-for-food, a Farm-Redev free-fence seed, and
a House-Redev "1 building resource of your choice less" improvement discount."""
from __future__ import annotations

from agricola.cards.hunting_trophy import CARD_ID
from agricola.cost import CostCtx
from agricola.legality import effective_payments
from agricola.pending import PendingHouseRedevelopment, push
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import setup

from tests.factories import with_majors, with_resources


def _own(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _food(s, i=0): return s.players[i].resources.food


# ---------------------------------------------------------------------------
# Cost + the on-play cook (the boar's cooking rate as food)
# ---------------------------------------------------------------------------

def test_registration_cost_and_vps():
    from agricola.cards.specs import MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost.animals == Animals(boar=1)   # "Return or Cook 1 Wild Boar"
    assert spec.vps == 1


def test_on_play_cooks_for_two_with_fireplace():
    from agricola.cards.specs import MINORS
    s = with_majors(setup(0), owner_by_idx={0: 0})       # Fireplace (idx 0)
    before = _food(s)
    s2 = MINORS[CARD_ID].on_play(s, 0)
    assert _food(s2) == before + 2                        # boar cooks to 2 food


def test_on_play_cooks_for_three_with_cooking_hearth():
    from agricola.cards.specs import MINORS
    s = with_majors(setup(0), owner_by_idx={2: 0})       # Cooking Hearth (idx 2)
    s2 = MINORS[CARD_ID].on_play(s, 0)
    assert _food(s2) == _food(s) + 3


def test_on_play_no_food_without_cooking_improvement():
    from agricola.cards.specs import MINORS
    s = setup(0)
    s2 = MINORS[CARD_ID].on_play(s, 0)
    assert _food(s2) == _food(s)                          # no cooking improvement -> returned


# ---------------------------------------------------------------------------
# Fence clause: +3 free fences on Farm Redevelopment only
# ---------------------------------------------------------------------------

def test_fence_seed_only_on_farm_redevelopment():
    from agricola.cards.cost_mods import free_fence_budget_for
    s = _own(setup(0), 0, CARD_ID)
    assert free_fence_budget_for(
        s, 0, build_fences_action=True, space_id="farm_redevelopment") == 3
    # Not on the Fencing space, nor on a card grant.
    assert free_fence_budget_for(s, 0, build_fences_action=True, space_id="fencing") == 0
    assert free_fence_budget_for(
        s, 0, build_fences_action=True, space_id="card:field_fences") == 0


def test_fence_seed_zero_without_card():
    from agricola.cards.cost_mods import free_fence_budget_for
    s = setup(0)
    assert free_fence_budget_for(
        s, 0, build_fences_action=True, space_id="farm_redevelopment") == 0


# ---------------------------------------------------------------------------
# House-Redev clause: 1 building resource of choice off an improvement, gated on the stack
# ---------------------------------------------------------------------------

def test_house_redev_discount_gated_on_stack():
    from agricola.cards.hunting_trophy import _house_redev_discount
    cost = Resources(wood=5, reed=2)
    s = setup(0)                                          # empty stack
    assert _house_redev_discount(s, 0, None, cost) == [cost]      # no House Redev frame
    s2 = push(s, PendingHouseRedevelopment(player_idx=0, initiated_by_id="house_redevelopment"))
    out = _house_redev_discount(s2, 0, None, cost)
    assert cost in out                                   # base kept (pruned later by Pareto-min)
    assert cost - Resources(wood=1) in out
    assert cost - Resources(reed=1) in out
    assert cost - Resources(clay=1) not in out          # clay not present in the cost


def test_house_redev_discount_in_effective_payments():
    # Through the chokepoint: an improvement cost of 2 wood + 1 reed, built via House Redev with
    # Hunting Trophy owned, yields the discounted frontier (the undiscounted base is dominated).
    s = _own(setup(0), 0, CARD_ID)
    s = with_resources(s, 0, wood=9, reed=9)
    s = push(s, PendingHouseRedevelopment(player_idx=0, initiated_by_id="house_redevelopment"))
    ctx = CostCtx("play_minor", Resources(wood=2, reed=1))
    payments = set(effective_payments(s, 0, ctx))
    assert payments == {Resources(wood=1, reed=1), Resources(wood=2)}   # -1 wood OR -1 reed


def test_no_house_redev_discount_without_the_frame():
    # Same improvement cost, Hunting Trophy owned, but NOT via House Redevelopment (no frame on
    # the stack) -> no discount; the printed cost is the only payment.
    s = _own(setup(0), 0, CARD_ID)
    s = with_resources(s, 0, wood=9, reed=9)
    ctx = CostCtx("play_minor", Resources(wood=2, reed=1))
    assert effective_payments(s, 0, ctx) == [Resources(wood=2, reed=1)]
