"""Parallel 100-game match: HubrisHeuristicV3 with lookahead='exhaustive'
vs the same agent with lookahead='turn' (greedy). Both use the current
v3_best.json config and restricted_legal_actions. Multiprocessing pool of
N workers, each plays one game.

Usage:
    python -O scripts/run_exhaustive_vs_greedy_match.py \\
        --config tuned_configs/v3_best.json --n-games 100 --jobs 8
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Worker globals (populated by _init_worker; one copy per worker process)
_CFG = None
_RESTRICTED = True
_EXHAUSTIVE_LEAF_CAP = 1000


def _init_worker(cfg_json_path: str, restricted: bool,
                  exhaustive_leaf_cap: int) -> None:
    """Each worker loads the config once at startup, so per-game work is
    just the game itself, not the JSON parse."""
    global _CFG, _RESTRICTED, _EXHAUSTIVE_LEAF_CAP
    from agricola.agents.heuristic import HeuristicConfigV3
    with open(cfg_json_path) as f:
        _CFG = HeuristicConfigV3(**json.load(f)["best_config"])
    _RESTRICTED = restricted
    _EXHAUSTIVE_LEAF_CAP = exhaustive_leaf_cap


def _play_one_game(seed: int) -> dict:
    """Worker-side: play one game. P0 = exhaustive, P1 = greedy.
    Returns {seed, score_p0, score_p1, margin, elapsed_seconds}.
    """
    import time as _time
    from agricola.agents.base import play_game
    from agricola.agents.heuristic import HubrisHeuristicV3
    from agricola.agents.restricted import restricted_legal_actions
    from agricola.legality import legal_actions
    from agricola.scoring import score
    from agricola.setup import setup, setup_env

    laf = restricted_legal_actions if _RESTRICTED else legal_actions
    p0 = HubrisHeuristicV3(seed=seed, config=_CFG, lookahead="exhaustive",
                            legal_actions_fn=laf,
                            exhaustive_leaf_cap=_EXHAUSTIVE_LEAF_CAP)
    p1 = HubrisHeuristicV3(seed=seed, config=_CFG, lookahead="turn",
                            legal_actions_fn=laf)
    t0 = _time.time()
    initial, env = setup_env(seed=seed)
    final, _ = play_game(initial, (p0, p1), env.resolve)
    s0, _ = score(final, 0)
    s1, _ = score(final, 1)
    return {
        "seed":             seed,
        "score_p0":         int(s0),
        "score_p1":         int(s1),
        "margin":           int(s0 - s1),
        "elapsed_seconds":  _time.time() - t0,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path,
                    default=ROOT / "tuned_configs" / "v3_best.json")
    p.add_argument("--n-games", type=int, default=100)
    p.add_argument("--seed-start", type=int, default=1000)
    p.add_argument("--jobs", type=int, default=8)
    p.add_argument("--restricted", action=argparse.BooleanOptionalAction,
                    default=True)
    p.add_argument("--exhaustive-leaf-cap", type=int, default=1000)
    args = p.parse_args()

    seeds = list(range(args.seed_start, args.seed_start + args.n_games))
    print(f"100-game match: P0=exhaustive vs P1=greedy")
    print(f"  config: {args.config}")
    print(f"  n_games: {args.n_games}  (seeds {seeds[0]}..{seeds[-1]})")
    print(f"  jobs: {args.jobs}")
    print(f"  restricted: {args.restricted}")
    print(f"  exhaustive_leaf_cap: {args.exhaustive_leaf_cap}")
    print()

    t0 = time.time()
    with Pool(args.jobs,
              initializer=_init_worker,
              initargs=(str(args.config), args.restricted,
                        args.exhaustive_leaf_cap)) as pool:
        results = []
        for r in pool.imap_unordered(_play_one_game, seeds):
            results.append(r)
            n_done = len(results)
            if n_done % 10 == 0:
                elapsed = time.time() - t0
                rate = n_done / elapsed
                eta = (args.n_games - n_done) / rate if rate > 0 else 0
                print(f"  {n_done}/{args.n_games} done  "
                      f"({elapsed:.1f}s elapsed, ETA {eta:.1f}s)")

    elapsed = time.time() - t0
    p0_wins = sum(1 for r in results if r["margin"] > 0)
    p1_wins = sum(1 for r in results if r["margin"] < 0)
    draws   = sum(1 for r in results if r["margin"] == 0)
    avg_p0  = sum(r["score_p0"] for r in results) / len(results)
    avg_p1  = sum(r["score_p1"] for r in results) / len(results)
    avg_margin = avg_p0 - avg_p1
    avg_game_wall = sum(r["elapsed_seconds"] for r in results) / len(results)

    print()
    print("=" * 70)
    print(f"RESULT: P0={p0_wins}-{draws}-{p1_wins}=P1  "
          f"avg {avg_p0:+.2f} vs {avg_p1:+.2f}  margin {avg_margin:+.4f}  "
          f"({len(results)} games)")
    print("=" * 70)
    print(f"  Wall time:        {elapsed:.1f}s  ({elapsed/60:.1f} min)")
    print(f"  Avg per-game:     {avg_game_wall:.2f}s (across all {args.jobs} workers)")
    print(f"  Effective speedup: {(avg_game_wall * len(results)) / elapsed:.1f}x")

    # Margin distribution
    margins = sorted(r["margin"] for r in results)
    print()
    print("Margin distribution (P0 score − P1 score):")
    print(f"  min: {margins[0]}  p25: {margins[len(margins)//4]}  "
          f"median: {margins[len(margins)//2]}  "
          f"p75: {margins[3*len(margins)//4]}  max: {margins[-1]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
