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
                lambda ps=ps, r=rates3, g=gained, s=state: helpers.pareto_frontier(s, ps, g, r),
                _norm_animal,
            )


def test_breeding_frontier_equiv():
    for name, state in _states():
        for pidx, ps in enumerate(state.players):
            rates3 = helpers.cooking_rates(state, pidx)[:3]
            _assert_equiv(
                lambda ps=ps, r=rates3, s=state: helpers.breeding_frontier(s, ps, r),
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


# ---------------------------------------------------------------------------
# Non-canonical pasture capacities (Drinking Trough) — the red-team item.
#
# Every state above has pasture capacities of the form 2*cells*2^stables. Drinking
# Trough adds a flat +2 per pasture, so its capacities (e.g. 4+2=6, 8+2=10) are the
# FIRST non-formula values to flow into the level-2/3 projection caches (_phi_cached /
# _animal_points_cached). Those caches sit below extract_slots and key on its output, and
# _build_phi is defined purely through the same can_accommodate oracle as level 0 — so the
# optimized path should match by construction. This test makes that explicit: it owns
# Drinking Trough on the pasture-bearing prefabs (and loads animals so capacity binds) and
# asserts level 0 == levels 1-3 on the resulting non-canonical capacities.
# ---------------------------------------------------------------------------

def _drinking_trough_states():
    """Pasture-bearing prefab states with player 0 owning Drinking Trough + animals near
    capacity, so its non-canonical (+2) pasture capacities are the binding constraint."""
    import dataclasses

    from agricola.resources import Animals as _An

    out = []
    for name in ("mid_round_6_basic", "mid_round_8_animals"):
        state = STATES[name]()
        p = state.players[0]
        p = dataclasses.replace(
            p,
            minor_improvements=p.minor_improvements | {"drinking_trough"},
            animals=_An(sheep=8, boar=6, cattle=6),   # exceed capacity -> frontier binds
        )
        state = dataclasses.replace(
            state, players=tuple(p if i == 0 else state.players[i] for i in range(2)))
        out.append((f"{name}+drinking_trough", state))
    return out


@pytest.mark.parametrize("gained", GAINED)
def test_pareto_frontier_equiv_non_canonical_caps(gained):
    for name, state in _drinking_trough_states():
        ps = state.players[0]
        rates3 = helpers.cooking_rates(state, 0)[:3]
        # sanity: Drinking Trough is active, so caps are the boosted (non-formula) values
        # and the test isn't vacuous.
        from agricola.cards.capacity_mods import pasture_capacity_bonus
        assert pasture_capacity_bonus(ps) == 2
        _assert_equiv(
            lambda ps=ps, r=rates3, g=gained, s=state: helpers.pareto_frontier(s, ps, g, r),
            _norm_animal,
        )


def test_breeding_frontier_equiv_non_canonical_caps():
    for name, state in _drinking_trough_states():
        ps = state.players[0]
        rates3 = helpers.cooking_rates(state, 0)[:3]
        _assert_equiv(
            lambda ps=ps, r=rates3, s=state: helpers.breeding_frontier(s, ps, r),
            _norm_animal,
        )


# ---------------------------------------------------------------------------
# PER-PASTURE non-canonical capacities (Tinsmith Master, 2026-07-15) — the
# second red-team item. Unlike Drinking Trough's flat +2, Tinsmith adds +1 only
# to STABLE-LESS pastures, so a farm with a mix carries pasture-specific
# capacities (some 2*cells, some 2*cells+1). This exercises §5.4's "key on the
# post-fold values" pattern for a bonus that varies BETWEEN pastures within one
# farm — the caps_tuple the caches key on already reflects it, so the optimized
# levels must match level 0 by construction.
# ---------------------------------------------------------------------------

def _tinsmith_states():
    import dataclasses

    import agricola.cards.tinsmith_master  # noqa: F401  (register the per-pasture fold)
    from agricola.resources import Animals as _An

    out = []
    for name in ("mid_round_6_basic", "mid_round_8_animals"):
        state = STATES[name]()
        p = state.players[0]
        p = dataclasses.replace(
            p,
            occupations=p.occupations | {"tinsmith_master"},
            animals=_An(sheep=8, boar=6, cattle=6),   # exceed capacity -> frontier binds
        )
        state = dataclasses.replace(
            state, players=tuple(p if i == 0 else state.players[i] for i in range(2)))
        out.append((f"{name}+tinsmith_master", state))
    return out


@pytest.mark.parametrize("gained", GAINED)
def test_pareto_frontier_equiv_tinsmith_per_pasture(gained):
    from agricola.cards.capacity_mods import pasture_capacity_per_list
    states = _tinsmith_states()
    # Non-vacuous over the set: at least one farm has a stable-less pasture that
    # actually takes the +1 (mid_round_6_basic's pastures are [stabled, plain] →
    # per [0, 1] — a bonus that VARIES BETWEEN pastures, the red-team point).
    # The all-stabled farm (per all-0) is a fine boundary: Tinsmith owned yet
    # inert must still match level 0.
    assert any(
        any(b > 0 for b in (pasture_capacity_per_list(
            s.players[0], s.players[0].farmyard.pastures) or []))
        for _n, s in states)
    for name, state in states:
        ps = state.players[0]
        assert pasture_capacity_per_list(ps, ps.farmyard.pastures) is not None, name
        rates3 = helpers.cooking_rates(state, 0)[:3]
        _assert_equiv(
            lambda ps=ps, r=rates3, g=gained, s=state: helpers.pareto_frontier(s, ps, g, r),
            _norm_animal,
        )


def test_breeding_frontier_equiv_tinsmith_per_pasture():
    for name, state in _tinsmith_states():
        ps = state.players[0]
        rates3 = helpers.cooking_rates(state, 0)[:3]
        _assert_equiv(
            lambda ps=ps, r=rates3, s=state: helpers.breeding_frontier(s, ps, r),
            _norm_animal,
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
