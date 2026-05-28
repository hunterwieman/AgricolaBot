"""Single-game recording driver.

Plays one full game between two agents from an initial state to
terminal, capturing every non-singleton decision plus the terminal
state and final scoring. The output is a complete `GameRecord` ready
to be pickled.

This is the core building block of the batch generator (step 3 in
the FIRST_NN.md §7.1 plan). The batch generator wraps this in a
multiprocessing pool and writes per-worker pickle files.

This module depends only on the engine (`step`, `legal_actions`,
`scoring`) and the `Agent` protocol — no PyTorch dependency.
"""

from __future__ import annotations

from agricola.agents.base import Agent, LegalActionsFn, decider_of
from agricola.agents.nn.schema import (
    DATA_VERSION,
    DecisionSnapshot,
    GameRecord,
    compute_winner,
)
from agricola.agents.restricted import restricted_legal_actions
from agricola.constants import Phase
from agricola.engine import step
from agricola.scoring import score, tiebreaker
from agricola.state import GameState
from tests.test_utils import filter_implemented


def play_recording_game(
    initial_state: GameState,
    p0_agent: Agent,
    p1_agent: Agent,
    *,
    game_idx: int,
    seed: int,
    p0_config_path: str,
    p1_config_path: str,
    p0_temperature: float,
    p1_temperature: float,
    legal_actions_fn: LegalActionsFn = restricted_legal_actions,
) -> GameRecord:
    """Play one full game between two agents, capturing every
    non-singleton decision + the terminal state + final scoring.

    Snapshot semantics (per FIRST_NN.md §7.1.2): a `DecisionSnapshot`
    is recorded only at states where the agent had a real choice —
    `len(filter_implemented(legal_actions_fn(state))) > 1`. Singleton
    states (and engine-resolved transitions inside `_advance_until_decision`)
    contribute nothing to `decisions`. Their absence from the record
    matches what the agent's singleton-skip wrapper does anyway.

    The `state` field of each snapshot is captured *before* the agent
    is called and *before* `step` is applied — it is precisely the
    state the agent saw and decided from. Critical: do not reorder
    this code unless you're certain the captured state still matches.

    `legal_actions_fn` should be the same function the agents
    themselves were constructed with (in practice
    `restricted_legal_actions` for the data-generation pipeline; see
    FIRST_NN.md §7.1.1). Determines what counts as a "non-singleton."

    Determinism: the caller is responsible for seeding the agents.
    This function does not introduce additional randomness — given
    pre-seeded agents and a deterministic `initial_state`, the
    resulting `GameRecord` is fully reproducible.

    Returns a complete `GameRecord` stamped with the current
    `DATA_VERSION`.
    """
    state = initial_state
    decisions: list[DecisionSnapshot] = []

    while state.phase != Phase.BEFORE_SCORING:
        decider = decider_of(state)
        agent = (p0_agent, p1_agent)[decider]

        # Decide whether to record. Use the same legal_actions_fn the
        # agent will consult so our "singleton" notion matches the agent's.
        actions = filter_implemented(legal_actions_fn(state))
        is_real_decision = len(actions) > 1

        # Capture the state BEFORE the agent call — frozen-dataclass
        # safety means this binding is durable even after `step` produces
        # a new state, but we want a value-bound reference for clarity.
        snapshot_state = state if is_real_decision else None

        chosen = agent(state)

        if is_real_decision:
            # snapshot_state is the state the agent saw; chosen is what
            # the agent returned. These together are the training datum.
            decisions.append(DecisionSnapshot(
                state=snapshot_state,
                chosen_action=chosen,
                decider_idx=decider,
            ))

        state = step(state, chosen)

    # Game over. `state` is at Phase.BEFORE_SCORING — the terminal state.
    p0_total, _ = score(state, 0)
    p1_total, _ = score(state, 1)
    p0_tb = tiebreaker(state, 0)
    p1_tb = tiebreaker(state, 1)
    winner = compute_winner(p0_total, p1_total, p0_tb, p1_tb)

    return GameRecord(
        data_version=DATA_VERSION,
        game_idx=game_idx,
        seed=seed,
        p0_config_path=p0_config_path,
        p1_config_path=p1_config_path,
        p0_temperature=p0_temperature,
        p1_temperature=p1_temperature,
        p0_final_score=p0_total,
        p1_final_score=p1_total,
        winner=winner,
        terminal_state=state,
        decisions=tuple(decisions),
    )
