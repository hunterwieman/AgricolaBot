"""Evaluate a search agent (UCT/PUCT, cap ON, NN leaf) vs the 8-config
data-gen heuristic ensemble (tuned_configs/DATA_GEN_ENSEMBLE.md).

The search agent is always P0; each opponent is one ensemble heuristic as P1,
built the same way the ensemble eval builds them (HubrisHeuristicV1/V3,
turn-lookahead, T=0, regular `restricted_legal_actions` — matching how the
configs were tuned). Single-seat (P0 fixed): one consistent-seat run over many
seeds averages the starting-player advantage, so no seat-swapping (project
convention). The same seed set is reused across opponents (common random
numbers) to reduce variance in the per-opponent comparison.

The PUCT/UCT agent is built by run_search_tournament.build_agent, so this
matches the tournament's agent exactly (cap_total_sims ON, NN leaf nn_models/best).

    python scripts/eval_search_vs_ensemble.py --policy puct --c 0.5 --sims 400 --n 30
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import json  # noqa: E402

from run_search_tournament import Cfg, build_agent, _init_worker  # noqa: E402
from play_match import _winner  # noqa: E402  (scripts/play_match.py)

from agricola.agents import (  # noqa: E402
    CONFIG_V1_T2,
    HeuristicConfig,
    HeuristicConfigV3,
    HubrisHeuristicV1,
    HubrisHeuristicV3,
    restricted_legal_actions,
)
from agricola.agents.base import play_game  # noqa: E402
from agricola.scoring import score, tiebreaker  # noqa: E402
from agricola.setup import setup_env  # noqa: E402


def _load_heuristic_config(spec: str, arch: str):
    """t2 → V1 CONFIG_V1_T2; else a tuned JSON's `best_config`. Mirrors
    scripts/nn/play_match._load_heuristic_config."""
    if spec == "t2":
        return CONFIG_V1_T2
    with Path(spec).open("r") as f:
        cfg_dict = json.load(f)["best_config"]
    return HeuristicConfigV3(**cfg_dict) if arch == "v3" else HeuristicConfig(**cfg_dict)

# DATA_GEN_ENSEMBLE.md order: (spec, arch).
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

# Globals stashed in each worker (the agent spec + the opponent configs).
_AGENT_CFG: Cfg | None = None
_OPP_CFGS: dict | None = None


def _init(agent_cfg: Cfg, opp_cfgs: dict) -> None:
    _init_worker()  # caches ON
    global _AGENT_CFG, _OPP_CFGS
    _AGENT_CFG = agent_cfg
    _OPP_CFGS = opp_cfgs


def _build_opponent(spec: str, arch: str, seed: int):
    cfg = _OPP_CFGS[spec]
    cls = HubrisHeuristicV1 if arch == "v1" else HubrisHeuristicV3
    return cls(
        seed=seed, temperature=0.0, lookahead="turn",
        config=cfg, legal_actions_fn=restricted_legal_actions,
    )


def play_one(task: tuple) -> dict:
    spec, arch, seed = task
    initial, env = setup_env(seed=seed)
    p0 = build_agent(_AGENT_CFG, seed)             # search agent (P0)
    p1 = _build_opponent(spec, arch, seed + 1)     # ensemble heuristic (P1)
    final, _ = play_game(initial, (p0, p1), env.resolve)
    s0, _ = score(final, 0)
    s1, _ = score(final, 1)
    tb0 = tiebreaker(final, 0)
    tb1 = tiebreaker(final, 1)
    return {"spec": spec, "seed": seed, "s0": s0, "s1": s1,
            "winner": _winner(s0, s1, tb0, tb1)}


def main() -> None:
    import multiprocessing as mp

    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--policy", choices=["uct", "puct"], default="puct")
    p.add_argument("--c", type=float, default=0.5)
    p.add_argument("--sims", type=int, default=400)
    p.add_argument("--n", type=int, default=30, help="games per opponent")
    p.add_argument("--seed-start", type=int, default=0)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    args = p.parse_args()

    agent_cfg = Cfg(args.policy, args.c, args.sims)
    opp_cfgs = {spec: _load_heuristic_config(spec, arch) for spec, arch in ENSEMBLE}

    seeds = list(range(args.seed_start, args.seed_start + args.n))
    tasks = [(spec, arch, s) for (spec, arch) in ENSEMBLE for s in seeds]

    print(f"{agent_cfg.name} (cap ON, NN leaf) vs 8-config ensemble | "
          f"{args.n} games/opp, P0=search, {args.jobs} workers\n", flush=True)
    print(f"{'opponent':<24} {'W-L-D':>10} {'win%':>7} {'margin':>8}", flush=True)
    print("-" * 53, flush=True)

    by_opp: dict[str, list] = {spec: [] for spec, _ in ENSEMBLE}
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.jobs, initializer=_init, initargs=(agent_cfg, opp_cfgs)) as pool:
        for res in pool.imap_unordered(play_one, tasks, chunksize=1):
            by_opp[res["spec"]].append(res)

    tw = tl = td = 0
    msum = 0.0
    for spec, _ in ENSEMBLE:
        rs = by_opp[spec]
        w = sum(1 for r in rs if r["winner"] == 0)
        l = sum(1 for r in rs if r["winner"] == 1)
        d = sum(1 for r in rs if r["winner"] is None)
        marg = sum(r["s0"] - r["s1"] for r in rs) / len(rs) if rs else 0.0
        tw += w; tl += l; td += d; msum += marg
        name = spec.replace("tuned_configs/", "").replace(".json", "")
        dec = max(w + l, 1)
        print(f"{name:<24} {w:>3}-{l:<3}-{d:<3} {100*w/dec:>6.1f}% {marg:>+7.2f}",
              flush=True)

    print("-" * 53, flush=True)
    dec = max(tw + tl, 1)
    print(f"{'AGGREGATE':<24} {tw}-{tl}-{td}  {100*tw/dec:.1f}%  "
          f"avg margin {msum/len(ENSEMBLE):+.2f}  ({tw+tl+td} games)", flush=True)
    print(f"\n{time.time()-t0:.0f}s total", flush=True)


if __name__ == "__main__":
    main()
