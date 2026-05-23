"""Agent implementations.

Each agent is a callable `(state) -> Action` that picks one legal action for
the current decider (the active player in WORK phase, or the pending frame's
`player_idx` if the pending stack is non-empty).

Currently implemented:

- `RandomAgent` (in `base.py`) — picks a uniformly-random legal action.
  Equivalent to the existing `tests/test_utils.random_agent_play` selection
  but packaged as a reusable agent object.

- `SimpleHeuristic` (in `heuristic.py`) — MVP heuristic agent: weighted-sum
  evaluator + 1-action lookahead + softmax-with-temperature action selection.

- `HubrisHeuristic` (in `heuristic.py`) — full-spec heuristic agent: same
  infrastructure, much more elaborate evaluator (per-round-decay,
  breeding-opportunity counter, context-dependent resource values, etc.).
  Designed to play noticeably better than `SimpleHeuristic` at the cost of
  more code and per-call evaluator cost.

For drivers that use these agents see `play_heuristic_game.py` at repo root.
"""

from agricola.agents.base import (
    Agent,
    HeuristicAgent,
    RandomAgent,
    play_game,
)
from agricola.agents.heuristic import (
    CONFIG_V1_T2,
    CONFIG_V3_T1,
    DEFAULT_CONFIG,
    DEFAULT_CONFIG_V3,
    HeuristicConfig,
    HeuristicConfigV3,
    HubrisHeuristic,
    HubrisHeuristicV1,
    HubrisHeuristicV2,
    HubrisHeuristicV3,
    SimpleHeuristic,
    evaluate_hubris,
    evaluate_hubris_v1,
    evaluate_hubris_v2,
    evaluate_hubris_v3,
    evaluate_simple,
)

__all__ = [
    "Agent",
    "HeuristicAgent",
    "RandomAgent",
    "HeuristicConfig",
    "HeuristicConfigV3",
    "DEFAULT_CONFIG",
    "DEFAULT_CONFIG_V3",
    "CONFIG_V1_T2",
    "CONFIG_V3_T1",
    "SimpleHeuristic",
    "HubrisHeuristic",
    "HubrisHeuristicV1",
    "HubrisHeuristicV2",
    "HubrisHeuristicV3",
    "evaluate_simple",
    "evaluate_hubris",
    "evaluate_hubris_v1",
    "evaluate_hubris_v2",
    "evaluate_hubris_v3",
    "play_game",
]
