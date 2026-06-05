"""Analyze a search-agent tournament (scripts/run_search_tournament.py output).

Reads <out-dir>/games.jsonl and reports:
  1. Per-config table: games, raw win%, Bradley-Terry strength (opponent-
     adjusted), and BT-implied win% vs the anchor.
  2. Marginal means by dimension: archetype, sims (per algo), c (per algo).
  3. The c x sims strength grid per algo.

Why Bradley-Terry: with random pairings a config's raw win% is confounded by
which opponents it happened to draw. BT fits one latent strength per config
that explains all pairwise outcomes jointly, so it controls for opponent
strength. Strengths are reported relative to the anchor (anchor = 0); a strength
of +g means BT-implied win prob vs anchor = sigmoid(g).

Draws count as half a win to each side. A light pseudo-count (--reg) regularizes
toward equal strength so configs with extreme records stay finite. Run any time,
including on a partial/killed run.

    python scripts/analyze_tournament.py --out-dir data/tournaments/search_tourney
"""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

import numpy as np


def load_games(path: Path) -> list[dict]:
    games = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                games.append(json.loads(line))
    return games


def fit_bradley_terry(games, names, reg=0.5, iters=10000, tol=1e-9):
    """Zermelo / MM fit. Returns dict name -> log-strength (anchor-relative)."""
    idx = {n: i for i, n in enumerate(names)}
    k = len(names)
    N = np.zeros((k, k))          # games between i and j (symmetric)
    W = np.zeros(k)               # win credit (1 win, 0.5 draw)
    for g in games:
        i, j = idx[g["p0"]], idx[g["p1"]]
        N[i, j] += 1
        N[j, i] += 1
        w = g["winner"]
        if w == 0:
            W[i] += 1
        elif w == 1:
            W[j] += 1
        else:
            W[i] += 0.5
            W[j] += 0.5
    # Regularize: add `reg` virtual draws between every pair.
    if reg > 0:
        off = reg * (np.ones((k, k)) - np.eye(k))
        N += off
        W += 0.5 * reg * (k - 1)

    pi = np.ones(k)
    for _ in range(iters):
        denom = np.zeros(k)
        for i in range(k):
            # sum_j N_ij / (pi_i + pi_j)
            mask = N[i] > 0
            denom[i] = np.sum(N[i][mask] / (pi[i] + pi[mask]))
        new = np.where(denom > 0, W / denom, pi)
        new /= np.exp(np.mean(np.log(new)))  # normalize geometric mean = 1
        if np.max(np.abs(np.log(new) - np.log(pi))) < tol:
            pi = new
            break
        pi = new

    s = np.log(pi)
    anchor = "anchor"
    if anchor in idx:
        s = s - s[idx[anchor]]
    return {n: float(s[idx[n]]) for n in names}


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-dir", type=str, default="data/tournaments/search_tourney")
    p.add_argument("--reg", type=float, default=0.5, help="BT pseudo-count.")
    args = p.parse_args()

    path = Path(args.out_dir) / "games.jsonl"
    if not path.exists():
        raise SystemExit(f"No games file at {path}")
    games = load_games(path)
    if not games:
        raise SystemExit("No games recorded yet.")

    # Per-config raw tallies + per-config attribute lookup.
    raw_w = defaultdict(float)
    raw_n = defaultdict(int)
    margin = defaultdict(float)
    attr = {}  # name -> (kind, c, sims)
    for g in games:
        for seat in (0, 1):
            name = g[f"p{seat}"]
            attr[name] = (g[f"p{seat}_kind"], g[f"p{seat}_c"], g[f"p{seat}_sims"])
            raw_n[name] += 1
            if g["winner"] == seat:
                raw_w[name] += 1
            elif g["winner"] is None:
                raw_w[name] += 0.5
            margin[name] += (g["score0"] - g["score1"]) * (1 if seat == 0 else -1)

    names = sorted(attr, key=lambda n: (attr[n][0], attr[n][1] or 0, attr[n][2] or 0))
    bt = fit_bradley_terry(games, names, reg=args.reg)

    print(f"\n=== Tournament analysis: {len(games)} games, {len(names)} configs ===\n")

    # 1. Per-config table.
    print(f"{'config':22s} {'games':>6s} {'rawW%':>6s} {'avgMrg':>7s} "
          f"{'BTstr':>7s} {'vsAnchor%':>9s}")
    print("-" * 62)
    for n in sorted(names, key=lambda n: -bt[n]):
        g = raw_n[n]
        wp = 100 * raw_w[n] / g if g else 0
        mg = margin[n] / g if g else 0
        print(f"{n:22s} {g:6d} {wp:6.1f} {mg:7.2f} {bt[n]:7.2f} "
              f"{100*sigmoid(bt[n]):9.1f}")

    # 2. Marginal means by dimension (mean BT strength over configs in bucket).
    def bucket_report(title, key_fn):
        groups = defaultdict(list)
        for n in names:
            k = key_fn(n)
            if k is not None:
                groups[k].append(n)
        print(f"\n{title}")
        for k in sorted(groups, key=lambda x: (str(type(x)), x)):
            cfgs = groups[k]
            ms = np.mean([bt[n] for n in cfgs])
            tot_g = sum(raw_n[n] for n in cfgs)
            print(f"  {str(k):16s} BTstr={ms:+.2f}  ({len(cfgs)} cfgs, {tot_g} games)")

    bucket_report("By archetype:", lambda n: attr[n][0])
    bucket_report("By sims (UCT only):",
                  lambda n: attr[n][2] if attr[n][0] == "uct" else None)
    bucket_report("By sims (PUCT only):",
                  lambda n: attr[n][2] if attr[n][0] == "puct" else None)
    bucket_report("By c (UCT only):",
                  lambda n: attr[n][1] if attr[n][0] == "uct" else None)
    bucket_report("By c (PUCT only):",
                  lambda n: attr[n][1] if attr[n][0] == "puct" else None)

    # 3. c x sims grids.
    for algo in ("uct", "puct"):
        cs = sorted({attr[n][1] for n in names if attr[n][0] == algo})
        ss = sorted({attr[n][2] for n in names if attr[n][0] == algo})
        if not cs:
            continue
        print(f"\n{algo.upper()} BT-strength grid (rows=c, cols=sims):")
        print("      " + "".join(f"{s:>9d}" for s in ss))
        lookup = {(attr[n][1], attr[n][2]): bt[n] for n in names if attr[n][0] == algo}
        for c in cs:
            row = "".join(
                f"{lookup[(c, s)]:>9.2f}" if (c, s) in lookup else f"{'--':>9s}"
                for s in ss
            )
            print(f"  c={c:<3g}{row}")

    print()


if __name__ == "__main__":
    main()
