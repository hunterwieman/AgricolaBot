"""MCTS-with-V1-evaluator vs MCTS-with-V3-evaluator head-to-head.

Tests whether the leaf-evaluator choice matters for MCTS strength.
Both seats are MCTS with identical agent-level config (sims/c_uct/etc)
and identical strict-restricted legality (V3-aware harvest-feed cap).
The only difference is the leaf evaluator:

  - P0 (or P1 with --mcts-v1-as-p1): V1 architecture, CONFIG_V1_T2
    leaf eval + HubrisHeuristicV1 for greedy macro-fencing chains.
  - The other seat: V3 architecture, --v3-config or v3_best.json leaf
    eval + HubrisHeuristicV3 for greedy macros.

Parallel via multiprocessing.Pool. Streams per-game lines as games
complete (running tally + ETA).

Usage:
    python -O scripts/play_mcts_v1_vs_v3.py --n 40 --sims 200 --jobs 8

Default opponent positioning: V1-MCTS as P0, V3-MCTS as P1.
"""
from __future__ import annotations

import argparse
import json
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
    CONFIG_V3_T1,
    DEFAULT_CONFIG_V3,
    HeuristicConfigV3,
    HubrisHeuristicV1,
    HubrisHeuristicV3,
    MCTSAgent,
    MCTSSearch,
    evaluate_hubris_v1,
    evaluate_hubris_v3,
    make_strict_restricted_legal_actions,
)
from agricola.agents.base import play_game
from agricola.scoring import score, tiebreaker
from agricola.setup import setup, setup_env

from play_match import GameResult, MatchResult, _winner


# ---------------------------------------------------------------------------
# Spec passed to workers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _Spec:
    v3_config: HeuristicConfigV3
    sims_per_move: int
    c_uct: float
    n_random_fencing: int
    fpu_offset: float
    temperature: float
    v1_as_p1: bool   # If True: V1-MCTS at P1, V3-MCTS at P0


_WORKER_SPEC: _Spec | None = None


def _init_worker(spec: _Spec) -> None:
    global _WORKER_SPEC
    _WORKER_SPEC = spec


# ---------------------------------------------------------------------------
# Agent factories
# ---------------------------------------------------------------------------

def _build_v3_mcts(seed: int, spec: _Spec) -> MCTSAgent:
    """MCTS with V3 leaf eval + V3 heuristic for macros + V3-strict legality."""
    search = MCTSSearch(
        evaluator_config=spec.v3_config,
        evaluator_fn=evaluate_hubris_v3,
        n_random_fencing=spec.n_random_fencing,
        rng_seed=seed,
    )
    return MCTSAgent(
        search,
        sims_per_move=spec.sims_per_move,
        c_uct=spec.c_uct,
        fpu_offset=spec.fpu_offset,
        action_selection_temperature=spec.temperature,
        rng_seed=seed,
    )


def _build_v1_mcts(seed: int, spec: _Spec) -> MCTSAgent:
    """MCTS with V1 leaf eval + V1 heuristic for macros.

    Note: the legality wrapper still uses V3 internally for the
    harvest-feed cap's ranking. That's intentional — the wrapper's cap
    is a LEGALITY concern (which CommitConvert options to surface to
    MCTS), and we want both seats to see the same set of legal commits.
    Only the LEAF evaluator differs between the two seats.
    """
    # Strict-restricted wrapper (V3-aware) for legality. Same as V3-MCTS.
    legal_fn = make_strict_restricted_legal_actions(
        config=spec.v3_config, rng=np.random.default_rng(seed),
    )
    # Heuristic for greedy macro-fencing chains uses V1.
    v1_heuristic = HubrisHeuristicV1(
        seed=seed, config=CONFIG_V1_T2, lookahead="turn",
        legal_actions_fn=legal_fn,
    )
    search = MCTSSearch(
        evaluator_config=CONFIG_V1_T2,
        evaluator_fn=evaluate_hubris_v1,
        heuristic=v1_heuristic,
        legal_actions_fn=legal_fn,
        n_random_fencing=spec.n_random_fencing,
        rng_seed=seed,
    )
    return MCTSAgent(
        search,
        sims_per_move=spec.sims_per_move,
        c_uct=spec.c_uct,
        fpu_offset=spec.fpu_offset,
        action_selection_temperature=spec.temperature,
        rng_seed=seed,
    )


def _play_one_game(seed: int) -> GameResult:
    assert _WORKER_SPEC is not None
    spec = _WORKER_SPEC
    initial, env = setup_env(seed=seed)
    if spec.v1_as_p1:
        p0 = _build_v3_mcts(seed + 0, spec)
        p1 = _build_v1_mcts(seed + 1, spec)
    else:
        p0 = _build_v1_mcts(seed + 0, spec)
        p1 = _build_v3_mcts(seed + 1, spec)
    final, _trace = play_game(initial, (p0, p1), env.resolve)
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


# ---------------------------------------------------------------------------
# Parallel runner + summary (same shape as play_mcts_match.py)
# ---------------------------------------------------------------------------

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


def _emit_progress(g: GameResult, completed: int, n_total: int,
                   games: list[GameResult], t0: float, v1_name: str,
                   v3_name: str) -> None:
    wins = sum(1 for x in games if x.winner == 0)
    losses = sum(1 for x in games if x.winner == 1)
    draws = sum(1 for x in games if x.winner is None)
    elapsed = time.perf_counter() - t0
    rate = elapsed / completed
    remaining = rate * (n_total - completed)
    margin = sum(x.score_p0 - x.score_p1 for x in games) / completed
    winner_str = ("P0" if g.winner == 0 else "P1" if g.winner == 1 else "tie")
    print(
        f"  [{completed:>3}/{n_total}] seed={g.seed:>3} "
        f"{v1_name}={g.score_p0:>3} {v3_name}={g.score_p1:>3} → {winner_str:>3} | "
        f"tally {v1_name} {wins}-{draws}-{losses} {v3_name}, "
        f"avg margin {margin:+.2f} | "
        f"elapsed {elapsed/60:.1f}m, ETA {remaining/60:.1f}m",
        flush=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=40,
                    help="Number of games. Default 40.")
    ap.add_argument("--sims", type=int, default=200,
                    help="MCTS sims/move for BOTH seats. Default 200.")
    ap.add_argument("--c-uct", type=float, default=1.4)
    ap.add_argument("--n-random-fencing", type=int, default=4)
    ap.add_argument("--fpu-offset", type=float, default=0.0)
    ap.add_argument("--temperature", type=float, default=0.2)
    ap.add_argument(
        "--v3-config", type=str,
        default=str(ROOT / "tuned_configs" / "v3_best.json"),
        help="Path to V3 config JSON. Default v3_best.json.",
    )
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--mcts-v1-as-p1", action="store_true",
                    help="Place V1-MCTS at P1 instead of P0.")
    args = ap.parse_args()

    # Resolve V3 config
    if args.v3_config in ("default_v3", "default"):
        v3_cfg = DEFAULT_CONFIG_V3
    elif args.v3_config == "v3_t1":
        v3_cfg = CONFIG_V3_T1
    else:
        with open(args.v3_config) as f:
            v3_cfg = HeuristicConfigV3(**json.load(f)["best_config"])

    spec = _Spec(
        v3_config=v3_cfg,
        sims_per_move=args.sims,
        c_uct=args.c_uct,
        n_random_fencing=args.n_random_fencing,
        fpu_offset=args.fpu_offset,
        temperature=args.temperature,
        v1_as_p1=args.mcts_v1_as_p1,
    )

    p0_name = "mcts_v3" if args.mcts_v1_as_p1 else "mcts_v1"
    p1_name = "mcts_v1" if args.mcts_v1_as_p1 else "mcts_v3"
    v1_label = "v1" if not args.mcts_v1_as_p1 else "v1"  # display label
    v3_label = "v3" if args.mcts_v1_as_p1 else "v3"
    # Note: we'll use p0_name/p1_name in the streaming line.

    print(f"MCTS V1-eval vs MCTS V3-eval")
    print(f"  P0={p0_name}  vs  P1={p1_name}  "
          f"(n={args.n}, sims={args.sims}, jobs={args.jobs})")
    print(f"  V3 config: {args.v3_config}")
    print(f"  V1 config: CONFIG_V1_T2 (round-2-tuned V1)")
    print(f"  knobs: c_uct={args.c_uct}, n_random_fencing={args.n_random_fencing}, "
          f"fpu_offset={args.fpu_offset}, temperature={args.temperature}")
    print()

    seeds = list(range(args.n))
    games: list[GameResult] = []
    t0 = time.perf_counter()
    if args.jobs <= 1:
        _init_worker(spec)
        for i, s in enumerate(seeds, start=1):
            g = _play_one_game(s)
            games.append(g)
            _emit_progress(g, i, args.n, games, t0, p0_name, p1_name)
    else:
        with Pool(processes=args.jobs, initializer=_init_worker, initargs=(spec,)) as pool:
            for i, g in enumerate(
                pool.imap_unordered(_play_one_game, seeds, chunksize=1),
                start=1,
            ):
                games.append(g)
                _emit_progress(g, i, args.n, games, t0, p0_name, p1_name)
        games.sort(key=lambda g: g.seed)

    elapsed = time.perf_counter() - t0
    result = _aggregate(games, elapsed)
    print()
    print(f"FINAL: {p0_name} {result.p0_wins}-{result.draws}-{result.p1_wins} {p1_name}  "
          f"avg score {p0_name}={result.avg_score_p0:+.2f}  "
          f"{p1_name}={result.avg_score_p1:+.2f}  "
          f"margin (P0-P1)={result.avg_margin:+.2f}")
    print(f"Wall: {elapsed/60:.1f} min  ({elapsed/args.n:.1f}s/game)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
