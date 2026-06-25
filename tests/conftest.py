"""Shared pytest fixtures.

The autouse fixture below keeps the frontier-optimization toggles
(`agricola.opt_config`) from leaking across tests: it snapshots the flags,
restores them after each test, and clears any frontier caches that exist. Most
tests run at the default level (0 = baseline) and never touch the flags; the
fixture is a cheap safety net for the cross-level tests that flip them
(see tests/test_frontier_opt.py and FRONTIER_OPT_DESIGN.md §8.1).
"""
import pytest

from agricola import helpers, legality, opt_config

# lru_cache-decorated caches to clear between tests; the getattr guard makes
# clearing a no-op for any not yet present. Keyed by (module, attr-name).
_CACHES = (
    (helpers, "_animal_points_cached"),
    (helpers, "_phi_cached"),
    (helpers, "_harvest_feed_cached"),
    (helpers, "_food_payment_cached"),
    (legality, "_legal_pasture_commits_cached"),
)


# Longest-running tests, longest first. Under `pytest-xdist -n N` the default
# `load` scheduler dispatches tests to workers in collection order, so a slow
# test collected late gets picked up near the end and strands the other workers
# idle waiting on it. Hoisting these to the front starts the long poles at t=0,
# so the makespan is the single longest test (~121s for the cpp/Python MCTS
# parity check) rather than that plus whenever a worker happened to grab it.
# Matched by node-id substring; a rename silently drops an entry (you lose the
# scheduling win, not correctness), so keep the names in sync with the suite.
_SLOW_FIRST = (
    "test_cpp_mcts_parity_vs_python_mcts",         # ~121s
    "test_cpp_legal_actions_set_matches_python",   # ~11s
    "test_cpp_step_matches_python_byte_for_byte",  # ~11s
    "test_cpp_candidate_encode_matches_python",    # ~10s
    "test_cpp_encode_matches_python",              # ~9s
    "test_cpp_value_matches_python",               # ~8s
)


def pytest_collection_modifyitems(config, items):
    """Reorder slow tests to the front, but only under xdist parallel runs.

    Serial runs (`numprocesses` unset or 0) keep their natural collection order
    — the reorder only matters for worker scheduling. The sort is deterministic
    (static substring map, stable sort), which xdist requires so every worker
    collects an identical order.
    """
    if config.getoption("numprocesses", None) in (None, 0):
        return

    def rank(item):
        for i, name in enumerate(_SLOW_FIRST):
            if name in item.nodeid:
                return i             # known-slow → front, in listed order
        return len(_SLOW_FIRST)      # everything else keeps its relative order

    items.sort(key=rank)


@pytest.fixture(autouse=True)
def _reset_opt_config():
    saved_level = opt_config.PARETO_OPT_LEVEL
    saved_fence = opt_config.FENCE_SCAN_CACHE
    try:
        yield
    finally:
        opt_config.PARETO_OPT_LEVEL = saved_level
        opt_config.FENCE_SCAN_CACHE = saved_fence
        for module, name in _CACHES:
            fn = getattr(module, name, None)
            if fn is not None and hasattr(fn, "cache_clear"):
                fn.cache_clear()
        # The NN inference encoding memo (torch-free; only present once the
        # encoder module is imported). Pure projection cache, but clear it for
        # test isolation + to bound memory across the suite.
        try:
            from agricola.agents.nn.encoder import clear_encoding_cache
            clear_encoding_cache()
        except Exception:
            pass
