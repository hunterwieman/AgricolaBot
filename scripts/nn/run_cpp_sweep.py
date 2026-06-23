"""Parallel C++ self-sweep: one model vs itself over randomized per-seat search
hyperparameters, to map how strength varies with `c_uct` and `sims`.

Each game, EACH seat independently draws (with replacement) `sims` uniformly from
`--sweep-sims` and `c_uct` uniformly from `[--cuct-lo, --cuct-hi]` — the draws are
done in the C++ binary from a per-game RNG seeded by the game seed (reproducible),
and reported back in each `GAME` line. This driver partitions the game indices
across a worker pool (each worker = one binary process, NN weights loaded once via
the batch `--game-idxs` mode), and STREAMS each finished game back to the parent
via a shared queue — so the log shows a live per-game running tally and the CSV
grows incrementally (you can `tail` either to gauge progress). Mirrors
`scripts/nn/run_cpp_match.py`'s live-queue shape.

Memory-light (C++ hand-rolled inference, no torch).

  python scripts/nn/run_cpp_sweep.py --p0-dir DIR --p1-dir DIR \
      --n 1000 --jobs 6 --temperature 0.0 --out-csv eval_out/sweep.csv
"""
from __future__ import annotations

import argparse
import queue as queuelib
import subprocess
import sys
import time
from collections import defaultdict
from multiprocessing import Manager, Pool
from pathlib import Path

BINARY = "cpp/build/selfplay"


def _slice(n: int, jobs: int) -> list[list[int]]:
    """Contiguous balanced partition of range(n) into `jobs` slices."""
    out, base, rem = [], n // jobs, n % jobs
    start = 0
    for j in range(jobs):
        cnt = base + (1 if j < rem else 0)
        if cnt:
            out.append(list(range(start, start + cnt)))
        start += cnt
    return out


def _run_chunk(arg) -> str | None:
    """Play a slice in one binary process; push each finished game onto `q` as a
    row dict the instant the binary prints it (live streaming). Returns an error
    string (or None) — the parent aggregates from the queue."""
    idxs, args, q = arg
    cmd = [
        BINARY, "--match", "--mcts", "--sweep",
        "--game-idxs", ",".join(map(str, idxs)),
        "--base-seed", str(args.base_seed),
        "--model-dir-p0", args.p0_dir, "--model-dir-p1", args.p1_dir,
        "--temperature", str(args.temperature),
        "--sweep-sims", args.sweep_sims,
        "--cuct-lo", str(args.cuct_lo), "--cuct-hi", str(args.cuct_hi),
    ]
    if args.sweep_alpha:
        cmd += ["--sweep-alpha",
                "--alpha-lo", str(args.alpha_lo), "--alpha-hi", str(args.alpha_hi)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    for line in proc.stdout:  # line-buffered: one GAME line per finished game
        if line.startswith("GAME"):
            f = dict(tok.split("=") for tok in line.split()[1:])
            row = {
                "seed": int(f["seed"]), "p0": int(f["p0"]), "p1": int(f["p1"]),
                "winner": int(f["winner"]),
                "sims0": int(f["sims0"]), "cuct0": float(f["cuct0"]),
                "sims1": int(f["sims1"]), "cuct1": float(f["cuct1"]),
            }
            if "alpha0" in f:
                row["alpha0"] = float(f["alpha0"])
                row["alpha1"] = float(f["alpha1"])
            q.put(row)
    err_txt = proc.stderr.read()
    return err_txt[-500:] if proc.wait() != 0 else None


def _summarize(rows: list[dict], cuct_lo: float, cuct_hi: float) -> None:
    n = len(rows)
    if not n:
        print("no games collected")
        return
    by_sims_w, by_sims_n = defaultdict(int), defaultdict(int)
    nbins = 5
    width = (cuct_hi - cuct_lo) / nbins
    by_cuct_w, by_cuct_n = defaultdict(int), defaultdict(int)
    more_sims_wins = more_sims_games = hi_cuct_wins = hi_cuct_games = 0
    for r in rows:
        won = {0: (1, 0), 1: (0, 1), -1: (0, 0)}[r["winner"]]
        for seat in (0, 1):
            s, c = r[f"sims{seat}"], r[f"cuct{seat}"]
            by_sims_n[s] += 1
            by_sims_w[s] += won[seat]
            b = min(nbins - 1, int((c - cuct_lo) / width)) if width > 0 else 0
            by_cuct_n[b] += 1
            by_cuct_w[b] += won[seat]
        if r["sims0"] != r["sims1"] and r["winner"] != -1:
            more_sims_games += 1
            hi = 0 if r["sims0"] > r["sims1"] else 1
            more_sims_wins += 1 if r["winner"] == hi else 0
        if r["winner"] != -1:
            hi_cuct_games += 1
            hi = 0 if r["cuct0"] > r["cuct1"] else 1
            hi_cuct_wins += 1 if r["winner"] == hi else 0

    print(f"\n=== sweep summary ({n} games, {2*n} seat-games) ===")
    draws = sum(1 for r in rows if r["winner"] == -1)
    print(f"P0 {sum(1 for r in rows if r['winner']==0)} | "
          f"P1 {sum(1 for r in rows if r['winner']==1)} | draws {draws} "
          f"(seat labels symmetric — expect ~50/50)")
    print("\nwin-rate by OWN sims (vs random-param opponent):")
    for s in sorted(by_sims_n):
        print(f"  sims={s:>4}: {by_sims_w[s]/by_sims_n[s]*100:5.1f}%  (n={by_sims_n[s]})")
    print(f"\nwin-rate by OWN c_uct bin (width {width:.2f}):")
    for b in sorted(by_cuct_n):
        lo = cuct_lo + b * width
        print(f"  c_uct[{lo:.2f}-{lo+width:.2f}]: "
              f"{by_cuct_w[b]/by_cuct_n[b]*100:5.1f}%  (n={by_cuct_n[b]})")
    if more_sims_games:
        print(f"\nhead-to-head: seat with MORE sims won {more_sims_wins}/"
              f"{more_sims_games} = {more_sims_wins/more_sims_games*100:.1f}% "
              f"(excl. equal-sims & draws)")
    if hi_cuct_games:
        print(f"head-to-head: seat with HIGHER c_uct won {hi_cuct_wins}/"
              f"{hi_cuct_games} = {hi_cuct_wins/hi_cuct_games*100:.1f}% (excl. draws)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--p0-dir", required=True)
    ap.add_argument("--p1-dir", required=True)
    ap.add_argument("--n", type=int, default=1000)
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--base-seed", type=int, default=0)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--sweep-sims", default="160,320,520,800,1200,1600")
    ap.add_argument("--cuct-lo", type=float, default=0.1)
    ap.add_argument("--cuct-hi", type=float, default=1.0)
    ap.add_argument("--sweep-alpha", action="store_true",
                    help="sweep the MIX-leaf blend weight α per seat per game "
                         "(both seats use leaf-mode mix); composes with fixed "
                         "sims/c_uct via a single --sweep-sims value + equal "
                         "--cuct-lo/--cuct-hi")
    ap.add_argument("--alpha-lo", type=float, default=0.0)
    ap.add_argument("--alpha-hi", type=float, default=1.0)
    ap.add_argument("--out-csv", default="eval_out/sweep.csv")
    args = ap.parse_args()

    slices = _slice(args.n, args.jobs)
    alpha_note = (f", α∈[{args.alpha_lo},{args.alpha_hi}] (mix leaf)"
                  if args.sweep_alpha else "")
    print(f"sweep: {args.n} games over {len(slices)} workers; "
          f"sims∈{{{args.sweep_sims}}}, c_uct∈[{args.cuct_lo},{args.cuct_hi}], "
          f"temp={args.temperature}{alpha_note}", flush=True)

    out = Path(args.out_csv)
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = ["seed", "p0", "p1", "winner", "sims0", "cuct0", "sims1", "cuct1"]
    if args.sweep_alpha:
        cols += ["alpha0", "alpha1"]
    csv = out.open("w")
    csv.write(",".join(cols) + "\n")
    csv.flush()

    mgr = Manager()
    q = mgr.Queue()
    tasks = [(s, args, q) for s in slices]
    rows: list[dict] = []
    p0w = p1w = draws = 0
    margin_sum = 0
    t0 = time.time()
    with Pool(len(slices)) as pool:
        res = pool.map_async(_run_chunk, tasks)
        # Drain the queue while workers run: one streamed line per finished game.
        while not (res.ready() and q.empty()):
            try:
                r = q.get(timeout=0.3)
            except queuelib.Empty:
                continue
            rows.append(r)
            csv.write(",".join(str(r[c]) for c in cols) + "\n")
            csv.flush()  # so a `tail` of the CSV is live too
            done = len(rows)
            margin_sum += r["p0"] - r["p1"]
            if r["winner"] == 0:
                p0w += 1
            elif r["winner"] == 1:
                p1w += 1
            else:
                draws += 1
            rate = done / max(time.time() - t0, 1e-6)
            eta = (args.n - done) / rate if rate else 0
            print(f"  [{done:>4}/{args.n}] seed={r['seed']:>4} "
                  f"P0(s{r['sims0']:>4},c{r['cuct0']:.2f})={r['p0']:>3} "
                  f"P1(s{r['sims1']:>4},c{r['cuct1']:.2f})={r['p1']:>3} "
                  f"-> {'P0' if r['winner']==0 else ('P1' if r['winner']==1 else 'tie')} | "
                  f"tally {p0w}-{draws}-{p1w} | ETA {eta/60:.1f}m", flush=True)
        errs = [e for e in res.get() if e]
    csv.close()
    for e in errs:
        print(f"  worker error: {e}", file=sys.stderr)
    print(f"\nwrote {len(rows)} rows -> {out}")
    _summarize(rows, args.cuct_lo, args.cuct_hi)


if __name__ == "__main__":
    main()
