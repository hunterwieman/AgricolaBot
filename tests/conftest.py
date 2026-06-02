"""Shared pytest fixtures.

The autouse fixture below keeps the frontier-optimization toggles
(`agricola.opt_config`) from leaking across tests: it snapshots the flags,
restores them after each test, and clears any frontier caches that exist. Most
tests run at the default level (0 = baseline) and never touch the flags; the
fixture is a cheap safety net for the cross-level tests that flip them
(see tests/test_frontier_opt.py and FRONTIER_OPT_DESIGN.md §8.1).
"""
import pytest

from agricola import helpers, opt_config

# lru_cache-decorated frontier caches added in later phases; clearing is a no-op
# until they exist (getattr guard).
_CACHE_NAMES = (
    "_animal_points_cached",
    "_phi_cached",
    "_harvest_feed_cached",
    "_food_payment_cached",
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
        for name in _CACHE_NAMES:
            fn = getattr(helpers, name, None)
            if fn is not None and hasattr(fn, "cache_clear"):
                fn.cache_clear()
