"""Agent infrastructure shared by the heuristic agents (and reused by the
random agent for symmetry with future agent types).

This module defines:

- The `Agent` protocol — anything callable as `agent(state) -> Action` qualifies.
- `RandomAgent` — uniform-random over legal actions; mirrors
  `tests/test_utils.random_agent_play`.
- `HeuristicAgent` — generic 1-action-lookahead agent. Takes an evaluator
  `(state, player_idx, config) -> float` and a temperature; picks actions
  by either argmax (`temperature == 0`) or softmax-sampling.
- `play_game` — drive a full game between two agents, returns
  `(final_state, trace)` like `random_agent_play` does.

Design notes:

- *Action selection respects the decider*. Sub-action decisions on the
  pending stack belong to `pending_stack[-1].player_idx`, not necessarily
  to `state.current_player` (the divergence occurs for opponent-triggered
  frames). The agent always picks for the decider and evaluates from the
  decider's perspective.

- *Singleton actions are not evaluated*. When `len(legal_actions(state)) ==
  1`, the agent returns it directly — no `step` call, no evaluator call.
  This matches the engine's "no auto-resolved singleton player decisions"
  principle while still avoiding wasted evaluator work.

- *Implementation filter*. `play_game` (and the lookahead) filter
  `legal_actions` through `filter_implemented` so unimplemented
  PlaceWorker targets (currently `lessons`) are excluded. This keeps the
  agents working as the engine grows: when a new non-atomic space lands,
  the filter widens automatically.

- *Singleton-skip is ALWAYS on*, regardless of lookahead mode. "n steps
  deep = n meaningful decisions" applies uniformly: after every step
  (top-level OR rollout-internal), we advance through any chain of
  singleton decisions belonging to the decider before evaluating. The
  evaluator therefore never sees a state where the decider's "next
  decision" has only one option.

- *Lookahead horizon is configurable* (defaults to 1 turn). The
  `lookahead` constructor arg picks one of two modes (both with
  singleton-skip on):

    - `"action"`: step + skip singletons, evaluate. One meaningful
      step ahead. Cheap; doesn't see what sub-actions the decider would
      pick after a non-atomic placement. Useful as a sanity baseline and
      as a cheap MCTS rollout policy.
    - `"turn"` (default): step + skip singletons, then greedily roll
      forward through the decider's remaining decisions (1-ply argmax at
      each multi-option point, singletons stepped through) until control
      hands off to the opponent or the game ends. This is the natural
      "1 turn = 1 worker placement + all its sub-action commits"
      framing. Cost is linear in chain length, not exponential — the
      rollout uses 1-ply argmax at each internal step rather than full
      search.

  Both modes use the same evaluator; only the *state being evaluated*
  differs.

- *Determinism via seed, not state*. Agents take a seed at construction;
  the `numpy` RNG threads through both action sampling and any internal
  tiebreakers. Two agents constructed with the same seed produce identical
  play given identical input.
"""

from __future__ import annotations

import math
from typing import Callable, Protocol

import numpy as np

from agricola.actions import Action
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions, legal_actions_cache
from agricola.state import GameState

# Import the filter helper used by the random-agent driver — agents inherit
# the same scope ("only pick actions the engine knows how to apply").
from tests.test_utils import filter_implemented


# ---------------------------------------------------------------------------
# Agent protocol
# ---------------------------------------------------------------------------

class Agent(Protocol):
    """Minimal agent interface. An agent is anything callable as
    `(state) -> Action` that returns one element of
    `filter_implemented(legal_actions(state))`.

    Callers should treat the returned action as opaque — pass it straight
    to `step(state, action)`. Agents are responsible for their own RNG and
    for never returning an illegal or unimplemented action.
    """

    def __call__(self, state: GameState) -> Action: ...


# ---------------------------------------------------------------------------
# Decider helper
# ---------------------------------------------------------------------------

def decider_of(state: GameState) -> int:
    """Return the player index whose decision is currently being awaited.

    Empty stack → `state.current_player` (whose worker placement is being
    resolved). Non-empty stack → `pending_stack[-1].player_idx` (the frame's
    owner; may differ from the active player for opponent-triggered frames).
    """
    if state.pending_stack:
        return state.pending_stack[-1].player_idx
    return state.current_player


# ---------------------------------------------------------------------------
# Random agent
# ---------------------------------------------------------------------------

class RandomAgent:
    """Uniformly random over the filtered legal actions.

    Equivalent to the loop body of `tests/test_utils.random_agent_play`,
    packaged as an agent object for symmetry with the heuristic agents.
    Used as a baseline opponent and as a sanity-check for evaluator code.
    """

    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)

    def __call__(self, state: GameState) -> Action:
        actions = filter_implemented(legal_actions(state))
        if not actions:
            raise RuntimeError(
                f"RandomAgent stuck: no implemented legal actions. "
                f"State: phase={state.phase}, "
                f"current_player={state.current_player}, "
                f"pending_stack={state.pending_stack}"
            )
        return actions[int(self.rng.integers(len(actions)))]


# ---------------------------------------------------------------------------
# Heuristic agent (generic, takes an evaluator)
# ---------------------------------------------------------------------------

# An evaluator scores a state from a player's perspective. Higher is better.
Evaluator = Callable[[GameState, int, "object"], float]


class HeuristicAgent:
    """1-action-lookahead agent driven by an evaluator function.

    The evaluator's signature is `(state, player_idx, config) -> float`. At
    each decision point the agent:

    1. Computes `actions = filter_implemented(legal_actions(state))`.
    2. If `len(actions) == 1`, returns the singleton (no evaluator call).
    3. Otherwise, for each action `a`: computes `next_state = step(state, a)`
       and `score = evaluator(next_state, decider, config)`.
    4. Selects an action by `temperature`-controlled softmax: temperature 0
       takes argmax with random tiebreak; positive temperatures sample from
       softmax(scores / temperature).

    The lookahead runs inside a `legal_actions_cache()` block so the
    `legal_actions(next_state)` calls the evaluator may issue are cached
    for the remainder of this decision.
    """

    def __init__(
        self,
        evaluator: Evaluator,
        *,
        config: object,
        temperature: float = 0.0,
        seed: int = 0,
        lookahead: str = "turn",
    ):
        if lookahead not in ("action", "turn"):
            raise ValueError(f"lookahead must be 'action' or 'turn', got {lookahead!r}")
        self.evaluator = evaluator
        self.config = config
        self.temperature = float(temperature)
        self.rng = np.random.default_rng(seed)
        self.lookahead = lookahead

    def __call__(self, state: GameState) -> Action:
        actions = filter_implemented(legal_actions(state))
        if not actions:
            raise RuntimeError(
                f"HeuristicAgent stuck: no implemented legal actions. "
                f"State: phase={state.phase}, "
                f"current_player={state.current_player}, "
                f"pending_stack={state.pending_stack}"
            )
        if len(actions) == 1:
            return actions[0]

        decider = decider_of(state)
        with legal_actions_cache():
            scores = [self._lookahead_value(step(state, a), decider) for a in actions]
        return self._select(actions, scores)

    def _lookahead_value(self, state: GameState, decider: int) -> float:
        """Score a candidate state from the decider's perspective.

        ALWAYS skips singletons first — "n steps deep = n meaningful
        decisions" applies uniformly across modes. The two modes differ
        in what happens AFTER singleton-skip:

        - `"action"`: evaluate immediately. One meaningful step ahead.
        - `"turn"`: greedily roll forward through the decider's
          remaining decisions until control hands off, then evaluate at
          the handoff state.
        """
        state = self._skip_singletons(state, decider)
        if self.lookahead == "action":
            return self.evaluator(state, decider, self.config)
        return self._rollout_value(state, decider)

    def _skip_singletons(self, state: GameState, decider: int) -> GameState:
        """Step through any chain of singleton decisions owned by `decider`
        until we reach a multi-option decision, the opponent's turn, or
        game end. Always-on; matches the "n meaningful decisions" rule."""
        while True:
            if state.phase == Phase.BEFORE_SCORING:
                return state
            if decider_of(state) != decider:
                return state
            actions = filter_implemented(legal_actions(state))
            if not actions or len(actions) != 1:
                return state
            state = step(state, actions[0])

    def _rollout_value(self, state: GameState, decider: int) -> float:
        """Greedy 1-ply rollout of the decider's OWN subsequent decisions
        until control hands off to the opponent or the game ends. Returns
        the evaluator score at the handoff state.

        Singleton actions are stepped through without evaluation (delegated
        to `_skip_singletons` at each iteration). At each multi-option
        decision the rollout picks the action whose post-step state
        evaluates highest — local greedy, not recursive. Cost is bounded
        by O(chain_length × branching) per top-level action; the
        alternative (recursive lookahead) would be exponential.
        """
        while True:
            state = self._skip_singletons(state, decider)
            if state.phase == Phase.BEFORE_SCORING:
                break
            if decider_of(state) != decider:
                break
            actions = filter_implemented(legal_actions(state))
            if not actions:
                break
            # _skip_singletons guarantees len(actions) > 1 here.
            best_score = -float("inf")
            best_state = None
            for a in actions:
                cand = step(state, a)
                s = self.evaluator(cand, decider, self.config)
                if s > best_score:
                    best_score = s
                    best_state = cand
            state = best_state
        return self.evaluator(state, decider, self.config)

    def _select(self, actions: list[Action], scores: list[float]) -> Action:
        if self.temperature <= 0.0:
            # Argmax with random tiebreak.
            best = max(scores)
            ties = [i for i, s in enumerate(scores) if s == best]
            idx = ties[int(self.rng.integers(len(ties)))]
            return actions[idx]
        # Softmax sampling. Subtract max for numerical stability.
        m = max(scores)
        exps = [math.exp((s - m) / self.temperature) for s in scores]
        total = sum(exps)
        probs = [e / total for e in exps]
        idx = int(self.rng.choice(len(actions), p=probs))
        return actions[idx]


# ---------------------------------------------------------------------------
# Game driver
# ---------------------------------------------------------------------------

def play_game(
    initial_state: GameState,
    agents: tuple[Agent, Agent],
) -> tuple[GameState, list[Action]]:
    """Drive a full game between two agents from `initial_state` to
    `BEFORE_SCORING`. Returns (terminal_state, trace).

    `agents[i]` plays as player i. The decider's agent is queried at each
    decision (uses `decider_of(state)`). Returns when the engine reports
    `BEFORE_SCORING` (game over, no actions remaining).

    Mirrors `tests/test_utils.random_agent_play` but lets you mix agent
    types — e.g. random vs heuristic, simple vs hubris, or self-play with
    a single shared agent object.
    """
    state = initial_state
    trace: list[Action] = []
    while state.phase != Phase.BEFORE_SCORING:
        agent = agents[decider_of(state)]
        action = agent(state)
        trace.append(action)
        state = step(state, action)
    return state, trace
