"""MCTS hyperparameter sweep — run a series of match configurations in
sequence, write per-config logs, and emit a ranked summary.

Default behavior: sweep `c_uct ∈ {0.7, 1.0, 1.4, 2.0, 2.8}`, 80 games per
config, 1000 sims/move, vs hubris_v3 on `tuned_configs/v3_best.json`,
parallelized across `cpu_count()` cores. Total wall ~6-7h on an 8-core box.

Outputs (under `tuned_configs/`):

  <label>_cuct_<value>.log        per-config full log (streamed per-game
                                  lines + final summary)
  <label>_summary.json            aggregate JSON: per-config wins, losses,
                                  margin, per-game margins, elapsed
                                  seconds, all config-level knobs

Stdout: a "starting config N/M" header before each run, a one-line summary
after each, and a final ranked summary table at the end (with 95% CI on
each config's margin computed from the per-game margins).

CLI examples:

    # Default sweep
    python -O scripts/mcts_sweep.py

    # Custom c_uct grid + label
    python -O scripts/mcts_sweep.py \\
        --c-uct 1.0 1.4 2.0 --n 100 --label cuct_focus

    # Smoke test (fast)
    python -O scripts/mcts_sweep.py \\
        --c-uct 1.0 1.4 --sims 50 --n 4 --label smoke
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

# Make `agricola` importable when run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from play_mcts_match import (
    _MatchSpec,
    _load_v3_config,
    play_match_parallel,
)


# Default c_uct grid — brackets the typical-best range.
# 0.7 = √2/2 (strong exploitation), 1.4 = √2 (classical UCB1, our default),
# 2.0 (AlphaGo-era moderate), 2.8 = 2√2 (aggressive exploration).
DEFAULT_C_UCT = [0.7, 1.0, 1.4, 2.0, 2.8]


def _ci_half_width(margins: list[float], conf: float = 0.95) -> float:
    """Half-width of the confidence interval on the mean margin.

    Uses the normal approximation: half-width = z · stddev / √n. For 95%
    confidence z ≈ 1.96. Returns 0 for n < 2 (undefined CI).
    """
    if len(margins) < 2:
        return 0.0
    z = 1.959963984540054  # 95% for normal approx
    if conf != 0.95:
        # Fall back to scipy-free approximation for arbitrary conf
        # (good enough for 0.9 / 0.99 etc.)
        raise NotImplementedError("Only 95% CI is supported")
    stddev = statistics.stdev(margins)
    return z * stddev / math.sqrt(len(margins))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--c-uct", type=float, nargs="+", default=DEFAULT_C_UCT,
        help=f"c_uct values to sweep (space-separated). Default: {DEFAULT_C_UCT}",
    )
    parser.add_argument(
        "--n", type=int, default=80,
        help="Games per config. Default 80. Larger = tighter CI; smaller = "
             "faster sweep.",
    )
    parser.add_argument(
        "--sims", type=int, default=1000,
        help="MCTS sims/move (applied to both MCTS seats in MCTS-vs-MCTS). "
             "Default 1000.",
    )
    parser.add_argument(
        "--opponent", default="hubris_v3",
        choices=("hubris_v3", "random", "mcts"),
        help="Opponent in each match. Default hubris_v3.",
    )
    parser.add_argument(
        "--v3-config", type=str, default=str(ROOT / "tuned_configs" / "v3_best.json"),
        help="Path to JSON V3 config (or 'default_v3' / 'v3_t1'). Default: "
             "tuned_configs/v3_best.json.",
    )
    parser.add_argument(
        "--n-random-fencing", type=int, default=4,
        help="MCTS macro-fencing random count. Default 4.",
    )
    parser.add_argument(
        "--fpu-offset", type=float, default=0.0,
        help="MCTS FPU offset. Default 0.0.",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.2,
        help="MCTS action-selection temperature. Default 0.2.",
    )
    parser.add_argument(
        "--jobs", type=int, default=os.cpu_count() or 1,
        help="Parallel processes per config. Default cpu_count().",
    )
    parser.add_argument(
        "--label", type=str, default="mcts_sweep",
        help="Filename prefix for per-config logs and the summary JSON. "
             "Default 'mcts_sweep'.",
    )
    parser.add_argument(
        "--mcts-as-p1", action="store_true",
        help="Place MCTS at P1 instead of P0. Margin is still reported as "
             "P0-P1, so MCTS-as-P1 should produce NEGATIVE margins when MCTS "
             "wins.",
    )
    args = parser.parse_args()

    # Resolve the V3 config once (shared across all configs).
    config_v3 = _load_v3_config(args.v3_config)
    out_dir = ROOT / "tuned_configs"
    out_dir.mkdir(exist_ok=True)

    # Headers (stdout — the user's screen and the sweep-level log if piped).
    print(f"MCTS sweep: c_uct in {args.c_uct}")
    print(f"  per-config: {args.n} games, {args.sims} sims/move, "
          f"jobs={args.jobs}, opponent={args.opponent}")
    print(f"  v3_config: {args.v3_config}")
    print(f"  fixed knobs: n_random_fencing={args.n_random_fencing}, "
          f"fpu_offset={args.fpu_offset}, temperature={args.temperature}")
    print(f"  output dir: {out_dir}")
    print()

    p0_name, p1_name = ("hubris_v3", "mcts") if args.mcts_as_p1 else ("mcts", args.opponent)
    if args.opponent != "mcts" and args.mcts_as_p1:
        p0_name = args.opponent
        p1_name = "mcts"
    elif args.opponent == "mcts" and args.mcts_as_p1:
        # MCTS-vs-MCTS makes the swap meaningless; warn.
        print("Note: --mcts-as-p1 with --opponent mcts is a no-op (both seats are MCTS).")

    results: list[tuple[float, "MatchResult"]] = []
    sweep_start = time.perf_counter()
    seeds = list(range(args.n))

    for i, cuct in enumerate(args.c_uct, start=1):
        log_path = out_dir / f"{args.label}_cuct_{cuct}.log"
        config_start = time.perf_counter()
        print(f"=== Config {i}/{len(args.c_uct)}: c_uct={cuct} → {log_path} ===",
              flush=True)

        spec = _MatchSpec(
            config_v3=config_v3,
            p0_name=p0_name, p1_name=p1_name,
            sims_per_move=args.sims, opp_sims_per_move=args.sims,
            c_uct=cuct, opp_c_uct=cuct,
            n_random_fencing=args.n_random_fencing,
            fpu_offset=args.fpu_offset,
            temperature=args.temperature,
        )

        # Redirect this config's full output (the streaming per-game lines
        # from play_match_parallel) to the per-config log.
        with open(log_path, "w") as logf:
            with redirect_stdout(logf):
                print(f"MCTS sweep config: c_uct={cuct}")
                print(f"  sims={args.sims} jobs={args.jobs} n={args.n}")
                print(f"  n_random_fencing={args.n_random_fencing} "
                      f"fpu_offset={args.fpu_offset} temperature={args.temperature}")
                print(f"  p0={p0_name} p1={p1_name} v3_config={args.v3_config}")
                print()
                result = play_match_parallel(
                    spec, seeds, jobs=args.jobs, progress=True,
                )
                print()
                print(result.summary_line())
                logf.flush()
        results.append((cuct, result))

        config_elapsed = time.perf_counter() - config_start
        sweep_elapsed = time.perf_counter() - sweep_start
        remaining = (sweep_elapsed / i) * (len(args.c_uct) - i)
        print(f"  done: {result.summary_line()}", flush=True)
        print(f"  config wall: {config_elapsed/60:.1f}m  |  "
              f"sweep elapsed: {sweep_elapsed/60:.1f}m  |  "
              f"ETA remaining: {remaining/60:.1f}m",
              flush=True)
        print(flush=True)

    # Ranked summary table.
    print("=" * 86)
    print(f"SWEEP COMPLETE — ranked by avg margin (best first)")
    print("=" * 86)
    header = f"{'c_uct':>8} {'wins':>5} {'draws':>6} {'losses':>7} " \
             f"{'avg margin':>12} {'95% CI':>14} {'wall (m)':>10}"
    print(header)
    print("-" * 86)
    for cuct, result in sorted(results, key=lambda x: -x[1].avg_margin):
        margins = [g.score_p0 - g.score_p1 for g in result.per_game]
        ci_half = _ci_half_width(margins)
        wall_m = result.elapsed_seconds / 60.0
        print(f"{cuct:>8.2f} {result.p0_wins:>5} {result.draws:>6} "
              f"{result.p1_wins:>7} {result.avg_margin:>+12.2f} "
              f"±{ci_half:>6.2f}        {wall_m:>10.1f}")
    print()

    # JSON summary for downstream tooling / reproducibility.
    summary = {
        "label": args.label,
        "sims": args.sims,
        "n": args.n,
        "jobs": args.jobs,
        "opponent": args.opponent,
        "v3_config": args.v3_config,
        "n_random_fencing": args.n_random_fencing,
        "fpu_offset": args.fpu_offset,
        "temperature": args.temperature,
        "mcts_as_p1": args.mcts_as_p1,
        "p0_name": p0_name,
        "p1_name": p1_name,
        "sweep_wall_seconds": time.perf_counter() - sweep_start,
        "results": [
            {
                "c_uct": cuct,
                "p0_wins": r.p0_wins,
                "p1_wins": r.p1_wins,
                "draws": r.draws,
                "avg_score_p0": r.avg_score_p0,
                "avg_score_p1": r.avg_score_p1,
                "avg_margin": r.avg_margin,
                "ci_half_95": _ci_half_width(
                    [g.score_p0 - g.score_p1 for g in r.per_game]
                ),
                "elapsed_seconds": r.elapsed_seconds,
                "per_game_margins": [g.score_p0 - g.score_p1 for g in r.per_game],
                "per_game_seeds": [g.seed for g in r.per_game],
            }
            for cuct, r in results
        ],
    }
    summary_path = out_dir / f"{args.label}_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Summary JSON: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
