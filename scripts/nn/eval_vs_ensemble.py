"""Evaluate a trained NN value function against the 8-config ensemble.

Parallel, single-seat. Drives `scripts/nn/play_match.py` (multiprocessing,
`--jobs`) once per ensemble opponent with the NN always P0 — a single
consistent seat (P0/P1 are symmetric; one seat over many seeds averages the
starting-player advantage, so no 50/50 split is needed). Both seats use
regular `restricted_legal_actions` (`--nn-legality regular` + the heuristic
seat's default), matching the training-pipeline convention.

Prints a per-opponent W-L-D + win% + avg-margin table and an aggregate.

(This replaces the older serial, seat-swapped implementation — the §13
"refold onto the parallel play_match engine" item. Numbers are single-seat,
so they are NOT directly comparable to pre-existing seat-swapped aggregates;
re-baseline a reference model through this tool for an apples-to-apples
comparison.)

CLI:
    python scripts/nn/eval_vs_ensemble.py \\
        --model nn_models/<run-id>/best.pt --n 100 --jobs 8
"""
from __future__ import annotations
import argparse, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# DATA_GEN_ENSEMBLE.md order.
ENSEMBLE = [
    ("t2", "v1"),
    ("tuned_configs/alphas_gen_7.json", "v3"),
    ("tuned_configs/alphas_gen_1.json", "v3"),
    ("tuned_configs/panel_wood_r1.json", "v3"),
    ("tuned_configs/panel_gen16.json", "v3"),
    ("tuned_configs/panel_gen47_wood020.json", "v3"),
    ("tuned_configs/panel_gen_25.json", "v3"),
    ("tuned_configs/panel_gen47.json", "v3"),
]
FINAL_RE = re.compile(
    r"Final: P0=(\d+)\s+P1=(\d+)\s+D=(\d+)\s+avg margin \(P0-P1\)=([+-][\d.]+)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True, help="NN checkpoint .pt (P0 seat)")
    ap.add_argument("--n", type=int, default=100, help="games per opponent")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--seed-start", type=int, default=0)
    args = ap.parse_args()

    print(f"NN {args.model} vs 8-config ensemble | {args.n} games/opp, "
          f"single-seat (NN=P0), regular legality, {args.jobs} workers\n")
    print(f"{'opponent':<24} {'NN W-L-D':>12} {'win%':>7} {'margin':>8}")
    print("-" * 56)
    tw = tl = td = 0
    msum = 0.0
    for spec, arch in ENSEMBLE:
        cmd = [sys.executable, str(ROOT / "scripts/nn/play_match.py"),
               "--p0", "nn", "--p1", "heuristic",
               "--p0-model", args.model,
               "--p1-config", spec, "--p1-arch", arch,
               "--n", str(args.n), "--jobs", str(args.jobs),
               "--nn-legality", "regular", "--seed-start", str(args.seed_start)]
        out = subprocess.run(cmd, capture_output=True, text=True).stdout
        m = FINAL_RE.search(out)
        name = spec.replace("tuned_configs/", "").replace(".json", "")
        if not m:
            print(f"{name:<24}  PARSE FAIL (see stderr)", flush=True)
            continue
        w, l, d, marg = int(m[1]), int(m[2]), int(m[3]), float(m[4])
        tw += w; tl += l; td += d; msum += marg
        dec = max(w + l, 1)
        print(f"{name:<24} {w:>4}-{l:<3}-{d:<3} {100 * w / dec:>6.1f}% "
              f"{marg:>+7.2f}", flush=True)
    print("-" * 56)
    dec = max(tw + tl, 1)
    print(f"{'AGGREGATE':<24} {tw}-{tl}-{td}  {100 * tw / dec:.1f}%  "
          f"avg margin {msum / len(ENSEMBLE):+.2f}  ({tw + tl + td} games)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
