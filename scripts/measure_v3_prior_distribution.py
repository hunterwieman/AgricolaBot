"""Measure HubrisHeuristicV3's implied prior distribution at various
softmax temperatures.

At each multi-option decision in a self-match game, compute the V3
evaluator's per-candidate score, apply softmax at multiple τ values, and
record per-decision statistics (max probability, # actions with p > 0.05,
entropy, top-1/top-2 raw score gap, etc.).

Aggregated by decision-type category (`PlaceWorker`, `PendingBuildFences`,
`PendingSow`, ...) and τ. Used to inform τ_prior and ε choices for MCTS
PUCT prior design.

Usage:
    python -O scripts/measure_v3_prior_distribution.py \\
        --config tuned_configs/v3_best.json --n-games 5
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents.base import decider_of
from agricola.agents.heuristic import (
    HeuristicConfigV3, HubrisHeuristicV3, evaluate_hubris_v3,
)
from agricola.agents.restricted import restricted_legal_actions
from agricola.constants import Phase
from agricola.engine import step
from agricola.setup import setup
from tests.test_utils import filter_implemented


# τ values to sweep. Includes very-low (sharp), 1.0 (canonical), and
# high (diffuse) for a range of policy peakedness.
TAUS: tuple[float, ...] = (0.1, 0.3, 0.5, 1.0, 2.0, 5.0)


def softmax(scores: list[float], tau: float) -> list[float]:
    """Numerically stable softmax with temperature."""
    if tau <= 0:
        # Degenerate "argmax" — all mass on top score(s), split among ties.
        m = max(scores)
        ties = [i for i, s in enumerate(scores) if s == m]
        return [1.0 / len(ties) if i in ties else 0.0 for i in range(len(scores))]
    m = max(scores)
    exps = [math.exp((s - m) / tau) for s in scores]
    z = sum(exps)
    return [e / z for e in exps]


def entropy(probs: list[float]) -> float:
    """Shannon entropy in nats."""
    return -sum(p * math.log(p) for p in probs if p > 0)


def quantile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    idx = q * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def categorize(state) -> str:
    if not state.pending_stack:
        return "PlaceWorker"
    return type(state.pending_stack[-1]).__name__


def play_and_instrument(seed: int, cfg, agent_factory, legal_actions_fn) -> list[dict]:
    """Play one game, recording at each multi-option decision the V3 score
    distribution + per-τ softmax stats."""
    state = setup(seed=seed)
    agents = (agent_factory(seed), agent_factory(seed + 1))
    records: list[dict] = []

    while state.phase != Phase.BEFORE_SCORING:
        decider = decider_of(state)
        actions = filter_implemented(legal_actions_fn(state))
        if not actions:
            break

        if len(actions) > 1:
            # Score each candidate from the decider's perspective.
            scores = [evaluate_hubris_v3(step(state, a), decider, cfg) for a in actions]
            n = len(actions)
            sorted_scores = sorted(scores, reverse=True)
            top1_top2_gap = sorted_scores[0] - sorted_scores[1] if n >= 2 else 0.0
            top1_median_gap = sorted_scores[0] - sorted_scores[len(sorted_scores) // 2]

            base_record = {
                "seed":              seed,
                "round":             state.round_number,
                "category":          categorize(state),
                "n":                 n,
                "top1_top2_gap":     top1_top2_gap,
                "top1_median_gap":   top1_median_gap,
                "score_range":       sorted_scores[0] - sorted_scores[-1],
            }

            per_tau = {}
            for tau in TAUS:
                probs = softmax(scores, tau)
                per_tau[f"tau_{tau}"] = {
                    "max_prob":       max(probs),
                    "top2_mass":      sum(sorted(probs, reverse=True)[:2]),
                    "top3_mass":      sum(sorted(probs, reverse=True)[:3]),
                    "n_above_005":    sum(1 for p in probs if p > 0.05),
                    "n_above_001":    sum(1 for p in probs if p > 0.01),
                    "entropy":        entropy(probs),
                    # Normalized entropy: 0 = degenerate, 1 = uniform.
                    "entropy_norm":   entropy(probs) / math.log(n) if n > 1 else 0.0,
                }
            base_record["per_tau"] = per_tau
            records.append(base_record)

        # Play the actual action (using the agent so the game flows naturally).
        action = agents[decider](state)
        state = step(state, action)

    return records


def summarize(records: list[dict]) -> None:
    """Print per-category × per-τ stats."""
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in records:
        by_cat[r["category"]].append(r)

    # Overall N distribution per category
    print("\n" + "=" * 95)
    print("LEGAL-ACTION COUNT (N) PER CATEGORY")
    print("=" * 95)
    print(f"{'Category':<32} {'#calls':>6} {'N min':>6} {'N p50':>6} {'N p95':>6} {'N max':>6} {'avg gap top1-top2':>20}")
    print("-" * 95)
    for cat in sorted(by_cat):
        recs = by_cat[cat]
        ns = [r["n"] for r in recs]
        gaps = [r["top1_top2_gap"] for r in recs]
        print(f"{cat:<32} {len(recs):>6} {min(ns):>6} {int(quantile(ns, 0.5)):>6} "
              f"{int(quantile(ns, 0.95)):>6} {max(ns):>6} {sum(gaps)/len(gaps):>20.3f}")

    # Per τ
    for tau in TAUS:
        print("\n" + "=" * 95)
        print(f"PROBABILITY STATS AT τ = {tau}")
        print("=" * 95)
        print(f"{'Category':<32} {'avg max_p':>10} {'avg #p>.05':>11} {'avg #p>.01':>11} "
              f"{'avg top2':>10} {'avg entropy':>12} {'norm-entropy':>13}")
        print("-" * 95)
        for cat in sorted(by_cat):
            recs = by_cat[cat]
            ts = [r["per_tau"][f"tau_{tau}"] for r in recs]
            n_calls = len(recs)
            print(f"{cat:<32} "
                  f"{sum(t['max_prob'] for t in ts)/n_calls:>10.3f} "
                  f"{sum(t['n_above_005'] for t in ts)/n_calls:>11.2f} "
                  f"{sum(t['n_above_001'] for t in ts)/n_calls:>11.2f} "
                  f"{sum(t['top2_mass'] for t in ts)/n_calls:>10.3f} "
                  f"{sum(t['entropy'] for t in ts)/n_calls:>12.3f} "
                  f"{sum(t['entropy_norm'] for t in ts)/n_calls:>13.3f}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path,
                    default=ROOT / "tuned_configs" / "v3_best.json")
    p.add_argument("--n-games", type=int, default=5)
    p.add_argument("--seed-start", type=int, default=0)
    p.add_argument("--restricted", action=argparse.BooleanOptionalAction,
                    default=True)
    p.add_argument("--output", type=Path, default=None,
                    help="Optional JSON path for raw records.")
    args = p.parse_args()

    with args.config.open() as f:
        cfg = HeuristicConfigV3(**json.load(f)["best_config"])

    if args.restricted:
        laf = restricted_legal_actions
    else:
        from agricola.legality import legal_actions
        laf = legal_actions

    def agent_factory(seed: int):
        # temperature=0 for actual play (so the game flows along its modal
        # trajectory); we measure the distribution shape independently.
        return HubrisHeuristicV3(seed=seed, config=cfg, lookahead="turn",
                                  legal_actions_fn=laf, temperature=0.0)

    print(f"Measuring V3 prior distribution across {args.n_games} self-match games")
    print(f"  config: {args.config}")
    print(f"  restricted: {args.restricted}")
    print(f"  τ sweep: {TAUS}")
    print()

    all_records: list[dict] = []
    t0 = time.time()
    for i in range(args.n_games):
        seed = args.seed_start + i
        t_game = time.time()
        records = play_and_instrument(seed, cfg, agent_factory, laf)
        print(f"  seed {seed}: {len(records)} multi-option decisions, "
              f"wall {time.time()-t_game:.1f}s")
        all_records.extend(records)

    print(f"\nTotal: {len(all_records)} decisions across {args.n_games} games, "
          f"wall {time.time()-t0:.1f}s")

    summarize(all_records)

    if args.output:
        with args.output.open("w") as f:
            json.dump(all_records, f, indent=2)
        print(f"\nRaw records saved to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
