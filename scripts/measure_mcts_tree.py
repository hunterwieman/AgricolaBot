"""Single-game MCTS tree-size instrumentation.

Plays one full MCTS-vs-hubris_v3 game; wraps `MCTSAgent.__call__` to log the
transposition-table size at three points per call (before re-root, after
re-root, after sims) plus per-call wall time and the chosen action's type.

Output: a CSV-ish table on stdout. Useful for deciding whether to add a
transposition cap.

Usage:
    python -O scripts/measure_mcts_tree.py [--sims 500] [--seed 0] [--v3-config PATH]
"""
from __future__ import annotations

import argparse
import gc
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np


def _get_rss_kb() -> int:
    """Process resident set size in KB. Uses `ps` for cross-platform
    portability (macOS / Linux). Slightly slower than psutil but no
    extra dependency."""
    try:
        out = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(os.getpid())],
            text=True,
        )
        return int(out.strip())
    except Exception:
        return -1

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents import (
    CONFIG_V3_T1,
    DEFAULT_CONFIG_V3,
    HeuristicConfigV3,
    HubrisHeuristicV3,
    MCTSAgent,
    MCTSSearch,
    make_strict_restricted_legal_actions,
)
from agricola.agents.base import play_game
from agricola.actions import PlaceWorker
from agricola.scoring import score
from agricola.setup import setup, setup_env


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sims", type=int, default=500)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--v3-config", type=str,
        default=str(ROOT / "tuned_configs" / "v3_best.json"),
        help="V3 config path (or 'default_v3' / 'v3_t1').",
    )
    ap.add_argument(
        "--mcts-as-p1", action="store_true",
        help="Place MCTS at P1 (default P0).",
    )
    args = ap.parse_args()

    # Resolve V3 config.
    if args.v3_config in ("default_v3", "default"):
        cfg = DEFAULT_CONFIG_V3
    elif args.v3_config == "v3_t1":
        cfg = CONFIG_V3_T1
    else:
        with open(args.v3_config) as f:
            cfg = HeuristicConfigV3(**json.load(f)["best_config"])

    search = MCTSSearch(
        evaluator_config=cfg,
        n_random_fencing=4,
        rng_seed=args.seed,
    )
    mcts = MCTSAgent(
        search,
        sims_per_move=args.sims,
        c_uct=1.4,
        fpu_offset=0.0,
        action_selection_temperature=0.2,
        rng_seed=args.seed,
    )

    # Strict-restricted heuristic opponent — same wiring as play_mcts_match.
    strict_fn = make_strict_restricted_legal_actions(
        config=cfg, rng=np.random.default_rng(args.seed ^ 0xC0FFEE),
    )
    heur = HubrisHeuristicV3(
        seed=args.seed + 1, temperature=0.0, lookahead="turn",
        config=cfg, legal_actions_fn=strict_fn,
    )

    # `agents` tuple is assigned below after the instrumented wrapper is built.

    # Instrument: wrap the agent object so play_game calls our wrapper
    # (not mcts directly). Instance-level `__call__` doesn't intercept
    # `obj(args)` in Python — it dispatches through `type(obj).__call__` —
    # so we wrap the agent rather than monkey-patching it.
    rows: list[dict] = []
    call_index = [0]

    class _Instrumented:
        def __call__(self, state):
            # Mid-macro? Just pop the queue — no sims, no re-root.
            if mcts._pending_macro_actions:
                return mcts(state)
            call_index[0] += 1
            tt_before = len(search.transpositions)
            existed = state in search.transpositions
            inherited_visits = (
                search.transpositions[state].visits if existed else 0
            )
            t0 = time.perf_counter()

            # Manually replay __call__ logic so we can sample tt size mid-call.
            root = search.find_or_create_node(state)
            search.re_root(root)
            tt_after_reroot = len(search.transpositions)

            for _ in range(mcts.sims_per_move):
                mcts._simulate(root)
            tt_after_sims = len(search.transpositions)

            action = mcts._select_action_with_temperature(root)
            from agricola.agents.mcts import MacroFencingAction
            if isinstance(action, MacroFencingAction):
                sequence = root.macro_sequences[action]
                mcts._pending_macro_actions.extend(sequence[1:])
                engine_action = sequence[0]
            else:
                engine_action = action

            wall = time.perf_counter() - t0

            # Memory + GC tracking. RSS is the process's resident set
            # size in KB; if it grows monotonically without the tree
            # growing, that suggests un-freed memory (Python heap not
            # returning to OS, or reference cycles not collected).
            rss_kb = _get_rss_kb()
            gc_counts = gc.get_count()  # (gen0, gen1, gen2) pending objects

            rows.append({
                "call": call_index[0],
                "round": state.round_number,
                "phase": state.phase.name,
                "tt_before": tt_before,
                "inherited_visits": inherited_visits,
                "tt_after_reroot": tt_after_reroot,
                "tt_after_sims": tt_after_sims,
                "delta_nodes": tt_after_sims - tt_after_reroot,
                "wall_s": wall,
                "action": type(engine_action).__name__,
                "rss_mb": rss_kb / 1024.0 if rss_kb >= 0 else -1,
                "gc_gen0": gc_counts[0],
                "gc_gen1": gc_counts[1],
                "gc_gen2": gc_counts[2],
            })
            return engine_action

    instrumented_mcts = _Instrumented()
    # Replace the agents tuple's MCTS slot with the wrapper.
    if args.mcts_as_p1:
        agents = (heur, instrumented_mcts)
    else:
        agents = (instrumented_mcts, heur)

    print(f"Single-game MCTS tree-size + memory measurement")
    print(f"  sims_per_move={args.sims}, seed={args.seed}, "
          f"mcts_seat={'P1' if args.mcts_as_p1 else 'P0'}")
    print(f"  v3_config={args.v3_config}")
    rss_start = _get_rss_kb()
    print(f"  initial RSS: {rss_start / 1024:.1f} MB")
    print()

    initial, env = setup_env(seed=args.seed)
    t_start = time.perf_counter()
    final, trace = play_game(initial, agents, env.resolve)
    total_wall = time.perf_counter() - t_start

    s0, _ = score(final, 0)
    s1, _ = score(final, 1)
    rss_end = _get_rss_kb()

    print(f"Game complete: P0={s0} P1={s1} margin={s0 - s1:+}  "
          f"wall={total_wall/60:.1f}min  trace_len={len(trace)}")
    print()
    print(f"{'call':>5} {'rnd':>3} {'phase':>15} "
          f"{'tt_before':>10} {'inh_vis':>8} {'after_reroot':>13} "
          f"{'after_sims':>11} {'Δnodes':>7} {'wall':>6} "
          f"{'rss_MB':>8} {'action':>20}")
    print("-" * 130)
    for r in rows:
        print(f"{r['call']:>5} {r['round']:>3} {r['phase']:>15} "
              f"{r['tt_before']:>10} {r['inherited_visits']:>8} "
              f"{r['tt_after_reroot']:>13} {r['tt_after_sims']:>11} "
              f"{r['delta_nodes']:>+7} {r['wall_s']:>6.1f} "
              f"{r['rss_mb']:>8.1f} {r['action']:>20}")

    # Summary stats
    max_tt = max(r["tt_after_sims"] for r in rows)
    final_tt = rows[-1]["tt_after_sims"]
    total_calls = len(rows)
    rss_values = [r["rss_mb"] for r in rows if r["rss_mb"] >= 0]
    max_rss = max(rss_values) if rss_values else -1
    min_rss = min(rss_values) if rss_values else -1
    final_rss = rss_values[-1] if rss_values else -1
    print()
    print("=" * 60)
    print(f"SUMMARY")
    print("=" * 60)
    print(f"  {total_calls} MCTS calls in {total_wall/60:.1f} min wall")
    print(f"  Tree: max {max_tt:,} nodes, final {final_tt:,}")
    print(f"  RSS: start {rss_start/1024:.1f} MB, min {min_rss:.1f} MB, "
          f"max {max_rss:.1f} MB, end {rss_end/1024:.1f} MB")
    print(f"  RSS growth (start→max): {max_rss - rss_start/1024:+.1f} MB")
    print(f"  RSS growth (start→end): {rss_end/1024 - rss_start/1024:+.1f} MB")
    # GC: did gen0 pending objects grow monotonically? That would suggest
    # objects aren't being collected.
    if rows:
        gc_initial = (rows[0]["gc_gen0"], rows[0]["gc_gen1"], rows[0]["gc_gen2"])
        gc_final = (rows[-1]["gc_gen0"], rows[-1]["gc_gen1"], rows[-1]["gc_gen2"])
        print(f"  GC pending counts: initial={gc_initial}, final={gc_final}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
