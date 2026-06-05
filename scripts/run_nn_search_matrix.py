"""Round-robin matrix over four NN-backed agents (all leaf = M_82k_warmM62k).

The four agents (no shared trees; single-seat per pairing, no seat-swap per
CLAUDE.md):

  A  uct        UCT + MACRO fencing, macros SAMPLED from the combined policy
                (`--macro-policy`), regular legality, c_uct = UCT_C (calibrated
                1.4/value_scale). V3-free (NN leaf + NN/policy macros).
  B  nn         NNAgent 1-turn greedy lookahead, regular legality.
  C  puct_unw   PUCT + FLATTEN, full legality, combined:unweighted prior, c = PUCT_C.
  D  puct_awr   PUCT + FLATTEN, full legality, combined:awr  prior, c = PUCT_C.

Each pairing runs through `scripts/play_mcts_match.py` (the tested CLI): the
"main" seat is P0 (mcts), the other is the opponent (P1). We parse its summary
line and print a results table. C_PUCT comes from the separate c_puct sweep.

Usage:
  python scripts/run_nn_search_matrix.py --puct-c 0.5 --uct-c 0.0608 \
      --sims 500 --n 100 --jobs 8 --fence-cache
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MATCH = ROOT / "scripts" / "play_mcts_match.py"

# Agent flag-sets. "main" flags configure the P0 (mcts) seat; "opp" flags
# configure a second mcts seat (P1) via the --opp-* mirror. nn is always the
# `--opponent nn` seat (never a main mcts seat), uct is always a main seat.
A_MAIN = [
    "--policy", "uct", "--legality", "regular", "--fence-mode", "macro",
    "--macro-policy", "combined:awr",
]
C_MAIN = ["--policy", "combined:unweighted", "--legality", "full", "--fence-mode", "flatten"]
C_OPP  = ["--opp-policy", "combined:unweighted", "--opp-legality", "full", "--opp-fence-mode", "flatten"]
D_MAIN = ["--policy", "combined:awr", "--legality", "full", "--fence-mode", "flatten"]
D_OPP  = ["--opp-policy", "combined:awr", "--opp-legality", "full", "--opp-fence-mode", "flatten"]

SUMMARY_RE = re.compile(
    r"P0 (\d+)-(\d+)-(\d+) P1\s+avg ([\d.+-]+) vs ([\d.+-]+)\s+margin ([\d.+-]+)"
)


def run_pairing(name, p0_label, p1_label, opponent, main_flags, opp_flags,
                *, puct_c, uct_c, sims, n, jobs, leaf_ckpt, extra):
    """Run one pairing through play_mcts_match.py and return a parsed dict."""
    cmd = [
        sys.executable, str(MATCH),
        "--opponent", opponent,
        "--leaf", "nn", "--leaf-ckpt", leaf_ckpt,
        "--sims", str(sims), "--n", str(n), "--jobs", str(jobs),
        *main_flags, *opp_flags, *extra,
    ]
    print(f"\n=== {name}: P0={p0_label}  vs  P1={p1_label} ===", flush=True)
    print("  " + " ".join(cmd[2:]), flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    dt = time.time() - t0
    out = proc.stdout
    if proc.returncode != 0:
        print(f"  !! FAILED (rc={proc.returncode})", flush=True)
        print(proc.stderr[-2000:], flush=True)
        return {"name": name, "p0": p0_label, "p1": p1_label, "ok": False}
    m = None
    for line in out.splitlines():
        mm = SUMMARY_RE.search(line)
        if mm:
            m = mm
    if not m:
        print("  !! could not parse summary", flush=True)
        print(out[-1500:], flush=True)
        return {"name": name, "p0": p0_label, "p1": p1_label, "ok": False}
    w, d, l = int(m.group(1)), int(m.group(2)), int(m.group(3))
    margin = float(m.group(6))
    print(f"  -> P0 {w}-{d}-{l} P1  margin {margin:+.2f}  ({dt/60:.1f} min)", flush=True)
    return {"name": name, "p0": p0_label, "p1": p1_label, "ok": True,
            "w": w, "d": d, "l": l, "margin": margin, "minutes": dt / 60}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--puct-c", type=float, required=True,
                   help="c_puct for the two PUCT agents (from the sweep; normalized units).")
    p.add_argument("--uct-c", type=float, default=0.0608,
                   help="c_uct for the UCT agent (default 1.4/value_scale = 0.0608).")
    p.add_argument("--sims", type=int, default=500)
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--leaf-ckpt", type=str, default="nn_models/best")
    # Default: inherit the agricola.opt_config module default (caches ON). Pass to
    # override (e.g. --opt-level 0 / --no-fence-cache to reproduce the baseline).
    p.add_argument("--fence-cache", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--opt-level", type=int, default=None, choices=[0, 1, 2, 3])
    args = p.parse_args()

    uct_c = [f"{args.uct_c}"]
    puct_c = [f"{args.puct_c}"]
    extra = []
    if args.fence_cache is not None:
        extra.append("--fence-cache" if args.fence_cache else "--no-fence-cache")
    if args.opt_level is not None:
        extra += ["--opt-level", str(args.opt_level)]

    # Per-pairing main/opp c_uct. play_mcts_match uses --c-uct (main) / --opp-c-uct (opp).
    A = A_MAIN + ["--c-uct", *uct_c]
    C_m = C_MAIN + ["--c-uct", *puct_c]
    D_m = D_MAIN + ["--c-uct", *puct_c]
    C_o = C_OPP + ["--opp-c-uct", *puct_c]
    D_o = D_OPP + ["--opp-c-uct", *puct_c]

    pairings = [
        ("A_vs_B", "uct",      "nn",       "nn",   A,   []),
        ("A_vs_C", "uct",      "puct_unw", "mcts", A,   C_o),
        ("A_vs_D", "uct",      "puct_awr", "mcts", A,   D_o),
        ("C_vs_B", "puct_unw", "nn",       "nn",   C_m, []),
        ("D_vs_B", "puct_awr", "nn",       "nn",   D_m, []),
        ("C_vs_D", "puct_unw", "puct_awr", "mcts", C_m, D_o),
    ]

    print(f"NN-search matrix: sims={args.sims}, n={args.n}, jobs={args.jobs}, "
          f"uct_c={args.uct_c}, puct_c={args.puct_c}, "
          f"opt-level={args.opt_level}, fence_cache={args.fence_cache}")
    results = []
    for name, p0, p1, opp, mflags, oflags in pairings:
        results.append(run_pairing(
            name, p0, p1, opp, mflags, oflags,
            puct_c=args.puct_c, uct_c=args.uct_c, sims=args.sims, n=args.n,
            jobs=args.jobs, leaf_ckpt=args.leaf_ckpt, extra=extra))

    print("\n" + "=" * 64)
    print("MATRIX RESULTS (P0 = first agent; W-D-L and margin from P0's view)")
    print("=" * 64)
    print(f"{'pairing':<10} {'P0':<9} {'P1':<9} {'W-D-L':>9} {'margin':>8} {'min':>6}")
    for r in results:
        if not r.get("ok"):
            print(f"{r['name']:<10} {r['p0']:<9} {r['p1']:<9} {'FAILED':>9}")
            continue
        wdl = f"{r['w']}-{r['d']}-{r['l']}"
        print(f"{r['name']:<10} {r['p0']:<9} {r['p1']:<9} {wdl:>9} "
              f"{r['margin']:>+8.2f} {r['minutes']:>6.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
