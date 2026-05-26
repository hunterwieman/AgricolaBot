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


# A `legal_actions_fn` is anything with the shape `legal_actions(state)`. The
# default for every agent is `agricola.legality.legal_actions` (unrestricted).
# Passing `agricola.agents.restricted.restricted_legal_actions` swaps in the
# action-pruned variant at every legality consultation.
LegalActionsFn = Callable[[GameState], list[Action]]


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

    `legal_actions_fn` is the function consulted for legality. Defaults to
    `agricola.legality.legal_actions` (the engine's unrestricted set); pass
    `agricola.agents.restricted.restricted_legal_actions` for a random
    agent operating on the action-pruned set.
    """

    def __init__(
        self,
        seed: int,
        *,
        legal_actions_fn: LegalActionsFn = legal_actions,
    ):
        self.rng = np.random.default_rng(seed)
        self.legal_actions_fn = legal_actions_fn

    def __call__(self, state: GameState) -> Action:
        actions = filter_implemented(self.legal_actions_fn(state))
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
        legal_actions_fn: LegalActionsFn = legal_actions,
        exhaustive_leaf_cap: int = 1000,
    ):
        if lookahead not in ("action", "turn", "exhaustive"):
            raise ValueError(f"lookahead must be 'action', 'turn', or "
                              f"'exhaustive', got {lookahead!r}")
        self.evaluator = evaluator
        self.config = config
        self.temperature = float(temperature)
        self.rng = np.random.default_rng(seed)
        self.lookahead = lookahead
        # See module-level note: the function consulted for legality at every
        # decision point (top-level pick, singleton-skip, rollout). Default is
        # the engine's unrestricted set; pass `restricted_legal_actions` for
        # the action-pruned variant.
        self.legal_actions_fn = legal_actions_fn
        # Per-top-level-action leaf cap used by lookahead="exhaustive". Each
        # candidate top-level action's exhaustive subtree may visit at most
        # this many leaves (= evaluator calls); if a recursion would exceed
        # the cap, that branch falls back to greedy descent (`_rollout_value`).
        # Default 1000 is a safety bound for Fencing-style explosions — per
        # the leaf-counter measurement, 95% of chains are <500 leaves so the
        # cap rarely fires.
        self.exhaustive_leaf_cap = int(exhaustive_leaf_cap)

    def __call__(self, state: GameState) -> Action:
        actions = filter_implemented(self.legal_actions_fn(state))
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

    def preview_top_actions(self, state: GameState) -> list[tuple[object, float]]:
        """Return [(action, score), ...] for each legal top-level action at
        `state`, sorted by descending score. Same `_lookahead_value`
        computation as `__call__`, exposed for observability (e.g. the
        web UI's interactive-AI preview mode). No selection, no mutation.

        Returns an empty list if there are zero or one legal actions
        (nothing meaningful to preview)."""
        actions = filter_implemented(self.legal_actions_fn(state))
        if len(actions) <= 1:
            return []
        decider = decider_of(state)
        with legal_actions_cache():
            scored = [(a, self._lookahead_value(step(state, a), decider))
                      for a in actions]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored

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
        if self.lookahead == "exhaustive":
            return self._exhaustive_value(state, decider)
        return self._rollout_value(state, decider)

    def _skip_singletons(self, state: GameState, decider: int) -> GameState:
        """Step through any chain of singleton decisions owned by `decider`
        until we reach a multi-option decision, the opponent's turn, or
        game end. Always-on; matches the "n meaningful decisions" rule.

        Singletons are detected against `self.legal_actions_fn`, so the
        action-pruned variant collapses sequences that look like singletons
        only after restriction (e.g., a forced highest-priority Commit*).
        """
        while True:
            if state.phase == Phase.BEFORE_SCORING:
                return state
            if decider_of(state) != decider:
                return state
            actions = filter_implemented(self.legal_actions_fn(state))
            if not actions or len(actions) != 1:
                return state
            state = step(state, actions[0])

    def _exhaustive_value(self, state: GameState, decider: int) -> float:
        """Exhaustive search over the decider's chain of decisions until
        control hands off. Returns the maximum evaluator score over all
        reachable handoff/end-state configurations.

        Cost is O(branching^chain_length) — potentially much larger than
        `_rollout_value`'s O(chain_length × branching). To bound the worst
        case (especially for Fencing, where chains can produce hundreds to
        thousands of leaves), a per-call leaf counter is tracked: when it
        exceeds `self.exhaustive_leaf_cap`, the recursion FALLS BACK to
        greedy descent (`_rollout_value`) for the remainder of that branch.

        Returns the best evaluator score reachable from this state through
        the decider's chain (whether found exhaustively or via partial
        greedy fallback). The caller is responsible for `_skip_singletons`
        before calling (the entry from `_lookahead_value` already does so;
        the recursive helper handles internal singleton-skip).
        """
        counter = [0]
        return self._exhaustive_recurse(state, decider, counter)

    def _exhaustive_recurse(self, state: GameState, decider: int,
                              counter: list) -> float:
        # Skip singletons (don't count as leaves — they have no decision).
        while True:
            if state.phase == Phase.BEFORE_SCORING:
                counter[0] += 1
                return self.evaluator(state, decider, self.config)
            if decider_of(state) != decider:
                counter[0] += 1
                return self.evaluator(state, decider, self.config)
            actions = filter_implemented(self.legal_actions_fn(state))
            if not actions:
                counter[0] += 1
                return self.evaluator(state, decider, self.config)
            if len(actions) == 1:
                state = step(state, actions[0])
                continue
            break

        # Multi-option decision still owned by decider.
        # If we're already over the cap, fall back to greedy for this branch.
        if counter[0] >= self.exhaustive_leaf_cap:
            return self._rollout_value(state, decider)

        best = -float("inf")
        for a in actions:
            cand = step(state, a)
            if counter[0] >= self.exhaustive_leaf_cap:
                # Cap hit mid-loop: remaining branches are evaluated greedily
                # rather than skipped, so we still return the BEST of what
                # we've seen plus a greedy approximation of unexpanded
                # branches. Greedy is admissible-ish (lower bound on what
                # exhaustive would find within the same branch).
                v = self._rollout_value(cand, decider)
            else:
                v = self._exhaustive_recurse(cand, decider, counter)
            if v > best:
                best = v
        return best

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
            actions = filter_implemented(self.legal_actions_fn(state))
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
