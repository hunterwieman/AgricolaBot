"""Runtime toggles for the frontier / accommodation optimizations.

See FRONTIER_OPT_DESIGN.md. A single cumulative knob covers the three pareto
levels; the fencing-scan cache is an independent boolean (a different subsystem).
This module imports nothing from `agricola`, so `helpers.py` / `legality.py`
can import it without cycles.

  PARETO_OPT_LEVEL  (cumulative; the §3 table has the animal-vs-feeding specifics)
    0 = baseline (original code — byte-identical; set this to reproduce
        pre-optimization results exactly)
    1 = + algorithmic fast paths, no caching (max-corner + rate-descending
        food_payment) and a canonical sort of the optimized output
    2 = + projection cache (animals: exact farm+caps; feeding: clipped outer)
    3 = + coarse layer (animals: Phi farm-shape; feeding: inner food_payment)

  FENCE_SCAN_CACHE  independent of the pareto level (legality subsystem)

Defaults are ON — these caches exist to speed up the engine and are used by
default. FENCE_SCAN_CACHE is result-IDENTICAL to the baseline (it memoizes a
pure function — same output, same order). PARETO_OPT_LEVEL >= 1 is set-identical
but may REORDER frontiers, so RNG-dependent consumers (MCTS macro / feed
sampling) produce a different — fully reproducible — realization than level 0.
Set PARETO_OPT_LEVEL = 0 only when you need byte-identical-to-original output.
"""
PARETO_OPT_LEVEL: int = 3

FENCE_SCAN_CACHE: bool = True
