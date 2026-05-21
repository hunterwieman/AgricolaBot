"""Direct microbenchmark: dataclasses.replace vs fast_replace.

cProfile's per-function self-time accounting can be misleading when one
implementation has more nested Python-level callees (genexprs, dict
lookups) than another. This script uses timeit for an apples-to-apples
per-call measurement.
"""
from __future__ import annotations

import dataclasses
import sys
import timeit
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import get_space


def bench(label, stmt, setup_stmt, n=200_000):
    t = timeit.timeit(stmt, setup=setup_stmt, number=n, globals=globals())
    per_call_us = (t / n) * 1e6
    print(f"  {label:<42} {per_call_us:7.3f} us/call  ({n:>7} iters, {t:.3f}s total)")


def main():
    state = setup(seed=0)
    p = state.players[0]
    r = p.resources
    sp = get_space(state.board, "forest")
    fy = p.farmyard

    print("--- Resources (7 fields, single-field update) ---")
    bench("dataclasses.replace(r, wood=10)",
          "dataclasses.replace(r, wood=10)",
          "from agricola.resources import Resources; r = Resources(wood=3)")
    bench("fast_replace(r, wood=10)",
          "fast_replace(r, wood=10)",
          "from agricola.replace import fast_replace; "
          "from agricola.resources import Resources; r = Resources(wood=3)")

    print("\n--- ActionSpaceState (4 fields, single-field update) ---")
    bench("dataclasses.replace(sp, workers=(1,0))",
          "dataclasses.replace(sp, workers=(1,0))",
          "import dataclasses; from agricola.state import ActionSpaceState; "
          "sp = ActionSpaceState(workers=(0,0))")
    bench("fast_replace(sp, workers=(1,0))",
          "fast_replace(sp, workers=(1,0))",
          "from agricola.replace import fast_replace; "
          "from agricola.state import ActionSpaceState; "
          "sp = ActionSpaceState(workers=(0,0))")

    print("\n--- PlayerState (12 fields, single-field update) ---")
    bench("dataclasses.replace(p, people_home=1)",
          "dataclasses.replace(p, people_home=1)",
          "from agricola.setup import setup; p = setup(0).players[0]")
    bench("fast_replace(p, people_home=1)",
          "fast_replace(p, people_home=1)",
          "from agricola.replace import fast_replace; "
          "from agricola.setup import setup; p = setup(0).players[0]")

    print("\n--- GameState (7 fields, single-field update) ---")
    bench("dataclasses.replace(s, current_player=0)",
          "dataclasses.replace(s, current_player=0)",
          "from agricola.setup import setup; s = setup(0)")
    bench("fast_replace(s, current_player=0)",
          "fast_replace(s, current_player=0)",
          "from agricola.replace import fast_replace; "
          "from agricola.setup import setup; s = setup(0)")

    print("\n--- GameState (multi-field, 2 changes) ---")
    bench("dataclasses.replace(s, current_player=0, round_number=2)",
          "dataclasses.replace(s, current_player=0, round_number=2)",
          "from agricola.setup import setup; s = setup(0)")
    bench("fast_replace(s, current_player=0, round_number=2)",
          "fast_replace(s, current_player=0, round_number=2)",
          "from agricola.replace import fast_replace; "
          "from agricola.setup import setup; s = setup(0)")


if __name__ == "__main__":
    main()
