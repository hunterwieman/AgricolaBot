"""Run a fixed matchup over a list of seeds and report aggregate stats.

Library entry point: `play_match(p0_factory, p1_factory, seeds)` returns a
`MatchResult` capturing win/loss/draw counts, score sums, and per-game
records. Used by the tuning harness (`scripts/tune_heuristic.py`) and as
a standalone CLI for ad-hoc matchups.

The factory pattern lets the caller decide how the game seed maps to each
agent's RNG seed. By default the CLI passes (seed, seed+1) — same
convention as `play_heuristic_game.py`.

CLI usage:
    python scripts/play_match.py --p0 hubris_v1 --p1 random --seeds 0-29
    python scripts/play_match.py --p0 hubris_v1 --p1 hubris_v2 --n 30
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Sequence

# Make `agricola` importable when run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents import (
    CONFIG_V1_T2,
    CONFIG_V3_T1,
    HubrisHeuristicV1,
    HubrisHeuristicV2,
    HubrisHeuristicV3,
    RandomAgent,
    SimpleHeuristic,
    play_game,
    restricted_legal_actions,
)
from agricola.agents.base import Agent
from agricola.scoring import score, tiebreaker
from agricola.setup import setup


AgentFactory = Callable[[int], Agent]  # game_seed -> Agent


@dataclass(frozen=True)
class GameResult:
    seed: int
    score_p0: int
    score_p1: int
    tiebreaker_p0: int
    tiebreaker_p1: int
    starting_player: int
    winner: int | None  # 0, 1, or None for true tie


@dataclass(frozen=True)
class MatchResult:
    n_games: int
    p0_wins: int
    p1_wins: int
    draws: int
    avg_score_p0: float
    avg_score_p1: float
    avg_margin: float     # mean(p0 - p1)
    elapsed_seconds: float
    per_game: tuple[GameResult, ...]

    def summary_line(self) -> str:
        return (
            f"P0 {self.p0_wins}-{self.draws}-{self.p1_wins} P1  "
            f"avg {self.avg_score_p0:+.2f} vs {self.avg_score_p1:+.2f}  "
            f"margin {self.avg_margin:+.2f}  "
            f"({self.n_games} games, {self.elapsed_seconds:.1f}s)"
        )


def _winner(s0: int, s1: int, tb0: int, tb1: int) -> int | None:
    if s0 > s1:
        return 0
    if s1 > s0:
        return 1
    if tb0 > tb1:
        return 0
    if tb1 > tb0:
        return 1
    return None


def play_match(
    p0_factory: AgentFactory,
    p1_factory: AgentFactory,
    seeds: Iterable[int],
) -> MatchResult:
    """Play one game per seed; aggregate results.

    Each game:
      - `state = setup(seed)`
      - `agents = (p0_factory(seed), p1_factory(seed))`
      - `play_game(state, agents)` to the end, then score + tiebreaker.

    Winner is the higher-score side; ties broken by tiebreaker; true ties
    (both equal) count as draws.
    """
    seeds = list(seeds)
    games: list[GameResult] = []
    t_start = time.perf_counter()

    for seed in seeds:
        initial = setup(seed=seed)
        agents = (p0_factory(seed), p1_factory(seed))
        state, _trace = play_game(initial, agents)
        s0, _ = score(state, 0)
        s1, _ = score(state, 1)
        tb0 = tiebreaker(state, 0)
        tb1 = tiebreaker(state, 1)
        winner = _winner(s0, s1, tb0, tb1)
        games.append(GameResult(
            seed=seed,
            score_p0=s0, score_p1=s1,
            tiebreaker_p0=tb0, tiebreaker_p1=tb1,
            starting_player=initial.starting_player,
            winner=winner,
        ))

    elapsed = time.perf_counter() - t_start
    n = len(games)
    p0_wins = sum(1 for g in games if g.winner == 0)
    p1_wins = sum(1 for g in games if g.winner == 1)
    draws   = sum(1 for g in games if g.winner is None)
    avg_p0  = sum(g.score_p0 for g in games) / n if n else 0.0
    avg_p1  = sum(g.score_p1 for g in games) / n if n else 0.0
    avg_margin = avg_p0 - avg_p1

    return MatchResult(
        n_games=n,
        p0_wins=p0_wins, p1_wins=p1_wins, draws=draws,
        avg_score_p0=avg_p0, avg_score_p1=avg_p1, avg_margin=avg_margin,
        elapsed_seconds=elapsed,
        per_game=tuple(games),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

AGENT_TYPES = ("random", "simple", "hubris", "hubris_v1", "hubris_v2", "hubris_v3")


def _make_factory(
    name: str,
    *,
    seed_offset: int,
    temperature: float,
    lookahead: str,
    restricted: bool = False,
) -> AgentFactory:
    """Build a factory closure for a named agent. The agent's RNG seed is
    `game_seed + seed_offset` so P0 and P1 can be given independent RNG
    streams (matching `play_heuristic_game.py`'s convention).

    Agent name conventions match play_heuristic_game.py:
      "hubris"     — V1 architecture + tuned CONFIG_V1_T2 (current strongest).
      "hubris_v1"  — V1 architecture + DEFAULT_CONFIG (original, for comparison).
      "hubris_v2"  — V2 architecture + DEFAULT_CONFIG.

    When `restricted=True` the agent is constructed with
    `legal_actions_fn=restricted_legal_actions`, so every legality
    consultation (top-level pick, singleton-skip, rollout) sees the
    action-pruned set defined by `agricola.agents.restricted`.
    """
    extra = {"legal_actions_fn": restricted_legal_actions} if restricted else {}

    def factory(game_seed: int) -> Agent:
        s = game_seed + seed_offset
        if name == "random":
            return RandomAgent(seed=s, **extra)
        if name == "simple":
            return SimpleHeuristic(seed=s, temperature=temperature, lookahead=lookahead, **extra)
        if name == "hubris":
            return HubrisHeuristicV1(seed=s, temperature=temperature, lookahead=lookahead,
                                     config=CONFIG_V1_T2, **extra)
        if name == "hubris_v1":
            return HubrisHeuristicV1(seed=s, temperature=temperature, lookahead=lookahead, **extra)
        if name == "hubris_v2":
            return HubrisHeuristicV2(seed=s, temperature=temperature, lookahead=lookahead, **extra)
        if name == "hubris_v3":
            return HubrisHeuristicV3(seed=s, temperature=temperature, lookahead=lookahead,
                                      config=CONFIG_V3_T1, **extra)
        raise ValueError(f"Unknown agent type {name!r}; choose from {AGENT_TYPES}")
    return factory


def _parse_seeds(spec: str) -> Sequence[int]:
    """Parse a seed spec like "0-29" or "0,5,10,42" or "0-9,20,30-39"."""
    seeds: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-", 1)
            seeds.extend(range(int(lo), int(hi) + 1))
        else:
            seeds.append(int(part))
    return seeds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p0", choices=AGENT_TYPES, default="hubris_v1")
    parser.add_argument("--p1", choices=AGENT_TYPES, default="hubris_v1")
    parser.add_argument("--p0-restricted", action="store_true",
                        help="Wrap P0 in restricted_legal_actions (action-pruned set).")
    parser.add_argument("--p1-restricted", action="store_true",
                        help="Wrap P1 in restricted_legal_actions (action-pruned set).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--seeds", type=str, default=None,
                       help="Seed spec (e.g. '0-29' or '0,5,10'). Default: '0-{n-1}'.")
    group.add_argument("--n", type=int, default=20,
                       help="Number of games (uses seeds 0..n-1). Default 20.")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--lookahead", choices=("action", "turn"), default="turn")
    parser.add_argument("--per-game", action="store_true",
                        help="Print one line per game in addition to the summary.")
    args = parser.parse_args()

    if args.seeds is not None:
        seeds = _parse_seeds(args.seeds)
    else:
        seeds = list(range(args.n))

    p0_fac = _make_factory(args.p0, seed_offset=0, temperature=args.temperature,
                            lookahead=args.lookahead, restricted=args.p0_restricted)
    p1_fac = _make_factory(args.p1, seed_offset=1, temperature=args.temperature,
                            lookahead=args.lookahead, restricted=args.p1_restricted)

    p0_label = args.p0 + ("[restricted]" if args.p0_restricted else "")
    p1_label = args.p1 + ("[restricted]" if args.p1_restricted else "")
    print(f"Match: P0={p0_label}  vs  P1={p1_label}  ({len(seeds)} seeds, "
          f"temperature={args.temperature}, lookahead={args.lookahead})")
    result = play_match(p0_fac, p1_fac, seeds)

    if args.per_game:
        print()
        print(f"{'seed':>6}  {'SP':>3}  {'P0':>4}  {'P1':>4}  {'tb0':>4}  {'tb1':>4}  winner")
        for g in result.per_game:
            w = "P0" if g.winner == 0 else ("P1" if g.winner == 1 else "tie")
            print(f"{g.seed:>6}  {g.starting_player:>3}  {g.score_p0:>4}  {g.score_p1:>4}  "
                  f"{g.tiebreaker_p0:>4}  {g.tiebreaker_p1:>4}  {w}")

    print()
    print(result.summary_line())
    return 0


if __name__ == "__main__":
    sys.exit(main())
