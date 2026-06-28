"""Stage 0 gate (CPP_ENGINE_PLAN.md §2): action trace serde round-trips, and the
trace writer + replayer faithfully reproduce a directly-recorded ``GameRecord``.

This validates the C++<->Python interop contract end-to-end on the Python side:
``game_to_trace`` (the writer the C++ binary mirrors) followed by ``replay_trace``
(the production adapter) yields the same record ``play_recording_game`` would —
same decision states, same chosen actions, same terminal state, same scoring.
"""

from __future__ import annotations

import pytest

from agricola.actions import (
    ChooseSubAction,
    CommitAccommodate,
    CommitBake,
    CommitBreed,
    CommitBuildMajor,
    CommitBuildPasture,
    CommitBuildRoom,
    CommitBuildStable,
    CommitConvert,
    CommitHarvestConversion,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    RevealCard,
    Stop,
)
from agricola.agents.base import RandomAgent
from agricola.agents.nn.recording import play_recording_game
from agricola.cost import ReturnImprovement
from agricola.resources import Resources
from agricola.agents.nn.trace_replay import (
    action_from_params,
    action_to_params,
    game_to_trace,
    replay_trace,
)
from agricola.canonical import dumps
from agricola.legality import legal_actions
from agricola.setup import setup_env

_SAMPLE_ACTIONS = [
    PlaceWorker("forest"),
    ChooseSubAction("sow"),
    CommitSow(grain=1, veg=2),
    CommitBake(grain=2),
    CommitPlow(row=0, col=1),
    CommitBuildStable(row=2, col=3),
    CommitBuildRoom(row=1, col=1),
    CommitBuildMajor(major_idx=2, payment=Resources(clay=4)),               # standard payment
    CommitBuildMajor(major_idx=2, payment=ReturnImprovement(improvement_idx=0)),  # fireplace route
    CommitRenovate(payment=Resources(clay=2, reed=1)),       # Resources payment serde
    CommitRenovate(payment=ReturnImprovement(improvement_idx=0)),  # route payment serde
    CommitAccommodate(sheep=1, boar=2, cattle=3),
    CommitBuildPasture(cells=frozenset({(0, 1), (0, 2)})),
    CommitHarvestConversion(conversion_id="joinery"),
    CommitConvert(grain=1, veg=0, sheep=2, boar=0, cattle=1),
    CommitBreed(sheep=2, boar=1, cattle=0),
    FireTrigger(card_id="potter_ceramics"),
    Stop(),
    RevealCard(card="fencing"),
]


@pytest.mark.parametrize("action", _SAMPLE_ACTIONS, ids=lambda a: type(a).__name__)
def test_action_params_roundtrip(action):
    params = action_to_params(action)
    restored = action_from_params(type(action).__name__, params)
    assert restored == action


def test_revealcard_carries_its_card_id():
    """The web-UI bug we fix: RevealCard's card id must survive serialization."""
    params = action_to_params(RevealCard(card="grain_utilization"))
    assert params == {"card": "grain_utilization"}
    assert action_from_params("RevealCard", params) == RevealCard(card="grain_utilization")


@pytest.mark.parametrize("seed", [0, 1, 2, 3])
def test_trace_replay_reproduces_direct_recording(seed):
    state0, env = setup_env(seed)

    # Reference: record the game directly (full, unrestricted legality — the
    # PUCT/self-play notion of "decision").
    reference = play_recording_game(
        state0,
        RandomAgent(seed * 3),
        RandomAgent(seed * 3 + 1),
        dealer=env.resolve,
        game_idx=0,
        seed=seed,
        p0_config_path="ref",
        p1_config_path="ref",
        p0_temperature=1.0,
        p1_temperature=1.0,
        legal_actions_fn=legal_actions,
    )

    # Same game via the trace writer + the replay adapter (fresh, identically
    # seeded agents → identical game).
    trace = game_to_trace(
        state0,
        RandomAgent(seed * 3),
        RandomAgent(seed * 3 + 1),
        dealer=env.resolve,
        seed=seed,
        legal_actions_fn=legal_actions,
    )
    replayed = replay_trace(trace, legal_actions_fn=legal_actions)

    assert len(reference.decisions) == len(replayed.decisions) > 0
    for d_ref, d_rep in zip(reference.decisions, replayed.decisions):
        assert dumps(d_ref.state) == dumps(d_rep.state)
        assert d_ref.chosen_action == d_rep.chosen_action
        assert d_ref.decider_idx == d_rep.decider_idx
    assert dumps(reference.terminal_state) == dumps(replayed.terminal_state)
    assert reference.p0_final_score == replayed.p0_final_score
    assert reference.p1_final_score == replayed.p1_final_score
    assert reference.winner == replayed.winner


def test_replay_rejects_foreign_schema():
    with pytest.raises(ValueError, match="schema"):
        replay_trace({"schema": "nope", "seed": 0, "initial_state": {}, "actions": []})
