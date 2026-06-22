"""Parallel two-net C++ MCTS match driver.

Runs the `cpp/build/selfplay --match` binary across a process pool — each worker
plays a contiguous slice of seeds (P0 = --p0-dir's model, P1 = --p1-dir's) and
streams its per-game `GAME ...` lines back to the parent via a shared queue. The
PARENT prints every completed game (running tally) to **stdout**, in one stream —
so a parallel run produces one clean log, exactly like `scripts/play_mcts_match.py`
(no per-worker files). Memory-light: C++ inference is hand-rolled MLPs, not torch.

Logging convention: this driver streams to stdout; the launcher redirects to
`eval_out/<label>.log` (one file per run). Example:

  python scripts/nn/run_cpp_match.py \
    --p0-dir nn_models/cpp_export_cand178 --p1-dir nn_models/cpp_export_taper128 \
    --n 100 --jobs 6 --sims 800 --c-uct 1.0 --temperature 0.0 --label e39_t0 \
    > eval_out/e39_t0.log
"""
from __future__ import annotations

import argparse
import queue as queuelib
import subprocess
import sys
from multiprocessing import Manager, Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BINARY = str(ROOT / "cpp" / "build" / "selfplay")


def _contiguous_chunks(n: int, k: int) -> list[list[int]]:
    """Split range(n) into k contiguous slices (balanced)."""
    k = max(1, min(k, n))
    base, rem = divmod(n, k)
    out, start = [], 0
    for i in range(k):
        size = base + (1 if i < rem else 0)
        out.append(list(range(start, start + size)))
        start += size
    return [c for c in out if c]


def _run_chunk(arg):
    """Play a slice in one binary process; push each finished game onto `q` as
    `(seed, p0, p1, winner)`. Returns an error string (or None) — the parent
    computes the tally from the queue, so this only reports failures."""
    p0_dir, p1_dir, idxs, base_seed, sims, c_uct, temp, per_seat, q = arg
    cmd = [BINARY, "--match", "--mcts",
           "--model-dir-p0", p0_dir, "--model-dir-p1", p1_dir,
           "--game-idxs", ",".join(map(str, idxs)),
           "--base-seed", str(base_seed),
           "--sims", str(sims), "--c-uct", str(c_uct), "--temperature", str(temp)]
    # Optional fixed per-seat overrides (e.g. 800 sims P0 vs 500 sims P1).
    for flag, val in per_seat.items():
        if val is not None:
            cmd += [flag, str(val)]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)
    for line in proc.stdout:
        if line.startswith("GAME"):
            f = dict(tok.split("=") for tok in line.split()[1:])
            q.put((int(f["seed"]), int(f["p0"]), int(f["p1"]), int(f["winner"])))
        # MATCH line ignored — the parent aggregates from the per-game results.
    err_txt = proc.stderr.read()
    return err_txt[-500:] if proc.wait() != 0 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--p0-dir", required=True, help="P0 cpp_export dir (value+policy)")
    ap.add_argument("--p1-dir", required=True, help="P1 cpp_export dir")
    ap.add_argument("--n", type=int, default=200, help="games (seeds 0..n-1)")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--sims", type=int, default=800)
    ap.add_argument("--c-uct", type=float, default=1.0)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--base-seed", type=int, default=0)
    ap.add_argument("--label", type=str, default="match")
    ap.add_argument("--sims-p0", type=int, default=None,
                    help="fixed P0 sims override (default: --sims for both seats)")
    ap.add_argument("--sims-p1", type=int, default=None, help="fixed P1 sims override")
    ap.add_argument("--c-uct-p0", type=float, default=None, help="fixed P0 c_uct override")
    ap.add_argument("--c-uct-p1", type=float, default=None, help="fixed P1 c_uct override")
    ap.add_argument("--prior-mix-p0", type=float, default=None,
                    help="P0 policy-prior uniform mix (0=pure policy)")
    ap.add_argument("--prior-mix-p1", type=float, default=None,
                    help="P1 policy-prior uniform mix (e.g. 0.05)")
    ap.add_argument("--temperature-p0", type=float, default=None,
                    help="P0 played-move temperature override")
    ap.add_argument("--temperature-p1", type=float, default=None,
                    help="P1 played-move temperature override")
    ap.add_argument("--select-by-p0", choices=["visits", "q"], default=None,
                    help="P0 played-move selection: visits (default) or q (rank by mean-Q)")
    ap.add_argument("--select-by-p1", choices=["visits", "q"], default=None,
                    help="P1 played-move selection: visits (default) or q")
    ap.add_argument("--leaf-mode-p0", choices=["margin", "outcome", "mix"], default=None,
                    help="P0 leaf-value head: margin (default) / outcome / mix")
    ap.add_argument("--leaf-mode-p1", choices=["margin", "outcome", "mix"], default=None,
                    help="P1 leaf-value head: margin (default) / outcome / mix")
    args = ap.parse_args()

    chunks = _contiguous_chunks(args.n, args.jobs)
    mgr = Manager()
    q = mgr.Queue()
    per_seat = {"--sims-p0": args.sims_p0, "--sims-p1": args.sims_p1,
                "--c-uct-p0": args.c_uct_p0, "--c-uct-p1": args.c_uct_p1,
                "--prior-mix-p0": args.prior_mix_p0, "--prior-mix-p1": args.prior_mix_p1,
                "--temperature-p0": args.temperature_p0, "--temperature-p1": args.temperature_p1,
                "--select-by-p0": args.select_by_p0, "--select-by-p1": args.select_by_p1,
                "--leaf-mode-p0": args.leaf_mode_p0, "--leaf-mode-p1": args.leaf_mode_p1}
    tasks = [(args.p0_dir, args.p1_dir, c, args.base_seed, args.sims,
              args.c_uct, args.temperature, per_seat, q) for c in chunks]

    s0 = args.sims_p0 if args.sims_p0 is not None else args.sims
    s1 = args.sims_p1 if args.sims_p1 is not None else args.sims
    c0 = args.c_uct_p0 if args.c_uct_p0 is not None else args.c_uct
    c1 = args.c_uct_p1 if args.c_uct_p1 is not None else args.c_uct
    print(f"[{args.label}] {args.n} games, {len(chunks)} workers, "
          f"P0(sims={s0},c_uct={c0}) vs P1(sims={s1},c_uct={c1}) "
          f"temp={args.temperature}", flush=True)
    print(f"  P0={args.p0_dir}\n  P1={args.p1_dir}", flush=True)

    p0w = p1w = draws = 0
    margin_sum = 0
    done = 0
    with Pool(len(chunks)) as pool:
        res = pool.map_async(_run_chunk, tasks)
        # Drain the queue while workers run: one streamed line per finished game.
        while not (res.ready() and q.empty()):
            try:
                seed, p0s, p1s, w = q.get(timeout=0.3)
            except queuelib.Empty:
                continue
            done += 1
            margin_sum += p0s - p1s
            if w == 0:
                p0w += 1
            elif w == 1:
                p1w += 1
            else:
                draws += 1
            who = "P0" if w == 0 else ("P1" if w == 1 else "tie")
            print(f"  [{done:>3}/{args.n}] seed={seed:>3} P0={p0s:>3} P1={p1s:>3} "
                  f"-> {who:>3} | P0 {p0w}-{draws}-{p1w} P1 | "
                  f"avg margin {margin_sum / done:+.2f}", flush=True)
        errs = [e for e in res.get() if e]

    for e in errs:
        print(f"  worker error: {e}", file=sys.stderr)
    total = p0w + p1w + draws
    rate = 100.0 * p0w / total if total else 0.0
    avg = margin_sum / total if total else 0.0
    print(f"[{args.label}] RESULT  P0={p0w}  P1={p1w}  D={draws}  "
          f"(P0 win% {rate:.1f})  avg margin (P0-P1)={avg:+.2f}  [{total} games]",
          flush=True)
    return 0 if total == args.n and not errs else 1


if __name__ == "__main__":
    raise SystemExit(main())
