"""Runtime toggles for the frontier / accommodation optimizations.

See FRONTIER_OPT_DESIGN.md. A single cumulative knob covers the three pareto
levels; the fencing-scan cache is an independent boolean (a different subsystem).
This module imports nothing from `agricola`, so `helpers.py` / `legality.py`
can import it without cycles.

  PARETO_OPT_LEVEL  (cumulative; the §3 table has the animal-vs-feeding specifics)
    0 = baseline (today's code — untouched; the default never moves)
    1 = + algorithmic fast paths, no caching (max-corner + rate-descending
        food_payment) and a canonical sort of the optimized output
    2 = + projection cache (animals: exact farm+caps; feeding: clipped outer)
    3 = + coarse layer (animals: Phi farm-shape; feeding: inner food_payment)

  FENCE_SCAN_CACHE  independent of the pareto level (legality subsystem)
"""
PARETO_OPT_LEVEL: int = 0

FENCE_SCAN_CACHE: bool = False
