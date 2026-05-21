"""Engine performance profiler — item C in POSSIBLE_NEXT_STEPS.md.

Runs three workloads under cProfile + manual wall-clock timing:

- Workload A: random_agent_play from setup() across seeds 0-9. End-to-end
  baseline; mirrors the existing random-agent regression sweep.

- Workload B: random_agent_play from a *wealthy* prefab state (the
  `early_round_3_wealthy` factory). Exercises action spaces that random
  play from a fresh setup rarely reaches — Major Improvement, Farm
  Expansion's room-build path, the renovation spaces, Fencing.

- Workload C: micro-benchmark loop over the 9 prefab states. Calls
  legal_actions(state) and step(state, action) repeatedly on each state.
  Isolates per-call cost from game-walk overhead and surfaces per-state
  variance. The union of states satisfies "every action space legal in at
  least one state" (except `lessons`, permanently illegal in Family).

Output: per-workload wall-clock summary, plus cProfile top-N tables sorted
by cumulative and total time, written to stdout. The intent is observation
only — no engine changes are made.

Usage:
    python scripts/profile_engine.py            # all workloads
    python scripts/profile_engine.py --workload A
    python scripts/profile_engine.py --workload C --topn 30
"""
from __future__ import annotations

import argparse
import cProfile
import pstats
import sys
import time
from io import StringIO
from pathlib import Path

# Make `agricola`, `tests`, and `scripts` importable when run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from agricola.engine import step
from agricola.legality import legal_actions
from agricola.setup import setup

from tests.test_utils import filter_implemented, random_agent_play

from scripts.profile_states import EARLY, LATE, MID, STATES


# ---------------------------------------------------------------------------
# Wall-clock summary helper
# ---------------------------------------------------------------------------

def _fmt_us(seconds: float) -> str:
    """Format a duration in seconds as us/ms/s with reasonable precision."""
    if seconds < 1e-3:
        return f"{seconds * 1e6:.2f} us"
    if seconds < 1.0:
        return f"{seconds * 1e3:.2f} ms"
    return f"{seconds:.3f} s"


# ---------------------------------------------------------------------------
# Workload A: random_agent_play from setup() across 10 seeds
# ---------------------------------------------------------------------------

def workload_a():
    seeds = list(range(10))
    total_actions = 0
    t0 = time.perf_counter()
    for seed in seeds:
        s = setup(seed=seed)
        _terminal, trace = random_agent_play(s, seed=seed)
        total_actions += len(trace)
    elapsed = time.perf_counter() - t0
    return {
        "name": "Workload A — random_agent_play from setup() over 10 seeds",
        "elapsed": elapsed,
        "n_games": len(seeds),
        "n_actions": total_actions,
        "per_action": elapsed / total_actions if total_actions else 0.0,
        "per_game": elapsed / len(seeds),
    }


# ---------------------------------------------------------------------------
# Workload B: random_agent_play from a wealthy prefab state
# ---------------------------------------------------------------------------

def workload_b():
    seeds = list(range(10))
    total_actions = 0
    t0 = time.perf_counter()
    for seed in seeds:
        # Re-build the wealthy state per seed so each run is independent.
        s = STATES["early_round_3_wealthy"]()
        _terminal, trace = random_agent_play(s, seed=seed)
        total_actions += len(trace)
    elapsed = time.perf_counter() - t0
    return {
        "name": "Workload B — random_agent_play from early_round_3_wealthy over 10 seeds",
        "elapsed": elapsed,
        "n_games": len(seeds),
        "n_actions": total_actions,
        "per_action": elapsed / total_actions if total_actions else 0.0,
        "per_game": elapsed / len(seeds),
    }


# ---------------------------------------------------------------------------
# Workload C: micro-benchmark legal_actions and step on 9 prefab states
# ---------------------------------------------------------------------------

def workload_c(iterations_per_state: int = 1000):
    """For each prefab state, call legal_actions() N times and step() N times
    with a randomly-chosen implemented action. Per-state breakdown surfaces
    cost variance across game positions.

    step() is called with a fresh random action each iteration so we don't
    keep stepping forward through the game (that would just degenerate into
    Workload A). Each step is one application from the same source state.
    """
    rng = np.random.default_rng(42)
    per_state = {}
    t_total = time.perf_counter()

    for name, factory in STATES.items():
        state = factory()
        legal = legal_actions(state)
        impl = filter_implemented(legal)
        if not impl:
            per_state[name] = {
                "legal_actions_total": 0.0,
                "step_total": 0.0,
                "n_legal_actions": len(legal),
                "n_legal_implemented": 0,
                "skipped": True,
            }
            continue

        # legal_actions timing
        t0 = time.perf_counter()
        for _ in range(iterations_per_state):
            legal_actions(state)
        la_elapsed = time.perf_counter() - t0

        # step timing — each iteration applies one random implemented action
        # from the source state, then throws the result away.
        choices = [impl[int(rng.integers(len(impl)))] for _ in range(iterations_per_state)]
        t0 = time.perf_counter()
        for action in choices:
            step(state, action)
        st_elapsed = time.perf_counter() - t0

        per_state[name] = {
            "legal_actions_total": la_elapsed,
            "step_total": st_elapsed,
            "n_legal_actions": len(legal),
            "n_legal_implemented": len(impl),
            "legal_actions_per_call": la_elapsed / iterations_per_state,
            "step_per_call": st_elapsed / iterations_per_state,
            "skipped": False,
        }

    elapsed = time.perf_counter() - t_total
    return {
        "name": f"Workload C — per-state micro-benchmark ({iterations_per_state} iters per state)",
        "elapsed": elapsed,
        "iterations_per_state": iterations_per_state,
        "per_state": per_state,
    }


# ---------------------------------------------------------------------------
# cProfile wrapper
# ---------------------------------------------------------------------------

def profile(callable_, topn: int = 25):
    """Run `callable_` under cProfile and return (result, profile_summaries).

    The summaries are two strings: top-N functions sorted by cumulative time,
    then by total (self) time.
    """
    pr = cProfile.Profile()
    pr.enable()
    result = callable_()
    pr.disable()

    out_cumulative = StringIO()
    pstats.Stats(pr, stream=out_cumulative).sort_stats("cumulative").print_stats(topn)

    out_tottime = StringIO()
    pstats.Stats(pr, stream=out_tottime).sort_stats("tottime").print_stats(topn)

    return result, out_cumulative.getvalue(), out_tottime.getvalue()


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_workload_summary(summary: dict):
    print("=" * 78)
    print(summary["name"])
    print("=" * 78)
    if "per_state" in summary:
        # Workload C
        print(f"  Total wall-clock: {_fmt_us(summary['elapsed'])} "
              f"({summary['iterations_per_state']} iters per state)\n")
        # Header
        print(f"  {'state':<34} {'#legal':>8} {'#impl':>7} "
              f"{'legal_actions/call':>20} {'step/call':>14}")
        print(f"  {'-' * 34} {'-' * 8} {'-' * 7} "
              f"{'-' * 20} {'-' * 14}")
        for name, stats in summary["per_state"].items():
            if stats.get("skipped"):
                print(f"  {name:<34} {stats['n_legal_actions']:>8} "
                      f"{stats['n_legal_implemented']:>7}  (skipped)")
                continue
            print(f"  {name:<34} {stats['n_legal_actions']:>8} "
                  f"{stats['n_legal_implemented']:>7} "
                  f"{_fmt_us(stats['legal_actions_per_call']):>20} "
                  f"{_fmt_us(stats['step_per_call']):>14}")
        print()
    else:
        # Workload A or B
        print(f"  Total wall-clock: {_fmt_us(summary['elapsed'])}")
        print(f"  Games:            {summary['n_games']}")
        print(f"  Total actions:    {summary['n_actions']}")
        print(f"  Per game:         {_fmt_us(summary['per_game'])}")
        print(f"  Per action:       {_fmt_us(summary['per_action'])}")
        print()


def print_profile_block(label: str, profile_text: str):
    print(f"--- {label} ---")
    print(profile_text)


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

WORKLOADS = {
    "A": ("Workload A: random play from setup()", workload_a),
    "B": ("Workload B: random play from wealthy prefab", workload_b),
    "C": ("Workload C: micro-benchmark on 9 prefab states", workload_c),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workload", choices=list(WORKLOADS.keys()) + ["all"],
                        default="all", help="Which workload to run (default: all).")
    parser.add_argument("--topn", type=int, default=25,
                        help="Top N functions in cProfile output (default: 25).")
    parser.add_argument("--no-profile", action="store_true",
                        help="Skip cProfile; only do wall-clock timing.")
    args = parser.parse_args()

    chosen = ["A", "B", "C"] if args.workload == "all" else [args.workload]
    print(f"\n>>> Running workloads: {chosen}\n")

    for key in chosen:
        label, fn = WORKLOADS[key]
        if args.no_profile:
            summary = fn()
            print_workload_summary(summary)
        else:
            summary, prof_cum, prof_tot = profile(fn, topn=args.topn)
            print_workload_summary(summary)
            print_profile_block(f"{label} — top {args.topn} by cumulative time", prof_cum)
            print_profile_block(f"{label} — top {args.topn} by total (self) time", prof_tot)
            print()


if __name__ == "__main__":
    main()
