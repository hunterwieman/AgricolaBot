"""scripts/nn/run_param_sweep.py

Self-play parameter sweep: N games where P0 and P1 each independently and
uniformly draw (c_uct, prior_mix, temperature) from user-supplied discrete sets.
Games with the same drawn parameter combo are batched into one binary invocation
so the NN is loaded once per unique combo rather than once per game.

Output: a CSV with one row per game:
  game_idx, seed, c_uct_p0, mix_p0, temp_p0, c_uct_p1, mix_p1, temp_p1,
  p0_score, p1_score, winner

Usage:
  python scripts/nn/run_param_sweep.py \\
    --model-dir nn_models/cpp_export_best \\
    --n 1000 --sims 800 --jobs 8 \\
    --c-uct-vals 0.25 0.5 1.0 2.0 4.0 \\
    --prior-mix-vals 0.0 0.025 0.5 0.1 \\
    --temperature-vals 0.0 0.3 \\
    --out sweep_results.csv
"""
from __future__ import annotations

import argparse
import csv
import queue as queuelib
import subprocess
import sys
import time
from collections import defaultdict
from multiprocessing import Manager, Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
BINARY = str(ROOT / "cpp" / "build" / "selfplay")


def _run_group(arg):
    """One binary invocation: plays all game indices with the same param combo.
    Each finished game is pushed onto q as a dict of field values.
    Returns None on success, an error snippet on failure."""
    model_dir, idxs, base_seed, sims, p0_params, p1_params, select_by, q = arg
    c0, m0, t0 = p0_params
    c1, m1, t1 = p1_params
    cmd = [
        BINARY, "--match", "--mcts",
        "--model-dir-p0", model_dir,
        "--model-dir-p1", model_dir,
        "--game-idxs", ",".join(map(str, idxs)),
        "--base-seed", str(base_seed),
        "--sims", str(sims),
        "--c-uct-p0", str(c0), "--c-uct-p1", str(c1),
        "--temperature-p0", str(t0), "--temperature-p1", str(t1),
        "--prior-mix-p0", str(m0), "--prior-mix-p1", str(m1),
    ]
    if select_by == "q":
        cmd += ["--select-by-p0", "q", "--select-by-p1", "q"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    for line in proc.stdout:
        if line.startswith("GAME"):
            f = dict(tok.split("=") for tok in line.split()[1:])
            q.put({
                "seed": int(f["seed"]),
                "p0_score": int(f["p0"]),
                "p1_score": int(f["p1"]),
                "winner": int(f["winner"]),
                "c_uct_p0": c0, "mix_p0": m0, "temp_p0": t0,
                "c_uct_p1": c1, "mix_p1": m1, "temp_p1": t1,
            })
    err = proc.stderr.read()
    return err[-600:] if proc.wait() != 0 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model-dir", default="nn_models/cpp_export_best",
                    help="cpp_export dir (value+policy); used for both seats")
    ap.add_argument("--n", type=int, default=1000,
                    help="total number of games to play")
    ap.add_argument("--sims", type=int, default=800,
                    help="MCTS simulations per move")
    ap.add_argument("--jobs", type=int, default=8,
                    help="parallel worker processes")
    ap.add_argument("--base-seed", type=int, default=0,
                    help="game_seed = base_seed + game_idx")
    ap.add_argument("--rng-seed", type=int, default=42,
                    help="seed for the parameter-draw RNG")
    ap.add_argument("--out", default="sweep_results.csv",
                    help="output CSV path")
    ap.add_argument("--c-uct-vals", nargs="+", type=float,
                    default=[0.25, 0.5, 1.0, 2.0, 4.0])
    ap.add_argument("--prior-mix-vals", nargs="+", type=float,
                    default=[0.0, 0.025, 0.5, 0.1])
    ap.add_argument("--temperature-vals", nargs="+", type=float,
                    default=[0.0, 0.3])
    ap.add_argument("--select-by", choices=["visits", "q"], default="visits",
                    help="played-move selection for BOTH seats (default visits)")
    args = ap.parse_args()

    model_dir = str((ROOT / args.model_dir).resolve())
    if not Path(model_dir).exists():
        print(f"ERROR: model dir not found: {model_dir}", file=sys.stderr)
        return 1

    # Draw parameters for every game using a seeded RNG so the design is
    # reproducible from --rng-seed alone.
    rng = np.random.default_rng(args.rng_seed)
    c_uct_arr  = rng.choice(args.c_uct_vals,        size=(args.n, 2))
    mix_arr    = rng.choice(args.prior_mix_vals,     size=(args.n, 2))
    temp_arr   = rng.choice(args.temperature_vals,   size=(args.n, 2))

    # game_params[i] = (game_idx, p0_tuple, p1_tuple)
    game_params = []
    for i in range(args.n):
        p0 = (float(c_uct_arr[i, 0]), float(mix_arr[i, 0]), float(temp_arr[i, 0]))
        p1 = (float(c_uct_arr[i, 1]), float(mix_arr[i, 1]), float(temp_arr[i, 1]))
        game_params.append((i, p0, p1))

    # Group by (p0_params, p1_params) so each unique combo is one batch.
    groups: dict[tuple, list[int]] = defaultdict(list)
    for i, p0, p1 in game_params:
        groups[(p0, p1)].append(i)

    # Build lookup: game_seed → (p0_params, p1_params) for CSV writing.
    # game_seed = base_seed + game_idx, so seed - base_seed = game_idx.
    seed_to_params: dict[int, tuple] = {}
    for i, p0, p1 in game_params:
        seed_to_params[args.base_seed + i] = (i, p0, p1)

    n_combos = len(groups)
    print(f"[sweep] {args.n} games | {n_combos} unique param combos | "
          f"{args.jobs} workers | sims={args.sims}", flush=True)
    print(f"  c_uct    : {sorted(set(args.c_uct_vals))}", flush=True)
    print(f"  prior_mix: {sorted(set(args.prior_mix_vals))}", flush=True)
    print(f"  temp     : {sorted(set(args.temperature_vals))}", flush=True)
    print(f"  select_by: {args.select_by}", flush=True)
    print(f"  model    : {model_dir}", flush=True)
    print(f"  out      : {args.out}", flush=True)

    mgr = Manager()
    q = mgr.Queue()
    tasks = [
        (model_dir, idxs, args.base_seed, args.sims, p0_params, p1_params,
         args.select_by, q)
        for (p0_params, p1_params), idxs in groups.items()
    ]

    CSV_FIELDS = ["game_idx", "seed",
                  "c_uct_p0", "mix_p0", "temp_p0",
                  "c_uct_p1", "mix_p1", "temp_p1",
                  "p0_score", "p1_score", "winner"]

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    done = 0
    p0w = p1w = draws = 0
    margin_sum = 0.0
    t_start = time.monotonic()
    errors = []

    with open(out_path, "w", newline="") as fout:
        writer = csv.DictWriter(fout, fieldnames=CSV_FIELDS)
        writer.writeheader()

        with Pool(min(args.jobs, len(tasks))) as pool:
            res = pool.map_async(_run_group, tasks)
            while not (res.ready() and q.empty()):
                try:
                    row = q.get(timeout=0.3)
                except queuelib.Empty:
                    continue
                done += 1
                game_idx, p0_params, p1_params = seed_to_params[row["seed"]]
                row["game_idx"] = game_idx
                writer.writerow(row)
                fout.flush()

                p0s, p1s, w = row["p0_score"], row["p1_score"], row["winner"]
                margin_sum += p0s - p1s
                if w == 0:   p0w += 1
                elif w == 1: p1w += 1
                else:        draws += 1

                elapsed = time.monotonic() - t_start
                rate = done / elapsed if elapsed > 0 else 0
                eta = (args.n - done) / rate if rate > 0 else 0
                who = "P0" if w == 0 else ("P1" if w == 1 else "tie")
                print(f"  [{done:>4}/{args.n}] game={game_idx:>4} "
                      f"P0={p0s:>3} P1={p1s:>3} {who}  "
                      f"c0={p0_params[0]:.2f} m0={p0_params[1]:.3f} t0={p0_params[2]:.3f} | "
                      f"c1={p1_params[0]:.2f} m1={p1_params[1]:.3f} t1={p1_params[2]:.3f}  "
                      f"eta={eta/60:.1f}m", flush=True)

            for err in res.get():
                if err:
                    errors.append(err)

    elapsed = time.monotonic() - t_start
    total = p0w + p1w + draws
    print(f"\n[sweep] done: {total} games in {elapsed/60:.1f}m "
          f"({elapsed/total:.1f}s/game)", flush=True)
    print(f"  P0 wins: {p0w} ({100*p0w/total:.1f}%)  "
          f"P1 wins: {p1w} ({100*p1w/total:.1f}%)  draws: {draws}", flush=True)
    print(f"  Avg P0 margin: {margin_sum/total:+.2f} pts", flush=True)
    if errors:
        print(f"  ERRORS ({len(errors)} groups failed):", file=sys.stderr)
        for e in errors:
            print(f"    {e}", file=sys.stderr)
        return 1
    print(f"  Results written to: {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
