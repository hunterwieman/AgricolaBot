"""Cross-level equivalence for the frontier/accommodation optimizations.

The toggle structure is the test oracle (FRONTIER_OPT_DESIGN.md §8.1):
Level 0 is today's code untouched; the optimized levels (1-3) must be

  * set-identical to Level 0 (same frontier set + food/begging values), and
  * identical to one another as ordered lists (they all canonically sort).

This single parametrized comparison over a corpus of states + arg combos
validates every optimization level at once. A new optimization that breaks
equivalence fails here immediately.
"""
import pytest

from agricola import helpers, opt_config
from agricola.resources import Animals
from agricola.setup import setup

from scripts.profile_states import STATES

LEVELS = [0, 1, 2, 3]


def _states():
    """Corpus: the 9 prefab states + a few fresh setups. (name, GameState)."""
    out = [(name, factory()) for name, factory in STATES.items()]
    for seed in (0, 1, 2):
        out.append((f"setup_seed{seed}", setup(seed)))
    return out


# ---- normalizers: turn each helper's result into a hashable canonical form ----

def _norm_animal(result):
    """[(Animals, food)] -> sorted list of ((s,b,c), food)."""
    return sorted(((a.sheep, a.boar, a.cattle), f) for (a, f) in result)


def _norm_food_payment(result):
    """[5-tuple] -> sorted list."""
    return sorted(result)


def _norm_harvest_feed(result):
    """[(5-tuple, begging)] -> sorted list."""
    return sorted((tuple(rem), beg) for (rem, beg) in result)


def _run_at_level(level, fn):
    opt_config.PARETO_OPT_LEVEL = level
    return fn()


def _assert_equiv(make_call, normalize):
    """Run `make_call` at every level, normalize, and assert:
    levels 1-3 identical as ordered lists; all levels equal as sets vs level 0.
    """
    norms = {lvl: normalize(_run_at_level(lvl, make_call)) for lvl in LEVELS}

    # Levels 1-3: identical ordered lists (canonical sort).
    for lvl in (2, 3):
        assert norms[lvl] == norms[1], (
            f"level {lvl} differs from level 1 (ordered):\n"
            f"  L1={norms[1]}\n  L{lvl}={norms[lvl]}"
        )
    # Level 0 vs the rest: set-identical (level 0 keeps legacy order).
    assert set(norms[0]) == set(norms[1]), (
        f"level 0 set differs from optimized:\n"
        f"  L0={sorted(norms[0])}\n  L1={sorted(norms[1])}"
    )


# ----------------------------------- tests -----------------------------------

GAINED = [Animals(sheep=2, boar=1), Animals(cattle=3), Animals(sheep=4, boar=4, cattle=4)]
FOOD_OWED = [0, 2, 4]


@pytest.mark.parametrize("gained", GAINED)
def test_pareto_frontier_equiv(gained):
    for name, state in _states():
        for pidx, ps in enumerate(state.players):
            rates3 = helpers.cooking_rates(state, pidx)[:3]
            _assert_equiv(
                lambda ps=ps, r=rates3, g=gained: helpers.pareto_frontier(ps, g, r),
                _norm_animal,
            )


def test_breeding_frontier_equiv():
    for name, state in _states():
        for pidx, ps in enumerate(state.players):
            rates3 = helpers.cooking_rates(state, pidx)[:3]
            _assert_equiv(
                lambda ps=ps, r=rates3: helpers.breeding_frontier(ps, r),
                _norm_animal,
            )


@pytest.mark.parametrize("food_owed", FOOD_OWED)
def test_food_payment_frontier_equiv(food_owed):
    for name, state in _states():
        for pidx, ps in enumerate(state.players):
            rates4 = helpers.cooking_rates(state, pidx)
            _assert_equiv(
                lambda ps=ps, r=rates4, fo=food_owed: helpers.food_payment_frontier(ps, fo, r),
                _norm_food_payment,
            )


@pytest.mark.parametrize("food_owed", FOOD_OWED)
def test_harvest_feed_frontier_equiv(food_owed):
    for name, state in _states():
        for pidx, ps in enumerate(state.players):
            rates4 = helpers.cooking_rates(state, pidx)
            _assert_equiv(
                lambda ps=ps, r=rates4, fo=food_owed: helpers.harvest_feed_frontier(ps, fo, r),
                _norm_harvest_feed,
            )


def test_default_level_is_zero():
    """The default must stay baseline so current scripts are unchanged."""
    assert opt_config.PARETO_OPT_LEVEL == 0
    assert opt_config.FENCE_SCAN_CACHE is False
