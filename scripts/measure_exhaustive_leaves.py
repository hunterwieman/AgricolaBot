"""Measure the cost of exhaustive sub-tree lookahead before implementing it.

Walks the sub-action tree owned by the decider at each multi-option decision
point in a self-match game, COUNTING the number of leaves (i.e., terminal
states where an exhaustive lookahead would call the evaluator) without
actually evaluating them.

Why: the current `HeuristicAgent(lookahead="turn")` greedily descends through
the decider's chain (O(chain_length × branching)). Replacing that with full
exhaustive sub-tree search would be O(branching^chain_length) — potentially
intractable for spaces like Fencing where each `PendingBuildFences` step can
offer ~100 pasture commits. This script measures the actual distribution so
we can decide between:

- Full exhaustive everywhere (if all chains stay small)
- Shape A: exhaustive for all non-Fencing chains, greedy for Fencing
- Shape B: per-chain leaf cap with greedy fallback above the cap

Output: per-call-site category, count of decisions, leaf-count quantiles
(50th / 95th / max), and total game-wide leaf count = exhaustive evaluator
calls per game.

Usage:
    python -O scripts/measure_exhaustive_leaves.py \\
        --config tuned_configs/v3_best.json --n-games 10
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents.heuristic import HeuristicConfigV3, HubrisHeuristicV3
from agricola.agents.base import decider_of
from agricola.agents.restricted import restricted_legal_actions
from agricola.constants import Phase
from agricola.engine import step
from agricola.setup import setup
from tests.test_utils import filter_implemented


# Maximum leaves to expand before short-circuiting. Set high enough not to
# bias typical chains but low enough to keep the script tractable when
# Fencing-style explosions happen. Returns the cap value as the count
# (with a "censored" marker in the call record).
LEAF_CAP = 200_000


def count_leaves(state, decider: int, legal_actions_fn,
                  cap: int = LEAF_CAP) -> tuple[int, bool]:
    """Count the number of terminal states (handoff to opponent / game end /
    no legal actions) reachable from `state` by the decider's chain of
    decisions. Singletons are stepped through transparently.

    Returns (count, censored). `censored=True` means we hit the cap and the
    actual count is >= cap.
    """
    return _count_leaves_recursive(state, decider, legal_actions_fn, cap, [0])


def _count_leaves_recursive(state, decider: int, legal_actions_fn,
                             cap: int, counter: list[int]) -> tuple[int, bool]:
    # Skip singletons (no evaluator call would happen at these positions)
    while True:
        if state.phase == Phase.BEFORE_SCORING:
            counter[0] += 1
            return 1, False
        if decider_of(state) != decider:
            counter[0] += 1
            return 1, counter[0] >= cap
        actions = filter_implemented(legal_actions_fn(state))
        if not actions:
            counter[0] += 1
            return 1, counter[0] >= cap
        if len(actions) == 1:
            state = step(state, actions[0])
            continue
        break

    # Multi-option decision — recurse on each
    total = 0
    censored = False
    for a in actions:
        if counter[0] >= cap:
            censored = True
            break
        cand = step(state, a)
        sub_count, sub_censored = _count_leaves_recursive(
            cand, decider, legal_actions_fn, cap, counter)
        total += sub_count
        if sub_censored:
            censored = True
            break
    return total, censored


def categorize_decision(state) -> str:
    """Label the decision-type at this state.

    Empty stack → "PlaceWorker" (top-level worker placement).
    Non-empty stack → name of the top pending frame's class.
    """
    if not state.pending_stack:
        return "PlaceWorker"
    return type(state.pending_stack[-1]).__name__


def play_instrumented_game(seed: int, agent_factory, legal_actions_fn) -> list[dict]:
    """Play a single game, recording at each multi-option decision the
    number of exhaustive leaves per top-level action AND the total. Returns
    list of records, one per decision point.
    """
    state = setup(seed=seed)
    agents = (agent_factory(seed), agent_factory(seed + 1))
    records: list[dict] = []

    while state.phase != Phase.BEFORE_SCORING:
        decider = decider_of(state)
        actions = filter_implemented(legal_actions_fn(state))
        if not actions:
            # Shouldn't happen in a real game but be defensive.
            break

        if len(actions) > 1:
            # Multi-option decision — measure exhaustive leaves per top-level action
            category = categorize_decision(state)
            leaf_counts: list[int] = []
            total_censored = False
            for a in actions:
                cand = step(state, a)
                count, censored = count_leaves(cand, decider, legal_actions_fn)
                leaf_counts.append(count)
                if censored:
                    total_censored = True
            records.append({
                "seed":           seed,
                "round":          state.round_number,
                "category":       category,
                "num_top_actions": len(actions),
                "total_leaves":   sum(leaf_counts),
                "max_leaf":       max(leaf_counts),
                "leaf_counts":    leaf_counts,
                "censored":       total_censored,
            })

        # Have the right agent pick the next action and step forward
        action = agents[decider](state)
        state = step(state, action)

    return records


def quantile(xs: list[float], q: float) -> float:
    """Simple linear-interp quantile (avoid numpy import overhead here)."""
    if not xs:
        return 0.0
    s = sorted(xs)
    idx = q * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def summarize(all_records: list[dict]) -> None:
    """Aggregate by category, print histograms + per-game totals."""
    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in all_records:
        by_cat[r["category"]].append(r)

    print()
    print("=" * 90)
    print("PER-CATEGORY LEAF COUNTS (sum across top-level actions per call site)")
    print("=" * 90)
    fmt = ("{cat:32s}  {n:>6s}  {p50:>10s}  {p95:>10s}  {pmax:>12s}  "
           "{any_cens:>8s}  {chain_p95:>10s}")
    print(fmt.format(cat="Category", n="#calls", p50="total p50",
                      p95="total p95", pmax="total max",
                      any_cens="censored",
                      chain_p95="chain-p95"))
    print("-" * 90)
    for cat in sorted(by_cat):
        recs = by_cat[cat]
        totals = [r["total_leaves"] for r in recs]
        # "chain p95" = 95th percentile of per-top-action leaf counts (not
        # summed) — tells us the worst single-chain expansion.
        chain_counts = [c for r in recs for c in r["leaf_counts"]]
        censored_count = sum(1 for r in recs if r["censored"])
        print(fmt.format(
            cat=cat,
            n=str(len(recs)),
            p50=f"{quantile(totals, 0.5):.0f}",
            p95=f"{quantile(totals, 0.95):.0f}",
            pmax=f"{max(totals):.0f}",
            any_cens=f"{censored_count}/{len(recs)}",
            chain_p95=f"{quantile(chain_counts, 0.95):.0f}",
        ))

    print()
    print("=" * 90)
    print("PER-GAME TOTAL LEAVES (= would-be exhaustive evaluator calls per game)")
    print("=" * 90)
    by_seed: dict[int, int] = defaultdict(int)
    for r in all_records:
        by_seed[r["seed"]] += r["total_leaves"]
    per_game = sorted(by_seed.values())
    print(f"  n_games: {len(per_game)}")
    print(f"  per-game leaves: min={per_game[0]:,}  p50={int(quantile(per_game, 0.5)):,}  "
          f"p95={int(quantile(per_game, 0.95)):,}  max={per_game[-1]:,}")
    print()
    grand_total = sum(per_game)
    avg = grand_total / len(per_game) if per_game else 0
    print(f"  avg leaves per game: {avg:,.0f}")
    print(f"  total leaves across all games: {grand_total:,}")

    # Cost interpretation
    print()
    print("=" * 90)
    print("COST INTERPRETATION")
    print("=" * 90)
    # Approximate eval-call cost: very rough estimate of ~50us per evaluator
    # call (V3 is reasonably heavy). Print converted to seconds per game.
    eval_us = 50
    extra_sec_per_game = avg * eval_us / 1_000_000
    # The CURRENT cost per game from greedy descent: looking at recent
    # matches, V3 self-match takes ~0.4 sec per game. So this gives us
    # a slowdown ratio estimate.
    current_sec_per_game = 0.4  # rough from recent measurements
    print(f"  Assuming ~{eval_us} us per evaluator call (V3 self-eval estimate)")
    print(f"  Exhaustive eval cost: {extra_sec_per_game:.2f} sec per game (just for evals)")
    print(f"  Current greedy total: ~{current_sec_per_game:.2f} sec per game (measured)")
    if current_sec_per_game > 0:
        ratio = extra_sec_per_game / current_sec_per_game
        print(f"  Approx slowdown ratio: {ratio:.1f}× (rough; ignores step() cost in expansion)")

    print()
    print("=" * 90)
    print("PER-CATEGORY LEAVES (totals across all games)")
    print("=" * 90)
    cat_totals = sorted(
        ((cat, sum(r["total_leaves"] for r in recs)) for cat, recs in by_cat.items()),
        key=lambda x: -x[1],
    )
    grand = sum(t for _, t in cat_totals)
    for cat, t in cat_totals:
        pct = 100.0 * t / grand if grand else 0
        print(f"  {cat:32s}  {t:>10,}  ({pct:5.1f}%)")
    print()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path,
                    default=ROOT / "tuned_configs" / "v3_best.json",
                    help="Path to a tuned config JSON. Default v3_best.json.")
    p.add_argument("--n-games", type=int, default=5,
                    help="Number of self-match games to instrument. Default 5.")
    p.add_argument("--seed-start", type=int, default=0,
                    help="First seed; games use seeds [start, start+n).")
    p.add_argument("--restricted", action=argparse.BooleanOptionalAction,
                    default=True, help="Use restricted_legal_actions. Default True.")
    p.add_argument("--output", type=Path, default=None,
                    help="Optional JSON output path for raw records. "
                         "Default: print summary only.")
    args = p.parse_args()

    with args.config.open() as f:
        cfg = HeuristicConfigV3(**json.load(f)["best_config"])

    laf = restricted_legal_actions if args.restricted else None
    if laf is None:
        from agricola.legality import legal_actions
        laf = legal_actions

    def agent_factory(seed: int):
        return HubrisHeuristicV3(seed=seed, config=cfg, lookahead="turn",
                                  legal_actions_fn=laf)

    print(f"Measuring exhaustive-subtree leaves on {args.n_games} self-match games")
    print(f"  config: {args.config}")
    print(f"  restricted: {args.restricted}")
    print(f"  seeds: {args.seed_start}..{args.seed_start + args.n_games - 1}")
    print()

    all_records: list[dict] = []
    t0 = time.time()
    for i in range(args.n_games):
        seed = args.seed_start + i
        t_game = time.time()
        records = play_instrumented_game(seed, agent_factory, laf)
        elapsed = time.time() - t_game
        total_leaves = sum(r["total_leaves"] for r in records)
        censored_count = sum(1 for r in records if r["censored"])
        print(f"  seed {seed}: {len(records)} multi-option decisions, "
              f"total leaves = {total_leaves:,}, "
              f"censored {censored_count}, "
              f"wall {elapsed:.1f}s")
        all_records.extend(records)

    total_elapsed = time.time() - t0
    print()
    print(f"Total wall time: {total_elapsed:.1f}s")
    print(f"Total decisions across games: {len(all_records)}")

    summarize(all_records)

    if args.output:
        with args.output.open("w") as f:
            json.dump(all_records, f, indent=2)
        print(f"\nRaw records saved to {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
