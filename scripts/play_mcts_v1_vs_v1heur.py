"""MCTS-with-V1-leaf vs V1-heuristic head-to-head.

Tests how much MCTS adds on top of the V1 heuristic. Both sides use the
V1 architecture (CONFIG_V1_T2 + HubrisHeuristicV1) so the only
difference between seats is "with MCTS search" vs "without."

P0 = MCTS-V1: V1 leaf eval (evaluate_hubris_v1) + HubrisHeuristicV1 for
              greedy macro-fencing chains + strict-restricted legality
              (the MCTS standard).
P1 = HubrisHeuristicV1 (CONFIG_V1_T2, lookahead='turn', restricted
              legality — matches training-pipeline convention).

Runs at multiple sim budgets in sequence so a single log shows the
scaling. Parallel via multiprocessing.Pool. Streams per-game lines.

Usage:
    python -O scripts/play_mcts_v1_vs_v1heur.py --sims 200 500 --n 40 --jobs 8
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agricola.agents import (
    CONFIG_V1_T2,
    HubrisHeuristicV1,
    MCTSAgent,
    MCTSSearch,
    evaluate_hubris_v1,
    make_strict_restricted_legal_actions,
    restricted_legal_actions,
)
from agricola.agents.base import play_game
from agricola.scoring import score, tiebreaker
from agricola.setup import setup

from play_match import GameResult, MatchResult, _winner


@dataclass(frozen=True)
class _Spec:
    sims_per_move: int
    c_uct: float
    n_random_fencing: int
    fpu_offset: float
    temperature: float
    mcts_as_p1: bool
    leaf_differential: bool


_WORKER_SPEC: _Spec | None = None


def _init_worker(spec: _Spec) -> None:
    global _WORKER_SPEC
    _WORKER_SPEC = spec


def _build_v1_mcts(seed: int, spec: _Spec) -> MCTSAgent:
    """MCTS using V1 leaf eval + V1 heuristic for macros + strict-restricted legality."""
    legal_fn = make_strict_restricted_legal_actions(
        rng=np.random.default_rng(seed),
    )
    v1_heur_for_macros = HubrisHeuristicV1(
        seed=seed, config=CONFIG_V1_T2, lookahead="turn",
        legal_actions_fn=legal_fn,
    )
    search = MCTSSearch(
        evaluator_config=CONFIG_V1_T2,
        evaluator_fn=evaluate_hubris_v1,
        heuristic=v1_heur_for_macros,
        legal_actions_fn=legal_fn,
        n_random_fencing=spec.n_random_fencing,
        rng_seed=seed,
        leaf_differential=spec.leaf_differential,
    )
    return MCTSAgent(
        search,
        sims_per_move=spec.sims_per_move,
        c_uct=spec.c_uct,
        fpu_offset=spec.fpu_offset,
        action_selection_temperature=spec.temperature,
        rng_seed=seed,
    )


def _build_v1_heuristic(seed: int) -> HubrisHeuristicV1:
    """Standalone V1 heuristic with the regular (non-strict) restricted wrapper,
    matching the training-pipeline convention."""
    return HubrisHeuristicV1(
        seed=seed, config=CONFIG_V1_T2, lookahead="turn",
        legal_actions_fn=restricted_legal_actions,
    )


def _play_one_game(seed: int) -> GameResult:
    assert _WORKER_SPEC is not None
    spec = _WORKER_SPEC
    initial = setup(seed=seed)
    if spec.mcts_as_p1:
        p0 = _build_v1_heuristic(seed + 0)
        p1 = _build_v1_mcts(seed + 1, spec)
    else:
        p0 = _build_v1_mcts(seed + 0, spec)
        p1 = _build_v1_heuristic(seed + 1)
    final, _ = play_game(initial, (p0, p1))
    s0, _ = score(final, 0)
    s1, _ = score(final, 1)
    tb0 = tiebreaker(final, 0)
    tb1 = tiebreaker(final, 1)
    return GameResult(
        seed=seed,
        score_p0=s0, score_p1=s1,
        tiebreaker_p0=tb0, tiebreaker_p1=tb1,
        starting_player=initial.starting_player,
        winner=_winner(s0, s1, tb0, tb1),
    )


def _aggregate(games: list[GameResult], elapsed: float) -> MatchResult:
    n = len(games)
    p0_wins = sum(1 for g in games if g.winner == 0)
    p1_wins = sum(1 for g in games if g.winner == 1)
    draws   = sum(1 for g in games if g.winner is None)
    avg_p0  = sum(g.score_p0 for g in games) / n if n else 0.0
    avg_p1  = sum(g.score_p1 for g in games) / n if n else 0.0
    return MatchResult(
        n_games=n,
        p0_wins=p0_wins, p1_wins=p1_wins, draws=draws,
        avg_score_p0=avg_p0, avg_score_p1=avg_p1,
        avg_margin=avg_p0 - avg_p1,
        elapsed_seconds=elapsed,
        per_game=tuple(games),
    )


def run_one_match(sims: int, n_games: int, jobs: int, c_uct: float,
                  n_random_fencing: int, fpu_offset: float,
                  temperature: float, mcts_as_p1: bool,
                  leaf_differential: bool) -> MatchResult:
    spec = _Spec(
        sims_per_move=sims,
        c_uct=c_uct,
        n_random_fencing=n_random_fencing,
        fpu_offset=fpu_offset,
        temperature=temperature,
        mcts_as_p1=mcts_as_p1,
        leaf_differential=leaf_differential,
    )
    p0_name = "v1_heur" if mcts_as_p1 else "mcts_v1"
    p1_name = "mcts_v1" if mcts_as_p1 else "v1_heur"

    print(f"\n{'='*80}", flush=True)
    print(f"Match: P0={p0_name} vs P1={p1_name}  |  sims={sims}, "
          f"n={n_games}, jobs={jobs}", flush=True)
    print(f"{'='*80}", flush=True)

    seeds = list(range(n_games))
    games: list[GameResult] = []
    t0 = time.perf_counter()

    def _emit(g: GameResult, completed: int) -> None:
        wins = sum(1 for x in games if x.winner == 0)
        losses = sum(1 for x in games if x.winner == 1)
        draws = sum(1 for x in games if x.winner is None)
        elapsed = time.perf_counter() - t0
        rate = elapsed / completed
        remaining = rate * (n_games - completed)
        margin = sum(x.score_p0 - x.score_p1 for x in games) / completed
        winner_str = ("P0" if g.winner == 0 else "P1" if g.winner == 1 else "tie")
        print(
            f"  [{completed:>3}/{n_games}] seed={g.seed:>3} "
            f"{p0_name}={g.score_p0:>3} {p1_name}={g.score_p1:>3} → {winner_str:>3} | "
            f"tally {p0_name} {wins}-{draws}-{losses} {p1_name}, "
            f"avg margin {margin:+.2f} | "
            f"elapsed {elapsed/60:.1f}m, ETA {remaining/60:.1f}m",
            flush=True,
        )

    if jobs <= 1:
        _init_worker(spec)
        for i, s in enumerate(seeds, start=1):
            g = _play_one_game(s)
            games.append(g)
            _emit(g, i)
    else:
        with Pool(processes=jobs, initializer=_init_worker, initargs=(spec,)) as pool:
            for i, g in enumerate(
                pool.imap_unordered(_play_one_game, seeds, chunksize=1),
                start=1,
            ):
                games.append(g)
                _emit(g, i)
        games.sort(key=lambda g: g.seed)

    elapsed = time.perf_counter() - t0
    result = _aggregate(games, elapsed)
    print(flush=True)
    mcts_label = p0_name if not mcts_as_p1 else p1_name
    print(f"FINAL @ sims={sims}: {p0_name} {result.p0_wins}-{result.draws}-{result.p1_wins} {p1_name}  "
          f"avg {p0_name}={result.avg_score_p0:+.2f}  "
          f"{p1_name}={result.avg_score_p1:+.2f}  "
          f"margin (P0-P1) = {result.avg_margin:+.2f}  "
          f"({mcts_label} = MCTS side)",
          flush=True)
    print(f"Wall: {elapsed/60:.1f} min  ({elapsed/n_games:.1f}s/game)", flush=True)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=40, help="Games per sim budget. Default 40.")
    ap.add_argument("--sims", type=int, nargs="+", default=[200, 500],
                    help="One or more sim-per-move values to run in sequence. Default: 200 500.")
    ap.add_argument("--c-uct", type=float, default=1.4)
    ap.add_argument("--n-random-fencing", type=int, default=4)
    ap.add_argument("--fpu-offset", type=float, default=0.0)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--mcts-as-p1", action="store_true",
                    help="Place MCTS-V1 at P1 (default P0).")
    ap.add_argument("--leaf-differential", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="If set (default), MCTS leaf uses e(p0)-e(p1). "
                         "Use --no-leaf-differential to fall back to e(p0) only.")
    args = ap.parse_args()

    print(f"MCTS-V1 vs V1-heuristic — head-to-head over multiple sim budgets")
    print(f"  Sim budgets: {args.sims}")
    print(f"  Games per budget: {args.n}  |  jobs: {args.jobs}")
    print(f"  MCTS leaf eval: evaluate_hubris_v1 + CONFIG_V1_T2")
    print(f"  MCTS macros: HubrisHeuristicV1 + strict_restricted_legal_actions")
    print(f"  V1 heuristic opponent: HubrisHeuristicV1 + CONFIG_V1_T2 + lookahead='turn'")
    print(f"  V1 heuristic legality: restricted_legal_actions (regular)")

    print(f"  leaf_differential: {args.leaf_differential}")
    all_results: list[tuple[int, MatchResult]] = []
    for sims in args.sims:
        r = run_one_match(
            sims=sims, n_games=args.n, jobs=args.jobs,
            c_uct=args.c_uct, n_random_fencing=args.n_random_fencing,
            fpu_offset=args.fpu_offset, temperature=args.temperature,
            mcts_as_p1=args.mcts_as_p1,
            leaf_differential=args.leaf_differential,
        )
        all_results.append((sims, r))

    # Final summary across budgets
    print(f"\n{'='*80}", flush=True)
    print(f"OVERALL SUMMARY — MCTS-V1 lift over V1-heuristic, by sim budget", flush=True)
    print(f"{'='*80}", flush=True)
    print(f"{'sims':>6} {'mcts_wins':>10} {'draws':>6} {'mcts_losses':>11} "
          f"{'margin (mcts-heur)':>20}", flush=True)
    for sims, r in all_results:
        # If MCTS is P0: margin (P0-P1) IS mcts margin. Else flip sign.
        mcts_margin = r.avg_margin if not args.mcts_as_p1 else -r.avg_margin
        mcts_w = r.p0_wins if not args.mcts_as_p1 else r.p1_wins
        mcts_l = r.p1_wins if not args.mcts_as_p1 else r.p0_wins
        print(f"{sims:>6} {mcts_w:>10} {r.draws:>6} {mcts_l:>11} {mcts_margin:>+20.2f}",
              flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
