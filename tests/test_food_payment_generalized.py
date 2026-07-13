"""Seam tests for the GENERALIZED food-payment frontier (rulings 34/37/39,
2026-07-12 — the converter cluster's core; CARD_DEFERRED_PLANS.md):

- `span_converters`: once-per-harvest BINARY building-resource converters
  enumerated as subsets around the cached crop/animal core — the return shape
  becomes ((g, v, s, b, c, wood, clay, reed, stone) remaining, fired ids).
- `animal_floors`: ruling 39's stateless post-breed cooking floor, applied by
  supply clipping + translation (no cache-key change).
- The legacy path (no converters, zero floors) is byte-identical.
"""
import pytest

from agricola import opt_config
from agricola.helpers import food_payment_frontier
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

RATES = (2, 2, 3, 2)   # sheep 2, boar 2, cattle 3, veg 2
JOINERY = ("joinery", (1, 0, 0, 0), 2)
STONE_CARVER = ("stone_carver", (0, 0, 0, 1), 3)


def _player(**kw):
    p = setup(3).players[0]
    res = {k: v for k, v in kw.items() if k in ("wood", "clay", "reed", "stone",
                                                "food", "grain", "veg")}
    ani = {k: v for k, v in kw.items() if k in ("sheep", "boar", "cattle")}
    p = fast_replace(p, resources=Resources(**res))
    if ani:
        p = fast_replace(p, animals=fast_replace(p.animals, **ani))
    return p


def test_legacy_shape_unchanged_without_extensions():
    p = _player(grain=2, wood=5)
    assert food_payment_frontier(p, 1, RATES) == [(1, 0, 0, 0, 0)]
    # Zero floors are the no-op default.
    assert food_payment_frontier(p, 1, RATES, animal_floors=(0, 0, 0)) == [
        (1, 0, 0, 0, 0)]


def test_converters_extend_the_space_and_return_shape():
    p = _player(grain=1, wood=2, stone=1)
    rows = food_payment_frontier(
        p, 2, RATES, span_converters=(JOINERY, STONE_CARVER))
    assert ((1, 0, 0, 0, 0, 1, 0, 0, 1), ("joinery",)) in rows
    assert ((1, 0, 0, 0, 0, 2, 0, 0, 0), ("stone_carver",)) in rows
    # Firing both is dominated by either single fire (same crops, fewer
    # building resources) — never offered.
    assert all(len(fired) <= 1 for _vec, fired in rows)


def test_converter_infeasible_without_input_good():
    p = _player(grain=2, wood=0)
    rows = food_payment_frontier(p, 2, RATES, span_converters=(JOINERY,))
    # Only the crops config survives (joinery unaffordable): grain pays.
    assert rows == [((0, 0, 0, 0, 0, 0, 0, 0, 0), ())]


def test_no_fires_offered_at_zero_owed():
    p = _player(grain=1, wood=2)
    rows = food_payment_frontier(p, 0, RATES, span_converters=(JOINERY,))
    assert rows == [((1, 0, 0, 0, 0, 2, 0, 0, 0), ())]


def test_overshoot_banked_not_a_dim():
    # Stone Carver's 3 food for owe=1: keeps the grain — incomparable with
    # paying the grain (different goods), so BOTH survive; surplus food is
    # never a Pareto dim.
    p = _player(grain=1, stone=1)
    rows = food_payment_frontier(p, 1, RATES, span_converters=(STONE_CARVER,))
    assert ((1, 0, 0, 0, 0, 0, 0, 0, 0), ("stone_carver",)) in rows
    assert ((0, 0, 0, 0, 0, 0, 0, 0, 1), ()) in rows


def test_floor_protects_animals():
    # 3 sheep at floor 3: none cookable — the grain alone can't cover owe 2,
    # so the frontier is EMPTY (the caller's feasibility gate must pre-check).
    p = _player(grain=1, sheep=3)
    assert food_payment_frontier(p, 2, RATES, animal_floors=(3, 3, 3)) == []
    # Unfloored: cooking a sheep pays.
    assert food_payment_frontier(p, 2, RATES) == [(1, 0, 2, 0, 0)]
    # 4 sheep at floor 3: exactly one is cookable.
    p4 = _player(grain=0, sheep=4)
    assert food_payment_frontier(p4, 2, RATES, animal_floors=(3, 3, 3)) == [
        (0, 0, 3, 0, 0)]


def test_floor_below_count_does_not_bind():
    # 2 sheep with floor 3: the floor only protects a type AT OR ABOVE it
    # (ruling 39's shorthand) — both sheep stay cookable.
    p = _player(grain=0, sheep=2)
    assert food_payment_frontier(p, 2, RATES, animal_floors=(3, 3, 3)) == [
        (0, 0, 1, 0, 0)]


def test_floors_and_converters_compose():
    p = _player(grain=0, sheep=3, wood=1)
    rows = food_payment_frontier(
        p, 2, RATES, span_converters=(JOINERY,), animal_floors=(3, 3, 3))
    # The sheep are protected; joinery is the only payment.
    assert rows == [((0, 0, 3, 0, 0, 0, 0, 0, 0), ("joinery",))]


def test_cross_level_equivalence(monkeypatch):
    """The converter wrap + floor translation sit OUTSIDE the level-dispatched
    core, so the generalized frontier must be SET-identical across opt levels
    (the FRONTIER_OPT_DESIGN.md cross-level pattern)."""
    p = _player(grain=2, veg=1, sheep=4, wood=2, stone=1)
    results = {}
    for level in (0, 1):
        monkeypatch.setattr(opt_config, "PARETO_OPT_LEVEL", level)
        results[level] = sorted(food_payment_frontier(
            p, 3, RATES, span_converters=(JOINERY, STONE_CARVER),
            animal_floors=(3, 0, 0)))
    assert results[0] == results[1]
    assert all(vec[2] >= 3 for vec, _f in results[0])    # sheep floor holds
