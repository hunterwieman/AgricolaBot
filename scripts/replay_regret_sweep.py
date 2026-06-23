"""Measure how much play-strength the 800-sim production budget leaves on the
table, vs a deep 16k-sim reference, across the 2x2 grid (c_uct in {0.5,1.0}) x
(prior_mix in {0,0.05}).

Phase 1: generate on-policy decision positions by self-play (c_uct=1.0, mix=0,
         played-move temperature 0.7 for diversity, 800 sims).
Phase 2: for each position run a 16k-sim reference (c_uct=1.0, mix=0.05) and the
         four 800-sim bot conditions; regret = ref_Q(ref's most-visited move) -
         ref_Q(bot's chosen move), in margin points (the reference is the common
         yardstick). Reports agreement rate, mean/median/p90 regret, and blunder
         rate (regret > 0.5 pts) per condition.

Caveat: the 16k reference is a search-DEPTH proxy for "best", not ground truth
(same net both sides) — it measures whether 800 sims extracts what the net
knows, not whether the net is right.
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("OMP_NUM_THREADS", "1")

import numpy as np

from agricola.setup import setup_env
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.canonical import dumps
from agricola.constants import Phase
from agricola.agents.base import decider_of
from agricola.agents.nn.trace_replay import action_from_params

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cpp" / "build"))
import agricola_cpp  # noqa: E402

EXPORT = str(ROOT / "nn_models" / "cpp_export_best")
OUT_DIR = ROOT / "regret_out"
OUT_DIR.mkdir(exist_ok=True)
POS_CACHE = OUT_DIR / "positions.json"
N_GAMES = 8
BOT_SIMS = 800
REF_SIMS = 24000
REF_CUCT, REF_MIX = 2.0, 0.05
CONDITIONS = [(0.5, 0.0), (0.5, 0.05), (1.0, 0.0), (1.0, 0.05)]
BLUNDER = 0.5  # points


def aj_to_action(aj):
    d = json.loads(aj) if isinstance(aj, str) else aj
    return action_from_params(d["type"], d["params"])


def label(aj):
    d = json.loads(aj) if isinstance(aj, str) else aj
    p = d.get("params", {})
    return d["type"] + ":" + json.dumps(p, sort_keys=True)


# ---------------------------------------------------------------- phase 1
def generate_positions():
    positions = []
    for seed in range(N_GAMES):
        state, env = setup_env(seed)
        rng = np.random.default_rng(1000 + seed)
        while state.phase != Phase.BEFORE_SCORING:
            d = decider_of(state)
            if d is None:  # nature reveal — resolve via env
                state = step(state, env.reveal_action(state))
                continue
            legal = legal_actions(state)
            if len(legal) == 1:
                state = step(state, legal[0])
                continue
            sj = dumps(state)
            dbg = agricola_cpp.mcts_debug_root(EXPORT, sj, BOT_SIMS, 1.0, int(seed), 0.0)
            positions.append(sj)
            vd = dbg["visit_distribution"]
            counts = np.array([n for _, n in vd], dtype=float)
            w = counts ** (1.0 / 0.7)
            idx = rng.choice(len(vd), p=w / w.sum())
            state = step(state, aj_to_action(vd[idx][0]))
        print(f"  game seed={seed}: {len(positions)} positions so far", flush=True)
    POS_CACHE.write_text(json.dumps(positions))
    return positions


# ---------------------------------------------------------------- phase 2
def measure(sj):
    ref = agricola_cpp.mcts_debug_root(EXPORT, sj, REF_SIMS, REF_CUCT, 0, REF_MIX)
    # ref Q per action label (q is value_scale-scaled margin, root/human frame)
    refq, refvis = {}, {}
    for row in ref["children_detail"]:
        lab = label(row[0])
        refvis[lab] = row[2]
        refq[lab] = row[3]
    refvd = sorted(ref["visit_distribution"], key=lambda pr: -pr[1])
    ref_best = label(refvd[0][0])
    ref_best_q = refq.get(ref_best)
    out = {}
    for (c, m) in CONDITIONS:
        bot = agricola_cpp.mcts_debug_root(EXPORT, sj, BOT_SIMS, c, 0, m)
        bvd = sorted(bot["visit_distribution"], key=lambda pr: -pr[1])
        bot_move = label(bvd[0][0])
        bq = refq.get(bot_move)
        agree = (bot_move == ref_best)
        regret = (ref_best_q - bq) if (bq is not None and ref_best_q is not None) else None
        out[f"{c}_{m}"] = {"agree": agree, "regret": regret,
                           "off_ref": bq is None}
    return out


def main():
    if POS_CACHE.exists():
        positions = json.loads(POS_CACHE.read_text())
        print(f"loaded {len(positions)} cached positions", flush=True)
    else:
        print("generating positions...", flush=True)
        positions = generate_positions()
    print(f"measuring regret over {len(positions)} positions "
          f"(ref={REF_SIMS} c_uct={REF_CUCT} mix={REF_MIX}, bot={BOT_SIMS})\n",
          flush=True)

    agg = {f"{c}_{m}": {"agree": 0, "regrets": [], "off_ref": 0, "blunder": 0}
           for (c, m) in CONDITIONS}
    t0 = time.time()
    from multiprocessing import Pool
    n_workers = max(1, (os.cpu_count() or 4) - 2)
    with Pool(n_workers) as pool:
      for i, res in enumerate(pool.imap_unordered(measure, positions, chunksize=4)):
        for k, r in res.items():
            a = agg[k]
            if r["agree"]:
                a["agree"] += 1
            if r["off_ref"]:
                a["off_ref"] += 1
            if r["regret"] is not None:
                a["regrets"].append(r["regret"])
                if r["regret"] > BLUNDER:
                    a["blunder"] += 1
        if (i + 1) % 25 == 0:
            dt = time.time() - t0
            eta = dt / (i + 1) * (len(positions) - i - 1)
            print(f"  {i+1}/{len(positions)}  ({dt:.0f}s, eta {eta:.0f}s)", flush=True)

    n = len(positions)
    print(f"\n=== regret vs {REF_SIMS}-sim reference, {n} positions, bot={BOT_SIMS} sims ===")
    print(f"{'condition':<18}{'agree%':>8}{'mean_reg':>10}{'median':>9}"
          f"{'p90':>8}{'blunder%':>10}{'off_ref':>9}")
    for (c, m) in CONDITIONS:
        a = agg[f"{c}_{m}"]
        regs = np.array(a["regrets"]) if a["regrets"] else np.array([0.0])
        print(f"c_uct={c},mix={m:<6}"
              f"{100*a['agree']/n:>8.1f}"
              f"{regs.mean():>10.3f}"
              f"{np.median(regs):>9.3f}"
              f"{np.percentile(regs,90):>8.3f}"
              f"{100*a['blunder']/n:>10.1f}"
              f"{a['off_ref']:>9}")
    out_path = OUT_DIR / "results.json"
    out_path.write_text(json.dumps({k: {"agree": v["agree"], "off_ref": v["off_ref"],
                                        "blunder": v["blunder"], "regrets": v["regrets"]}
                                    for k, v in agg.items()}))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
