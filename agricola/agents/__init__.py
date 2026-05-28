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
    LegalActionsFn,
    RandomAgent,
    play_game,
)
from agricola.agents.restricted import (
    FIRST_PASTURE_REQUIRED_CELLS,
    MAX_TOTAL_ROOMS,
    PLOW_PRIORITY,
    ROOM_PRIORITY,
    STABLE_PRIORITY,
    make_strict_restricted_legal_actions,
    restricted_legal_actions,
    strict_restricted_legal_actions,
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
    HubrisHeuristicV1Differential,
    HubrisHeuristicV3,
    HubrisHeuristicV3Differential,
    SimpleHeuristic,
    evaluate_hubris,
    evaluate_hubris_v1,
    evaluate_hubris_v1_differential,
    evaluate_hubris_v2,
    evaluate_hubris_v3,
    evaluate_hubris_v3_differential,
    evaluate_simple,
    make_differential_evaluator,
    compose_evaluators,
    r1_force_forest_bonus,
)
from agricola.agents.mcts import (
    MCTSAgent,
    MCTSNode,
    MCTSSearch,
    MacroFencingAction,
)

__all__ = [
    "Agent",
    "HeuristicAgent",
    "LegalActionsFn",
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
    "HubrisHeuristicV1Differential",
    "HubrisHeuristicV3Differential",
    "evaluate_simple",
    "evaluate_hubris",
    "evaluate_hubris_v1",
    "evaluate_hubris_v2",
    "evaluate_hubris_v3",
    "evaluate_hubris_v1_differential",
    "evaluate_hubris_v3_differential",
    "make_differential_evaluator",
    "compose_evaluators",
    "r1_force_forest_bonus",
    "play_game",
    "restricted_legal_actions",
    "strict_restricted_legal_actions",
    "make_strict_restricted_legal_actions",
    "STABLE_PRIORITY",
    "ROOM_PRIORITY",
    "PLOW_PRIORITY",
    "FIRST_PASTURE_REQUIRED_CELLS",
    "MAX_TOTAL_ROOMS",
    "MCTSAgent",
    "MCTSSearch",
    "MCTSNode",
    "MacroFencingAction",
]
