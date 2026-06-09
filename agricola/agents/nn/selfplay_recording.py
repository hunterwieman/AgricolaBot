"""MCTS self-play recording driver (DATA_VERSION 3).

Plays one full game with a SINGLE shared `MCTSAgent` driving both seats
(the "shared tree via shared agent" mode, MCTS_IMPLEMENTATION.md §11.2 mode 2)
and records each non-singleton decision together with the search's root
visit distribution π and root value — the AlphaZero policy/value targets.

Two pieces:

* `RootCapturingMCTSAgent` — an `MCTSAgent` subclass that stashes the
  searched root on `self.last_root` (by overriding the one method that
  receives it, `_select_action_with_temperature`). No edit to `mcts.py`.

* `play_selfplay_recording_game` — the per-game loop. Forced (singleton)
  decisions are stepped through directly without invoking the search:
  the move is forced regardless of search, so the trajectory is identical
  and we skip ~half the wasted MCTS calls. Only genuine multi-option
  decisions are searched and recorded.

Torch-free at module level (the NN leaf rides in via the agent the caller
passes); depends only on the engine + the schema dataclasses.
"""

from __future__ import annotations

from agricola.agents.base import decider_of
from agricola.agents.mcts import MCTSAgent, MCTSNode
from agricola.agents.nn.schema import (
    DATA_VERSION,
    DecisionSnapshot,
    GameRecord,
    compute_winner,
)
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions as full_legal_actions
from agricola.scoring import score, tiebreaker
from agricola.state import GameState
from tests.test_utils import filter_implemented


class RootCapturingMCTSAgent(MCTSAgent):
    """`MCTSAgent` that remembers the root of its most recent search.

    `_select_action_with_temperature` is the last thing `__call__` does
    after the simulation loop, and it receives the searched root — so
    overriding it to stash `self.last_root` captures exactly the tree the
    played move was drawn from, with no change to the search itself.
    """

    last_root: MCTSNode | None = None

    def _select_action_with_temperature(self, root: MCTSNode):
        self.last_root = root
        return super()._select_action_with_temperature(root)


def _root_value_p0(root: MCTSNode) -> float:
    """The root's mean value, expressed in P0's frame (P0 − P1 margin).

    `root.value_sum`/`mean_q` are stored in the root decider's own frame
    (MCTS_IMPLEMENTATION.md §1.6); flip to P0's frame so the stored
    `root_value` matches the terminal-margin convention the value head uses.
    """
    q = root.mean_q
    return q if root.decider == 0 else -q


def play_selfplay_recording_game(
    initial_state: GameState,
    agent: RootCapturingMCTSAgent,
    *,
    dealer,
    game_idx: int,
    seed: int,
    temperature: float,
    config_label: str = "mcts_selfplay",
    legal_actions_fn=full_legal_actions,
) -> GameRecord:
    """Play one shared-tree MCTS self-play game and return its `GameRecord`.

    `agent` is used for BOTH seats (shared tree). At every player decision
    we count `filter_implemented(legal_actions_fn(state))`: a singleton is
    stepped through directly (forced — not searched, not recorded); a
    multi-option decision is searched by `agent`, and we record the state,
    the chosen action, the root visit distribution π, and the P0-frame
    root value.

    `legal_actions_fn` must match what the agent consults so the
    "singleton" notion agrees (the production self-play agent uses full,
    unrestricted `legal_actions` — the default here).
    """
    state = initial_state
    decisions: list[DecisionSnapshot] = []

    while state.phase != Phase.BEFORE_SCORING:
        decider = decider_of(state)
        if decider is None:
            # Nature's round-card reveal — resolved by the dealer, never recorded.
            state = step(state, dealer(state))
            continue

        actions = filter_implemented(legal_actions_fn(state))
        if len(actions) <= 1:
            # Forced move: the single legal action is what any search would
            # also play. Step directly — identical trajectory, no wasted sims.
            state = step(state, actions[0])
            continue

        snapshot_state = state  # captured BEFORE the agent acts
        chosen = agent(state)
        root = agent.last_root
        decisions.append(DecisionSnapshot(
            state=snapshot_state,
            chosen_action=chosen,
            decider_idx=decider,
            visit_distribution=agent.root_visit_distribution(root),
            root_value=_root_value_p0(root),
        ))
        state = step(state, chosen)

    p0_total, _ = score(state, 0)
    p1_total, _ = score(state, 1)
    p0_tb = tiebreaker(state, 0)
    p1_tb = tiebreaker(state, 1)
    winner = compute_winner(p0_total, p1_total, p0_tb, p1_tb)

    return GameRecord(
        data_version=DATA_VERSION,
        game_idx=game_idx,
        seed=seed,
        p0_config_path=config_label,
        p1_config_path=config_label,
        p0_temperature=temperature,
        p1_temperature=temperature,
        p0_final_score=p0_total,
        p1_final_score=p1_total,
        winner=winner,
        terminal_state=state,
        decisions=tuple(decisions),
    )
