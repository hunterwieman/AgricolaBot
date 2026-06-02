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
