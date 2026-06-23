"""Kernel-regression analysis of the c_uct self-sweep.

Reads the merged per-level CSVs from `run_cpp_sweep.py --cuct-log` (columns
seed,p0,p1,winner,sims0,cuct0,sims1,cuct1), and for each sim level pools BOTH
seats into points (c_uct, result) — result 1/0.5/0 for win/draw/loss — then fits
a Gaussian Nadaraya-Watson kernel regression of win-prob on c_uct. The curve
answers: "playing this c_uct against the log-uniform-c_uct field at this sim
budget, what's your win prob?" — so its peak is the best fixed c_uct for that
budget.

Regression is done in LOG c_uct (the sampling was log-uniform → uniform density
in log-space → no boundary/density bias); the peak is reported back in c_uct.
The peak's 95% CI comes from a game-level bootstrap (resample games, refit,
collect argmax) so the within-game seat correlation is respected.

Usage:
  python scripts/nn/analyze_cuct_sweep.py --merged-dir sweep_out/merged \
      --out-png sweep_out/cuct_sweep.png
"""
import argparse
import csv
import glob
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402


def load_games(path):
    """Per-game (c0, c1, winner) arrays + the sim level (from sims0)."""
    c0, c1, w = [], [], []
    sims = None
    with open(path) as f:
        for row in csv.DictReader(f):
            c0.append(float(row["cuct0"]))
            c1.append(float(row["cuct1"]))
            w.append(int(row["winner"]))
            sims = int(row["sims0"])
    return np.array(c0), np.array(c1), np.array(w), sims


def seat_points(c0, c1, w):
    """Pool both seats -> (log_cuct, result)."""
    lc = np.concatenate([np.log(c0), np.log(c1)])
    y = np.concatenate([
        np.where(w == -1, 0.5, (w == 0).astype(float)),
        np.where(w == -1, 0.5, (w == 1).astype(float)),
    ])
    return lc, y


def kreg(lc, y, grid, h):
    """Gaussian Nadaraya-Watson on log-c_uct; returns (mean, se)."""
    mean = np.empty_like(grid)
    se = np.empty_like(grid)
    for i, g in enumerate(grid):
        ww = np.exp(-0.5 * ((lc - g) / h) ** 2)
        sw = ww.sum()
        m = float((ww * y).sum() / sw)
        neff = sw * sw / (ww * ww).sum()
        mean[i] = m
        se[i] = np.sqrt(max(m * (1 - m), 1e-9) / max(neff, 1.0))
    return mean, se


def boot_peak(c0, c1, w, grid, h, n_boot, rng):
    """Game-level bootstrap -> array of peak c_uct (in raw units)."""
    n = len(w)
    peaks = np.empty(n_boot)
    for b in range(n_boot):
        idx = rng.integers(0, n, n)
        lc, y = seat_points(c0[idx], c1[idx], w[idx])
        m, _ = kreg(lc, y, grid, h)
        peaks[b] = np.exp(grid[int(np.argmax(m))])
    return peaks


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--merged-dir", default="sweep_out/merged")
    p.add_argument("--out-png", default="sweep_out/cuct_sweep.png")
    p.add_argument("--bandwidth", type=float, default=0.18,
                   help="Gaussian kernel bandwidth in LOG-c_uct units (default 0.18)")
    p.add_argument("--n-boot", type=int, default=300)
    args = p.parse_args()

    files = sorted(glob.glob(os.path.join(args.merged_dir, "sweep_*.csv")))
    if not files:
        raise SystemExit(f"no sweep_*.csv in {args.merged_dir}")
    rng = np.random.default_rng(0)

    lo, hi = np.log(0.3), np.log(3.0)
    grid = np.linspace(lo, hi, 161)
    cgrid = np.exp(grid)

    series = []
    for path in files:
        c0, c1, w, sims = load_games(path)
        lc, y = seat_points(c0, c1, w)
        mean, se = kreg(lc, y, grid, args.bandwidth)
        peak_i = int(np.argmax(mean))
        peak_c = float(cgrid[peak_i])
        peaks = boot_peak(c0, c1, w, grid, args.bandwidth, args.n_boot, rng)
        ci = (float(np.percentile(peaks, 2.5)), float(np.percentile(peaks, 97.5)))
        # win% at the deployed c_uct=1.0
        j1 = int(np.argmin(np.abs(cgrid - 1.0)))
        series.append(dict(sims=sims, mean=mean, se=se, peak_c=peak_c,
                           peak_w=100 * mean[peak_i], ci=ci, w_at_1=100 * mean[j1],
                           n=len(w)))
        print(f"sims={sims:>4}: peak c_uct = {peak_c:.2f}  "
              f"(95% CI {ci[0]:.2f}-{ci[1]:.2f}), win {100*mean[peak_i]:.1f}%  |  "
              f"c_uct=1.0 -> {100*mean[j1]:.1f}%   (n={len(w)} games)")

    series.sort(key=lambda s: s["sims"])

    # Plot 1: win-prob vs c_uct, one curve per sim level.
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))
    for s in series:
        line, = ax1.plot(cgrid, 100 * s["mean"], lw=2, label=f"{s['sims']} sims")
        ax1.fill_between(cgrid, 100 * (s["mean"] - 1.96 * s["se"]),
                         100 * (s["mean"] + 1.96 * s["se"]),
                         color=line.get_color(), alpha=0.12)
        ax1.plot(s["peak_c"], s["peak_w"], "o", color=line.get_color(), ms=7)
    ax1.axhline(50, color="grey", ls="--", lw=1)
    ax1.axvline(1.0, color="black", ls=":", lw=1, label="deployed c_uct=1.0")
    ax1.set_xscale("log")
    ax1.set_xlabel("c_uct (log axis)")
    ax1.set_ylabel("win prob vs log-uniform-c_uct field (%)")
    ax1.set_title("Win probability vs c_uct, by sim budget")
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)

    # Plot 2: optimal c_uct vs sims (with bootstrap CI).
    sims = [s["sims"] for s in series]
    peak = [s["peak_c"] for s in series]
    lo_e = [s["peak_c"] - s["ci"][0] for s in series]
    hi_e = [s["ci"][1] - s["peak_c"] for s in series]
    ax2.errorbar(sims, peak, yerr=[lo_e, hi_e], marker="o", lw=2, capsize=4)
    ax2.axhline(1.0, color="black", ls=":", lw=1, label="deployed c_uct=1.0")
    ax2.set_xlabel("sims / move")
    ax2.set_ylabel("optimal c_uct (kernel-regression peak)")
    ax2.set_title("Optimal c_uct vs sim budget")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(args.out_png, dpi=130)
    print(f"\nwrote {args.out_png}")


if __name__ == "__main__":
    main()
