"""Parallel two-net C++ MCTS match driver.

Runs the `cpp/build/selfplay --match` binary across a process pool — each worker
plays a contiguous slice of seeds (P0 = --p0-dir's value net, P1 = --p1-dir's),
parses the per-game `GAME ...` / `MATCH ...` lines, and aggregates W-D-L + the
P0-P1 score-margin. The binary is single-threaded per process, so this is how we
parallelize an N-game match (mirrors generate_selfplay_data_cpp.py's worker-pool
pattern). Memory-light: C++ inference is hand-rolled MLPs, not torch.

Example:
  python scripts/nn/run_cpp_match.py \
    --p0-dir nn_models/cpp_export_256 --p1-dir nn_models/cpp_export_512 \
    --n 200 --jobs 6 --sims 800 --c-uct 0.5 --temperature 0.2 --label 256v512
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from multiprocessing import Pool

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
    p0_dir, p1_dir, idxs, base_seed, sims, c_uct, temp, label, widx, progress_dir = arg
    cmd = [BINARY, "--match", "--mcts",
           "--model-dir-p0", p0_dir, "--model-dir-p1", p1_dir,
           "--game-idxs", ",".join(map(str, idxs)),
           "--base-seed", str(base_seed),
           "--sims", str(sims), "--c-uct", str(c_uct), "--temperature", str(temp)]
    p0w = p1w = draws = 0
    margins = []
    done = 0
    # Stream the binary's stdout line-by-line so each finished game lands in a
    # per-worker progress file IMMEDIATELY (tail -f eval_out/progress/<label>_w*).
    pf = Path(progress_dir) / f"{label}_w{widx}.log" if progress_dir else None
    pfh = open(pf, "w") if pf else None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        for line in proc.stdout:
            if line.startswith("GAME"):
                f = dict(tok.split("=") for tok in line.split()[1:])
                margins.append(int(f["p0"]) - int(f["p1"]))
                done += 1
                if pfh:
                    pfh.write(f"[{label} w{widx}] {done}/{len(idxs)}  {line}")
                    pfh.flush()
            elif line.startswith("MATCH"):
                f = dict(tok.split("=") for tok in line.split()[1:])
                p0w += int(f["p0_wins"]); p1w += int(f["p1_wins"])
                draws += int(f["draws"])
        err_txt = proc.stderr.read()
        rc = proc.wait()
    finally:
        if pfh:
            pfh.close()
    if rc != 0:
        return {"err": err_txt[-500:], "p0w": 0, "p1w": 0, "draws": 0, "margins": []}
    return {"err": None, "p0w": p0w, "p1w": p1w, "draws": draws, "margins": margins}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--p0-dir", required=True, help="P0 cpp_export dir (value+policy)")
    ap.add_argument("--p1-dir", required=True, help="P1 cpp_export dir")
    ap.add_argument("--n", type=int, default=200, help="games (seeds 0..n-1)")
    ap.add_argument("--jobs", type=int, default=6)
    ap.add_argument("--sims", type=int, default=800)
    ap.add_argument("--c-uct", type=float, default=0.5)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--base-seed", type=int, default=0)
    ap.add_argument("--label", type=str, default="match")
    args = ap.parse_args()

    progress_dir = ROOT / "eval_out" / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)
    chunks = _contiguous_chunks(args.n, args.jobs)
    tasks = [(args.p0_dir, args.p1_dir, c, args.base_seed, args.sims,
              args.c_uct, args.temperature, args.label, i, str(progress_dir))
             for i, c in enumerate(chunks)]
    print(f"[{args.label}] {args.n} games, {len(chunks)} workers, sims={args.sims} "
          f"c_uct={args.c_uct} temp={args.temperature}", flush=True)
    print(f"  P0={args.p0_dir}\n  P1={args.p1_dir}", flush=True)
    print(f"  live per-game progress: tail -f {progress_dir}/{args.label}_w*.log",
          flush=True)

    with Pool(len(chunks)) as pool:
        results = pool.map(_run_chunk, tasks)

    errs = [r["err"] for r in results if r["err"]]
    for e in errs:
        print(f"  worker error: {e}", file=sys.stderr)
    p0w = sum(r["p0w"] for r in results)
    p1w = sum(r["p1w"] for r in results)
    draws = sum(r["draws"] for r in results)
    margins = [m for r in results for m in r["margins"]]
    total = p0w + p1w + draws
    avg_margin = (sum(margins) / len(margins)) if margins else 0.0
    p0_rate = 100.0 * p0w / total if total else 0.0
    print(f"[{args.label}] RESULT  P0={p0w}  P1={p1w}  D={draws}  "
          f"(P0 win% {p0_rate:.1f})  avg margin (P0-P1)={avg_margin:+.2f}  "
          f"[{total} games]", flush=True)
    return 0 if total == args.n and not errs else 1


if __name__ == "__main__":
    raise SystemExit(main())
