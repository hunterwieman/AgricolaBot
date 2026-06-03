"""Play one full Family-game-mode game between two named agents and print
the final score.

Mirrors `play_random_game.py` but lets you pick any combination of
`random`, `simple`, `hubris` for each seat.

Usage:
    python play_heuristic_game.py                                   # hubris vs random, random seed
    python play_heuristic_game.py --p0 simple --p1 hubris           # named matchup
    python play_heuristic_game.py --p0 hubris --p1 hubris 42        # self-play with seed
    python play_heuristic_game.py --temperature 0.5 --trace 42      # sample-with-temperature + per-round trace
    python play_heuristic_game.py --lookahead action 42             # cheaper, weaker (1-action lookahead)
    python play_heuristic_game.py --quiet 42                        # totals only

The agent constructor seeds derive from the game seed (p0 seed = game_seed,
p1 seed = game_seed + 1) so a single CLI seed pins everything.
"""
from __future__ import annotations

import argparse
import random
import sys

from agricola.agents import (
    CONFIG_V1_T2,
    CONFIG_V3_T1,
    HeuristicConfigV3,
    HubrisHeuristic,
    HubrisHeuristicV1,
    HubrisHeuristicV2,
    HubrisHeuristicV3,
    RandomAgent,
    SimpleHeuristic,
    play_game,
)
from agricola.scoring import score, tiebreaker
from agricola.setup import setup, setup_env

# Tuned V3 config loaded at startup via --v3-config PATH. When None,
# hubris_v3 falls back to CONFIG_V3_T1. See _load_v3_config_from_json.
_TUNED_V3_CONFIG: HeuristicConfigV3 | None = None


def _load_v3_config_from_json(path: str) -> HeuristicConfigV3:
    """Load a HeuristicConfigV3 from a tune_heuristic.py JSON output file's
    `best_config` field. Raises if the file isn't a V3 tuning artifact.
    Mirrors play_web.py's helper of the same name."""
    import json as _json
    with open(path) as f:
        data = _json.load(f)
    if data.get("candidate_arch") != "v3":
        raise ValueError(
            f"{path}: candidate_arch is {data.get('candidate_arch')!r}, "
            f"expected 'v3'. This JSON is not a V3 tuning result."
        )
    if "best_config" not in data:
        raise ValueError(f"{path}: missing 'best_config' field.")
    return HeuristicConfigV3(**data["best_config"])

# Reuse the formatting helpers from play_random_game.py — same scoreboard,
# same trace renderer.
from play_random_game import (
    CATEGORY_ORDER,
    _format_player_summary,
    _print_scoreboard,
    _print_trace,
)


AGENT_TYPES = ("random", "simple", "hubris", "hubris_v1", "hubris_v2", "hubris_v3")


def _make_agent(name: str, seed: int, temperature: float, lookahead: str):
    """Build an agent by name. `temperature` and `lookahead` are ignored
    by `random` (it has no evaluator).

    Agent name conventions:
      "hubris"     — currently-strongest configured Hubris: V1 architecture
                     with the round-2-tuned CONFIG_V1_T2. Use this as the
                     default opponent in head-to-head matchups.
      "hubris_v1"  — original V1 with hand-picked DEFAULT_CONFIG (kept for
                     comparison with the tuned config).
      "hubris_v2"  — V2 architecture (joint frontier) with DEFAULT_CONFIG.

    The same seed is passed to both agents' RNGs; tournaments wanting
    independent RNGs should rely on the p0/p1 seed offset derived in main().
    """
    if name == "random":
        return RandomAgent(seed=seed)
    if name == "simple":
        return SimpleHeuristic(seed=seed, temperature=temperature, lookahead=lookahead)
    if name == "hubris":
        # Current strongest: V1 architecture + tuned CONFIG_V1_T2.
        return HubrisHeuristicV1(
            seed=seed, temperature=temperature, lookahead=lookahead,
            config=CONFIG_V1_T2,
        )
    if name == "hubris_v1":
        # Original V1 with DEFAULT_CONFIG (hand-picked).
        return HubrisHeuristicV1(seed=seed, temperature=temperature, lookahead=lookahead)
    if name == "hubris_v2":
        return HubrisHeuristicV2(seed=seed, temperature=temperature, lookahead=lookahead)
    if name == "hubris_v3":
        # V3 architecture. Priority: --v3-config PATH (if set) > CONFIG_V3_T1
        # (the older hardcoded V3 constant). The default --v3-config points
        # at tuned_configs/v3_best.json so this picks up the current champion
        # without per-command overrides. CONFIG_V3_T1 is kept as the
        # fallback only if the user passes --v3-config "" or none.
        cfg = _TUNED_V3_CONFIG if _TUNED_V3_CONFIG is not None else CONFIG_V3_T1
        return HubrisHeuristicV3(seed=seed, temperature=temperature, lookahead=lookahead,
                                  config=cfg)
    raise ValueError(f"Unknown agent type {name!r}; choose from {AGENT_TYPES}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "seed", nargs="?", type=int, default=None,
        help="Seed for setup() and both agents (defaults to a random int).",
    )
    parser.add_argument(
        "--p0", choices=AGENT_TYPES, default="hubris",
        help="Agent for player 0 (default: hubris).",
    )
    parser.add_argument(
        "--p1", choices=AGENT_TYPES, default="random",
        help="Agent for player 1 (default: random).",
    )
    parser.add_argument(
        "--temperature", type=float, default=0.0,
        help="Softmax temperature for heuristic agents (default 0.0 = argmax).",
    )
    parser.add_argument(
        "--lookahead", choices=("action", "turn"), default="turn",
        help="Lookahead horizon for heuristic agents (default 'turn').",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Only print totals + winner, not the per-category breakdown.",
    )
    parser.add_argument(
        "--trace", "-t", action="store_true",
        help="Print a per-round action log before the scoreboard.",
    )
    parser.add_argument(
        "--v3-config", default="tuned_configs/v3_best.json",
        help="Path to a JSON file (from scripts/tune_heuristic.py) whose "
             "'best_config' is loaded as the HubrisHeuristicV3 config when "
             "'hubris_v3' is selected as a seat. Default: "
             "tuned_configs/v3_best.json (the current promoted champion). "
             "Pass empty string ('') to fall back to the hardcoded "
             "CONFIG_V3_T1 (older V3 from earlier training rounds).",
    )
    args = parser.parse_args()

    # Load the tuned V3 config if a path was provided.
    global _TUNED_V3_CONFIG
    if args.v3_config:
        try:
            _TUNED_V3_CONFIG = _load_v3_config_from_json(args.v3_config)
            print(f"Loaded V3 config from {args.v3_config}")
        except (FileNotFoundError, ValueError) as e:
            print(f"WARNING: --v3-config {args.v3_config} failed to load: {e}")
            print(f"  Falling back to CONFIG_V3_T1 (hardcoded V3 constant).")
            _TUNED_V3_CONFIG = None

    seed = args.seed if args.seed is not None else random.randint(0, 2**31 - 1)
    print(f"Agricola heuristic game, seed={seed}, P0={args.p0}, P1={args.p1}, "
          f"temperature={args.temperature}, lookahead={args.lookahead}")

    initial_state, env = setup_env(seed=seed)
    print(f"Starting player: P{initial_state.starting_player}")

    agents = (
        _make_agent(args.p0, seed=seed,     temperature=args.temperature, lookahead=args.lookahead),
        _make_agent(args.p1, seed=seed + 1, temperature=args.temperature, lookahead=args.lookahead),
    )
    state, trace = play_game(initial_state, agents, env.resolve)

    print(f"Final phase: {state.phase.name}, round {state.round_number}, "
          f"{len(trace)} actions played.")

    if args.trace:
        _print_trace(initial_state, trace)

    print()
    print(f"Player 0 ({args.p0}):")
    print(_format_player_summary(state, 0))
    print()
    print(f"Player 1 ({args.p1}):")
    print(_format_player_summary(state, 1))

    _print_scoreboard(state, quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
