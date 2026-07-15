"""Tests for Brushwood Collector (occupation, B145).

Card text: "Each time you renovate or build a room, you can replace the required 1 or 2
reed with a total of 1 wood."

An optional conversion on renovate (1 reed) and build_room (2 reed) that swaps the whole
reed requirement for a single wood. Verified at the `effective_payments` chokepoint: the
frontier holds BOTH the unchanged printed cost AND the reed→wood substitution (it is
optional), and the substitution replaces ALL the reed with exactly 1 wood.
"""
import agricola.cards.brushwood_collector  # noqa: F401  (registers the conversions)

from agricola.constants import HouseMaterial
from agricola.cost import CostCtx
from agricola.cards.cost_mods import CONVERSIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.legality import effective_payments
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup


def _state_owning(*card_ids):
    state = setup(0)
    p0 = fast_replace(state.players[0], occupations=frozenset(card_ids),
                      resources=Resources(wood=20, clay=20, reed=20, stone=20))
    return fast_replace(state, players=(p0, state.players[1]))


def _set(frontier):
    return set(frontier)


def test_registration():
    assert "brushwood_collector" in OCCUPATIONS
    for kind in ("renovate", "build_room"):
        assert any(cid == "brushwood_collector"
                   for _o, cid, _fn, _rec in CONVERSIONS.get(kind, ()))


def test_room_two_reed_replaced_by_one_wood():
    # Stone room: 5 stone + 2 reed. Substitution: the 2 reed -> a total of 1 wood.
    state = _state_owning("brushwood_collector")
    ctx = CostCtx("build_room", Resources(stone=5, reed=2))
    assert _set(effective_payments(state, 0, ctx)) == {
        Resources(stone=5, reed=2),                 # unchanged (optional)
        Resources(stone=5, wood=1),                 # 2 reed -> 1 wood
    }


def test_renovate_one_reed_replaced_by_one_wood():
    # Renovate to stone: 3 stone + 1 reed. Substitution: the 1 reed -> 1 wood.
    state = _state_owning("brushwood_collector")
    ctx = CostCtx("renovate", Resources(stone=3, reed=1), to_material=HouseMaterial.STONE)
    assert _set(effective_payments(state, 0, ctx)) == {
        Resources(stone=3, reed=1),                 # unchanged (optional)
        Resources(stone=3, wood=1),                 # 1 reed -> 1 wood
    }


def test_no_substitution_when_no_reed():
    # A reedless build offers no substitution.
    state = _state_owning("brushwood_collector")
    ctx = CostCtx("build_room", Resources(stone=5))
    assert _set(effective_payments(state, 0, ctx)) == {Resources(stone=5)}


def test_not_applied_without_the_card():
    state = _state_owning()   # nobody owns Brushwood Collector
    ctx = CostCtx("build_room", Resources(stone=5, reed=2))
    assert _set(effective_payments(state, 0, ctx)) == {Resources(stone=5, reed=2)}
