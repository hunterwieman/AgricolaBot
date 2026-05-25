"""Run MCTS vs a chosen opponent over a list of seeds and report aggregates.

Built on `scripts/play_match.py`'s pattern: each game's seed maps to per-
agent RNG seeds, then `play_game` drives the engine to completion and
`play_match` aggregates. Adds an MCTS-specific factory and per-MCTS
configuration flags (sims_per_move, c_uct, n_random_fencing, etc.).

Quick examples:

    # 10-game smoke at low sim budget
    python scripts/play_mcts_match.py --opponent hubris_v3 --sims 100 --n 10

    # Production validation against the current strongest V3
    python scripts/play_mcts_match.py --opponent hubris_v3 \\
        --v3-config tuned_configs/v3_best.json \\
        --sims 500 --n 100

    # MCTS-vs-MCTS with different c_uct (separate trees)
    python scripts/play_mcts_match.py --opponent mcts --sims 500 \\
        --c-uct 1.0 --opp-c-uct 2.0 --n 30

The MCTS seat plays as P0 by default. Use `--mcts-as-p1` to swap seats.
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

# Make `agricola` importable when run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents import (
    CONFIG_V3_T1,
    DEFAULT_CONFIG_V3,
    HeuristicConfigV3,
    HubrisHeuristicV3,
    MCTSAgent,
    MCTSSearch,
    RandomAgent,
    make_strict_restricted_legal_actions,
)
from agricola.agents.base import Agent, play_game
from agricola.scoring import score, tiebreaker
from agricola.setup import setup

# Reuse the play_match library for the aggregation logic.
sys.path.insert(0, str(ROOT / "scripts"))
from play_match import AgentFactory, GameResult, MatchResult, play_match, _winner


# ---------------------------------------------------------------------------
# Agent factories
# ---------------------------------------------------------------------------

def _load_v3_config(path: str | None):
    """Resolve a V3 config: None → DEFAULT_CONFIG_V3, 'v3_t1' → CONFIG_V3_T1,
    'default_v3' → DEFAULT_CONFIG_V3, else JSON path (loads `best_config`).
    """
    if path is None or path == "default_v3":
        return DEFAULT_CONFIG_V3
    if path == "v3_t1":
        return CONFIG_V3_T1
    with open(path) as f:
        payload = json.load(f)
    return HeuristicConfigV3(**payload["best_config"])


def _mcts_factory(
    *,
    seed_offset: int,
    config,
    sims_per_move: int,
    c_uct: float,
    n_random_fencing: int,
    temperature: float,
    fpu_offset: float,
) -> AgentFactory:
    def factory(game_seed: int) -> Agent:
        s = game_seed + seed_offset
        search = MCTSSearch(
            evaluator_config=config,
            n_random_fencing=n_random_fencing,
            rng_seed=s,
        )
        return MCTSAgent(
            search,
            sims_per_move=sims_per_move,
            c_uct=c_uct,
            fpu_offset=fpu_offset,
            action_selection_temperature=temperature,
            rng_seed=s,
        )
    return factory


def _opponent_factory(
    name: str,
    *,
    seed_offset: int,
    config,
    sims_per_move: int,
    c_uct: float,
    n_random_fencing: int,
    temperature: float,
    fpu_offset: float,
) -> AgentFactory:
    """Build the opponent factory. The heuristic opponent uses the SAME
    legal_actions_fn (strict-restricted) as MCTS for a fair comparison —
    matches what MCTS itself consults at every legality check, and aligns
    with the training pipeline's default (CHANGES.md Change 11).
    """
    if name == "mcts":
        return _mcts_factory(
            seed_offset=seed_offset, config=config,
            sims_per_move=sims_per_move, c_uct=c_uct,
            n_random_fencing=n_random_fencing,
            temperature=temperature, fpu_offset=fpu_offset,
        )

    def factory(game_seed: int) -> Agent:
        s = game_seed + seed_offset
        # A per-game RNG for the strict wrapper so cap-random samples are
        # deterministic per (game, seat).
        strict_fn = make_strict_restricted_legal_actions(
            config=config, rng=np.random.default_rng(s ^ 0xC0FFEE),
        )
        if name == "hubris_v3":
            return HubrisHeuristicV3(
                seed=s, temperature=0.0, lookahead="turn",
                config=config, legal_actions_fn=strict_fn,
            )
        if name == "random":
            return RandomAgent(seed=s, legal_actions_fn=strict_fn)
        raise ValueError(
            f"Unknown opponent {name!r}; choose from mcts / hubris_v3 / random"
        )
    return factory


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

OPPONENT_TYPES = ("hubris_v3", "random", "mcts")


# ---------------------------------------------------------------------------
# Parallel match runner
# ---------------------------------------------------------------------------
#
# multiprocessing.Pool with a worker initializer that stashes the per-match
# configuration in module-level globals (mirroring tune_heuristic.py's
# pattern). Agents are constructed inside the worker per game — avoids
# pickling MCTSSearch's transposition table, which would be expensive and
# may contain self-referential MCTSNode → MCTSSearch back-refs that don't
# pickle cleanly.


@dataclass(frozen=True)
class _MatchSpec:
    """Everything a worker needs to play one game. All fields are pickle-
    friendly primitives or the HeuristicConfigV3 dataclass."""
    config_v3: HeuristicConfigV3
    p0_name: str            # "mcts" or one of the opponent types
    p1_name: str
    sims_per_move: int
    opp_sims_per_move: int  # only relevant if opponent is also mcts
    c_uct: float
    opp_c_uct: float
    n_random_fencing: int
    fpu_offset: float
    temperature: float


_WORKER_SPEC: _MatchSpec | None = None


def _init_worker(spec: _MatchSpec) -> None:
    """Pool initializer: stash the match config in worker globals so each
    `_play_one_game` call can read it without re-passing on every task."""
    global _WORKER_SPEC
    _WORKER_SPEC = spec


def _build_agent(
    name: str, *, game_seed: int, seed_offset: int, spec: _MatchSpec,
    is_opponent: bool,
) -> Agent:
    """Construct an agent for one seat. Mirrors `_opponent_factory` but
    inline so it can be pickled / called from worker processes.

    `is_opponent` selects between the two MCTS budget knobs
    (sims_per_move vs opp_sims_per_move, c_uct vs opp_c_uct) when both
    seats are MCTS.
    """
    s = game_seed + seed_offset
    if name == "mcts":
        sims = spec.opp_sims_per_move if is_opponent else spec.sims_per_move
        c = spec.opp_c_uct if is_opponent else spec.c_uct
        search = MCTSSearch(
            evaluator_config=spec.config_v3,
            n_random_fencing=spec.n_random_fencing,
            rng_seed=s,
        )
        return MCTSAgent(
            search,
            sims_per_move=sims,
            c_uct=c,
            fpu_offset=spec.fpu_offset,
            action_selection_temperature=spec.temperature,
            rng_seed=s,
        )
    # Non-MCTS opponent. Use the same strict-restricted legality as MCTS
    # (matches the training pipeline default).
    strict_fn = make_strict_restricted_legal_actions(
        config=spec.config_v3, rng=np.random.default_rng(s ^ 0xC0FFEE),
    )
    if name == "hubris_v3":
        return HubrisHeuristicV3(
            seed=s, temperature=0.0, lookahead="turn",
            config=spec.config_v3, legal_actions_fn=strict_fn,
        )
    if name == "random":
        return RandomAgent(seed=s, legal_actions_fn=strict_fn)
    raise ValueError(f"Unknown agent name {name!r}")


def _play_one_game(seed: int) -> GameResult:
    """Top-level worker function (pickleable). Plays one game per seed
    and returns a GameResult. Reads config from `_WORKER_SPEC` globals."""
    assert _WORKER_SPEC is not None, "worker globals not initialized"
    spec = _WORKER_SPEC
    initial = setup(seed=seed)
    p0 = _build_agent(spec.p0_name, game_seed=seed, seed_offset=0,
                       spec=spec, is_opponent=(spec.p0_name != "mcts"))
    # When both seats are MCTS, P0=mcts (not opponent), P1=mcts (opponent).
    # When P0 is mcts and P1 is the opponent, P1 is the opponent.
    # When P0 is the opponent (--mcts-as-p1) and P1 is mcts, P0 IS the
    # opponent.
    p1 = _build_agent(spec.p1_name, game_seed=seed, seed_offset=1,
                       spec=spec, is_opponent=(spec.p1_name != "mcts" or spec.p0_name == "mcts"))
    final, _trace = play_game(initial, (p0, p1))
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
    """Aggregate per-game results into a MatchResult. Matches
    `play_match.play_match`'s reducer logic."""
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


def play_match_parallel(
    spec: _MatchSpec, seeds: list[int], *, jobs: int, progress: bool = True,
) -> MatchResult:
    """Run all games in parallel via multiprocessing.Pool.

    `jobs` workers each process a chunk of seeds. For best throughput,
    pick `len(seeds)` as a multiple of `jobs` so the final batch is full
    (a 10-seed run on 8 cores wastes 6 cores during the trailing batch
    of 2; 16 seeds on 8 cores fills both batches).

    `progress=True` prints one line per completed game (in completion
    order, not seed order) including running win/loss tally and ETA.
    Output is unbuffered (`flush=True`) so it's visible immediately when
    piped through `tee` or redirected to a file.
    """
    t0 = time.perf_counter()
    n_total = len(seeds)
    games: list[GameResult] = []

    def _emit(g: GameResult, completed: int) -> None:
        if not progress:
            return
        wins_so_far = sum(1 for x in games if x.winner == 0)
        losses_so_far = sum(1 for x in games if x.winner == 1)
        draws_so_far = sum(1 for x in games if x.winner is None)
        elapsed = time.perf_counter() - t0
        rate = elapsed / completed
        remaining = rate * (n_total - completed)
        margin_so_far = sum(x.score_p0 - x.score_p1 for x in games) / completed
        winner_str = ("P0" if g.winner == 0 else "P1" if g.winner == 1 else "tie")
        print(
            f"  [{completed:>3}/{n_total}] seed={g.seed:>3} "
            f"P0={g.score_p0:>3} P1={g.score_p1:>3} → {winner_str:>3} | "
            f"tally P0 {wins_so_far}-{draws_so_far}-{losses_so_far} P1, "
            f"avg margin {margin_so_far:+.2f} | "
            f"elapsed {elapsed/60:.1f}m, ETA {remaining/60:.1f}m",
            flush=True,
        )

    if jobs <= 1:
        # Sequential — useful for debugging / tracebacks. Skips the Pool.
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
        # imap_unordered returns games in completion order; sort by seed for
        # deterministic per-game output (the `--per-game` table later).
        games.sort(key=lambda g: g.seed)
    elapsed = time.perf_counter() - t0
    return _aggregate(games, elapsed)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--opponent", choices=OPPONENT_TYPES, default="hubris_v3",
                   help="The non-MCTS seat. (Or another MCTS for MCTS-vs-MCTS.)")
    p.add_argument("--mcts-as-p1", action="store_true",
                   help="Place MCTS at P1 instead of P0.")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--seeds", type=str, default=None,
                       help="Seed spec ('0-29' or '0,5,10'). Default: '0-{n-1}'.")
    group.add_argument("--n", type=int, default=10,
                       help="Number of games (uses seeds 0..n-1). Default 10.")
    p.add_argument("--v3-config", type=str, default=None,
                   help="Path to JSON config for the V3 evaluator. Defaults "
                        "to DEFAULT_CONFIG_V3. Use 'v3_t1' for CONFIG_V3_T1.")
    p.add_argument("--sims", type=int, default=500,
                   help="MCTS simulations per move. Default 500.")
    p.add_argument("--opp-sims", type=int, default=None,
                   help="MCTS sims/move for the opponent (--opponent mcts only). "
                        "Default = --sims.")
    p.add_argument("--c-uct", type=float, default=1.4)
    p.add_argument("--opp-c-uct", type=float, default=None,
                   help="c_uct for the opponent MCTS. Default = --c-uct.")
    p.add_argument("--n-random-fencing", type=int, default=4)
    p.add_argument("--fpu-offset", type=float, default=0.0)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                   help="Parallel processes for running games (default: all "
                        "cores). Use 1 for sequential (helpful for debugging). "
                        "Choose a multiple of --jobs as --n for best throughput "
                        "(no half-full final batch).")
    p.add_argument("--per-game", action="store_true",
                   help="Print one line per game in addition to the summary.")
    args = p.parse_args()

    if args.seeds is not None:
        from play_match import _parse_seeds
        seeds = list(_parse_seeds(args.seeds))
    else:
        seeds = list(range(args.n))

    config = _load_v3_config(args.v3_config)

    mcts_factory = _mcts_factory(
        seed_offset=0,
        config=config,
        sims_per_move=args.sims,
        c_uct=args.c_uct,
        n_random_fencing=args.n_random_fencing,
        temperature=args.temperature,
        fpu_offset=args.fpu_offset,
    )
    opp_sims = args.opp_sims if args.opp_sims is not None else args.sims
    opp_c_uct = args.opp_c_uct if args.opp_c_uct is not None else args.c_uct
    opp_factory = _opponent_factory(
        args.opponent,
        seed_offset=1,
        config=config,
        sims_per_move=opp_sims,
        c_uct=opp_c_uct,
        n_random_fencing=args.n_random_fencing,
        temperature=args.temperature,
        fpu_offset=args.fpu_offset,
    )

    if args.mcts_as_p1:
        p0_name, p1_name = args.opponent, "mcts"
    else:
        p0_name, p1_name = "mcts", args.opponent

    spec = _MatchSpec(
        config_v3=config,
        p0_name=p0_name, p1_name=p1_name,
        sims_per_move=args.sims, opp_sims_per_move=opp_sims,
        c_uct=args.c_uct, opp_c_uct=opp_c_uct,
        n_random_fencing=args.n_random_fencing,
        fpu_offset=args.fpu_offset,
        temperature=args.temperature,
    )

    cfg_label = args.v3_config or "default_v3"
    jobs = max(1, int(args.jobs))
    print(f"Match: P0={p0_name}  vs  P1={p1_name}  "
          f"({len(seeds)} seeds, jobs={jobs})")
    print(f"  V3 config: {cfg_label}")
    print(f"  MCTS: sims={args.sims}, c_uct={args.c_uct}, "
          f"n_random_fencing={args.n_random_fencing}, "
          f"fpu_offset={args.fpu_offset}, temperature={args.temperature}")
    if args.opponent == "mcts":
        print(f"  Opp MCTS: sims={opp_sims}, c_uct={opp_c_uct}")

    result = play_match_parallel(spec, list(seeds), jobs=jobs)
    elapsed = result.elapsed_seconds

    if args.per_game:
        print()
        print(f"{'seed':>6}  {'SP':>3}  {'P0':>4}  {'P1':>4}  "
              f"{'tb0':>4}  {'tb1':>4}  winner")
        for g in result.per_game:
            w = "P0" if g.winner == 0 else ("P1" if g.winner == 1 else "tie")
            print(f"{g.seed:>6}  {g.starting_player:>3}  "
                  f"{g.score_p0:>4}  {g.score_p1:>4}  "
                  f"{g.tiebreaker_p0:>4}  {g.tiebreaker_p1:>4}  {w}")

    print()
    print(result.summary_line())
    print(f"  Wall: {elapsed:.1f}s total, {elapsed / max(1, len(seeds)):.1f}s / game")
    return 0


if __name__ == "__main__":
    sys.exit(main())
