"""Kernel-regression analysis of a mix-rate (alpha) self-sweep.

Reads one or more CSVs produced by `run_cpp_sweep.py --sweep-alpha` (columns incl.
`alpha0,alpha1,winner`), pools BOTH seats into points `(alpha, result)` where
result is 1 (win) / 0.5 (draw) / 0 (loss) for that seat, and fits a Gaussian
Nadaraya-Watson kernel regression of win-prob on alpha. The curve answers: "if you
play mix-rate alpha against a uniform-random-alpha opponent field, what's your win
prob?" — so its peak is the best fixed alpha.

alpha convention: 1 = pure margin leaf, 0 = pure outcome leaf, 0.5 = the 50/50 mix.

Usage:
  python scripts/nn/analyze_alpha_sweep.py \
     --series "800 sims=eval_out/alpha_800.csv" "1600 sims=eval_out/alpha_1600.csv" \
     --out-png eval_out/alpha_sweep.png
"""
import argparse
import csv

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def load_points(path: str):
    """Pool both seats -> (alpha, result) arrays. winner: 0=P0, 1=P1, -1=draw."""
    a, y = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            w = int(row["winner"])
            for seat in (0, 1):
                a.append(float(row[f"alpha{seat}"]))
                y.append(0.5 if w == -1 else (1.0 if w == seat else 0.0))
    return np.asarray(a, float), np.asarray(y, float)


def kreg(a, y, grid, h):
    """Gaussian Nadaraya-Watson; returns (mean, se) with effective-N std error."""
    mean = np.empty_like(grid)
    se = np.empty_like(grid)
    for i, g in enumerate(grid):
        w = np.exp(-0.5 * ((a - g) / h) ** 2)
        sw = w.sum()
        m = float((w * y).sum() / sw)
        neff = sw * sw / (w * w).sum()           # effective sample size at g
        mean[i] = m
        se[i] = np.sqrt(max(m * (1 - m), 1e-9) / max(neff, 1.0))
    return mean, se


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--series", nargs="+", required=True,
                   help='one or more "label=path.csv" (e.g. "800 sims=a.csv")')
    p.add_argument("--out-png", required=True)
    p.add_argument("--bandwidth", type=float, default=0.05,
                   help="Gaussian kernel bandwidth in alpha units (default 0.05)")
    args = p.parse_args()

    grid = np.linspace(0.0, 1.0, 201)
    plt.figure(figsize=(8, 5))
    for spec in args.series:
        label, path = spec.split("=", 1)
        a, y = load_points(path)
        mean, se = kreg(a, y, grid, args.bandwidth)
        peak = grid[int(np.argmax(mean))]
        line, = plt.plot(grid, 100 * mean, lw=2,
                         label=f"{label}  (n={len(a)} seat-games, peak α≈{peak:.2f})")
        plt.fill_between(grid, 100 * (mean - 1.96 * se), 100 * (mean + 1.96 * se),
                         color=line.get_color(), alpha=0.15)
        # reference win% at the three canonical alphas
        for ax_val in (0.0, 0.5, 1.0):
            j = int(round(ax_val * (len(grid) - 1)))
            print(f"{label}: win% at α={ax_val:.1f} = {100*mean[j]:.1f}%  | peak α={peak:.2f} ({100*mean.max():.1f}%)")

    plt.axhline(50, color="grey", ls="--", lw=1)
    plt.xlabel("mix rate α   (1 = pure margin, 0 = pure outcome)")
    plt.ylabel("win prob vs uniform-random-α field (%)")
    plt.title("Mix-rate sweep: win probability vs α")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(args.out_png, dpi=130)
    print(f"\nwrote {args.out_png}")


if __name__ == "__main__":
    main()
