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


def test_default_opt_settings_are_on():
    """The caches default ON — they exist to speed up the engine and are used
    by default (changed 2026-06-05). FENCE_SCAN_CACHE is result-identical;
    PARETO_OPT_LEVEL=3 is reproducible-but-reordered vs level 0. Set level 0
    explicitly for byte-identical-to-original output.
    """
    assert opt_config.PARETO_OPT_LEVEL == 3
    assert opt_config.FENCE_SCAN_CACHE is True


# ----------------------- fence-scan cache (independent) ----------------------

def _trace_actions(seed):
    """Action-type trace of a full random game (exercises fencing naturally)."""
    from tests.test_utils import random_agent_play
    _, trace = random_agent_play(setup(seed), seed)
    return [(type(a).__name__, repr(a)) for a in trace]


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_fence_scan_cache_transparent(seed):
    """FENCE_SCAN_CACHE on/off must produce byte-identical games (same seed):
    the cache only fronts the fence-universe scan and must change nothing.
    Random games build fences, so this exercises both the placement predicate
    and the build-fences enumerator end-to-end.
    """
    opt_config.FENCE_SCAN_CACHE = False
    trace_off = _trace_actions(seed)
    opt_config.FENCE_SCAN_CACHE = True
    trace_on = _trace_actions(seed)
    assert trace_off == trace_on


def test_any_legal_pasture_commit_parity():
    """Direct parity on the placement predicate over the prefab corpus."""
    from agricola import legality
    for name, state in _states():
        for ps in state.players:
            opt_config.FENCE_SCAN_CACHE = False
            off = legality._any_legal_pasture_commit(state, ps)
            opt_config.FENCE_SCAN_CACHE = True
            on = legality._any_legal_pasture_commit(state, ps)
            assert off == on, f"{name}: predicate differs (off={off}, on={on})"
