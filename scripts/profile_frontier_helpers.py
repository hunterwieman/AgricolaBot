"""Benchmark + hit-rate profiler for the frontier/accommodation helpers.

Companion to FRONTIER_OPT_DESIGN.md §8.2. Two modes, both runnable TODAY (before
any optimization lands), so they de-risk the design before code is written:

  microbench  Per-call cost (µs) of each frontier helper over the 9 prefab
              states from scripts/profile_states.py. Establishes the Level-0
              baseline; re-run at each --level after the optimization lands to
              read the actual speedup. (Tree-independent — isolates the Level-1
              algorithmic gain with no MCTS confound.)

  collision   Runs one full MCTS-vs-hubris_v3 game with the helpers wrapped to
              record their *projection key* on every call, then reports
              distinct-keys / total-calls. The "hit rate" column is exactly the
              fraction of calls a perfect projection cache would serve from
              cache — i.e. the payoff of Levels 2-3 — measured WITHOUT building
              the cache. This is the gate for Phase 2/3 (FRONTIER_OPT_DESIGN.md
              §10): low hit rate => caching isn't worth it.

For end-to-end wall-clock A/B across levels, use scripts/play_mcts_match.py
(fixed --seeds + --sims, --jobs 1) and scripts/measure_mcts_tree.py (to confirm
levels 1-3 build identical trees). This script covers the two measurements those
don't.

Usage:
    python -O scripts/profile_frontier_helpers.py                 # both modes
    python -O scripts/profile_frontier_helpers.py --mode microbench --iters 5000
    python -O scripts/profile_frontier_helpers.py --mode collision --sims 300 --seed 0
    python -O scripts/profile_frontier_helpers.py --level 3       # once opt_config exists
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import timeit
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np

from agricola.helpers import cooking_rates, extract_slots
from agricola.resources import Animals


# ---------------------------------------------------------------------------
# Projection-key functions — mirror the cache keys in FRONTIER_OPT_DESIGN.md.
# ---------------------------------------------------------------------------

def _slots(ps):
    caps, flex = extract_slots(ps)
    return tuple(sorted(caps)), flex


def _animal_key(ps, gained):
    """Rates-free key for pareto/breeding (§2.1): farm shape + available caps."""
    caps, flex = _slots(ps)
    a = ps.animals
    return (caps, flex,
            a.sheep + gained.sheep, a.boar + gained.boar, a.cattle + gained.cattle)


def _feed_caps(ps, food_owed, rates):
    """Clipped supplies (§6.5 Level 2): min(supply, ceil(food_owed/rate))."""
    sR, bR, cR, vR = rates
    r, a = ps.resources, ps.animals
    cap_g = min(r.grain, food_owed)
    cap_v = min(r.veg,    math.ceil(food_owed / vR)) if vR > 0 else 0
    cap_s = min(a.sheep,  math.ceil(food_owed / sR)) if sR > 0 else 0
    cap_b = min(a.boar,   math.ceil(food_owed / bR)) if bR > 0 else 0
    cap_c = min(a.cattle, math.ceil(food_owed / cR)) if cR > 0 else 0
    return (cap_g, cap_v, cap_s, cap_b, cap_c)


def _feed_exact(ps):
    r, a = ps.resources, ps.animals
    return (r.grain, r.veg, a.sheep, a.boar, a.cattle)


# ---------------------------------------------------------------------------
# Mode 1: microbench — per-call cost over prefab states.
# ---------------------------------------------------------------------------

def microbench(iters: int) -> None:
    from scripts.profile_states import STATES
    from agricola.helpers import (
        breeding_frontier, food_payment_frontier, harvest_feed_frontier,
        pareto_frontier,
    )

    per_helper: dict[str, list[float]] = defaultdict(list)
    rows: list[tuple] = []

    for name, factory in STATES.items():
        state = factory()
        for pidx, ps in enumerate(state.players):
            rates4 = cooking_rates(state, pidx)
            rates3 = rates4[:3]
            need = max(1, 2 * ps.people_total - ps.newborns)
            cases = [
                ("pareto_frontier",
                 lambda ps=ps, r=rates3: pareto_frontier(ps, Animals(sheep=1), r)),
                ("breeding_frontier",
                 lambda ps=ps, r=rates3: breeding_frontier(ps, r)),
                ("harvest_feed_frontier",
                 lambda ps=ps, r=rates4, fo=need: harvest_feed_frontier(ps, fo, r)),
                ("food_payment_frontier",
                 lambda ps=ps, r=rates4, fo=need: food_payment_frontier(ps, fo, r)),
            ]
            for hname, fn in cases:
                try:
                    res = fn()
                except Exception:
                    continue
                us = timeit.timeit(fn, number=iters) / iters * 1e6
                per_helper[hname].append(us)
                rows.append((name, pidx, hname, len(res), us))

    print(f"\n=== microbench (per-call µs, {iters} iters/case) ===")
    print(f"{'state':<28} {'p':>1} {'helper':<24} {'|frontier|':>10} {'µs/call':>9}")
    for name, pidx, hname, n, us in sorted(rows, key=lambda r: -r[4]):
        print(f"{name:<28} {pidx:>1} {hname:<24} {n:>10} {us:>9.2f}")

    print("\n--- per-helper mean µs/call (Level-0 baseline) ---")
    for hname in ("pareto_frontier", "breeding_frontier",
                  "harvest_feed_frontier", "food_payment_frontier"):
        xs = per_helper.get(hname, [])
        if xs:
            print(f"  {hname:<24} mean {sum(xs)/len(xs):>8.2f}  "
                  f"max {max(xs):>8.2f}  (n={len(xs)})")


# ---------------------------------------------------------------------------
# Mode 2: collision — predicted cache hit rate over an MCTS game.
# ---------------------------------------------------------------------------

_counters: dict[str, Counter] = defaultdict(Counter)


def _install_wrappers() -> None:
    import agricola.helpers as H
    import agricola.legality as L

    _orig_pareto = H.pareto_frontier
    _orig_breed = H.breeding_frontier
    _orig_feed = H.harvest_feed_frontier
    _orig_pay = H.food_payment_frontier
    _orig_fence = L._any_legal_pasture_commit

    def w_pareto(player_state, gained, rates=(0, 0, 0)):
        _counters["pareto_frontier"][_animal_key(player_state, gained)] += 1
        return _orig_pareto(player_state, gained, rates)

    def w_breed(player_state, rates=(0, 0, 0)):
        _counters["breeding_frontier"][_animal_key(player_state, Animals())] += 1
        return _orig_breed(player_state, rates)

    def w_feed(player_state, food_owed, rates):
        _counters["harvest_feed (clipped key)"][
            (_feed_caps(player_state, food_owed, rates), food_owed, rates)] += 1
        _counters["harvest_feed (exact key)"][
            (_feed_exact(player_state), food_owed, rates)] += 1
        return _orig_feed(player_state, food_owed, rates)

    def w_pay(player_state, food_owed, rates):
        _counters["food_payment (clip-by-paid)"][
            (_feed_caps(player_state, food_owed, rates), food_owed, rates)] += 1
        return _orig_pay(player_state, food_owed, rates)

    def w_fence(state, p, **kwargs):
        # placement-time scan: subdivision_started is always False here.
        _counters["fence_scan (any_legal)"][(p.farmyard, p.resources.wood)] += 1
        return _orig_fence(state, p, **kwargs)

    H.pareto_frontier = w_pareto
    H.breeding_frontier = w_breed
    H.harvest_feed_frontier = w_feed
    H.food_payment_frontier = w_pay
    L._any_legal_pasture_commit = w_fence


def _load_cfg(path: str):
    from agricola.agents import DEFAULT_CONFIG_V3, HeuristicConfigV3
    if path in ("default_v3", "default"):
        return DEFAULT_CONFIG_V3
    with open(path) as f:
        return HeuristicConfigV3(**json.load(f)["best_config"])


def collision(sims: int, seed: int, v3_config: str) -> None:
    # Patch BEFORE constructing agents / playing.
    _install_wrappers()

    from agricola.agents import (
        HubrisHeuristicV3, MCTSAgent, MCTSSearch,
        make_strict_restricted_legal_actions,
    )
    from agricola.agents.base import play_game
    from agricola.setup import setup, setup_env

    cfg = _load_cfg(v3_config)
    search = MCTSSearch(evaluator_config=cfg, n_random_fencing=4, rng_seed=seed)
    mcts = MCTSAgent(
        search, sims_per_move=sims, c_uct=1.0, fpu_offset=0.0,
        action_selection_temperature=0.2, rng_seed=seed,
    )
    strict_fn = make_strict_restricted_legal_actions(
        config=cfg, rng=np.random.default_rng(seed ^ 0xC0FFEE),
    )
    heur = HubrisHeuristicV3(
        seed=seed + 1, temperature=0.0, lookahead="turn",
        config=cfg, legal_actions_fn=strict_fn,
    )

    initial, env = setup_env(seed)
    play_game(initial, (mcts, heur), env.resolve)

    print(f"\n=== projection-collision over one MCTS game "
          f"(sims={sims}, seed={seed}) ===")
    print("hit rate = fraction of calls a perfect projection cache would "
          "serve from cache (= 1 − distinct/total)\n")
    print(f"{'helper / key':<30} {'calls':>8} {'distinct':>9} {'hit rate':>9}")
    for hname in sorted(_counters):
        c = _counters[hname]
        total = sum(c.values())
        distinct = len(c)
        hit = (total - distinct) / total if total else 0.0
        print(f"{hname:<30} {total:>8} {distinct:>9} {hit:>8.1%}")
    print("\nNote: 'harvest_feed (clipped key)' vs '(exact key)' shows the "
          "extra hits clipping buys (§6.5 Level 2/3).")


# ---------------------------------------------------------------------------

def _set_level(level: int) -> None:
    """Forward-looking hook: set PARETO_OPT_LEVEL once opt_config exists.

    Today opt_config doesn't exist and the helpers don't read the flag, so this
    is a no-op except for the warning. Collision hit rates are a workload
    property (implementation-independent); microbench at >0 only differs once
    the optimization lands.
    """
    if level == 0:
        return
    try:
        import agricola.opt_config as oc
        oc.PARETO_OPT_LEVEL = level
        print(f"[set PARETO_OPT_LEVEL = {level}]")
    except ImportError:
        print(f"WARNING: agricola/opt_config.py not found — --level {level} "
              f"ignored (optimization not implemented yet).")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["microbench", "collision", "both"],
                    default="both")
    ap.add_argument("--iters", type=int, default=3000,
                    help="microbench iterations per case")
    ap.add_argument("--sims", type=int, default=200,
                    help="MCTS sims/move for collision mode")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--level", type=int, default=0,
                    help="PARETO_OPT_LEVEL (no-op until opt_config exists)")
    ap.add_argument("--v3-config", type=str,
                    default=str(ROOT / "tuned_configs" / "v3_best.json"))
    args = ap.parse_args()

    _set_level(args.level)

    # microbench first (before collision installs wrappers).
    if args.mode in ("microbench", "both"):
        microbench(args.iters)
    if args.mode in ("collision", "both"):
        collision(args.sims, args.seed, args.v3_config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
