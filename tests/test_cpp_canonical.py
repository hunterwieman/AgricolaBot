"""Stage 0 gate (CPP_ENGINE_PLAN.md §3.1): the canonical ``GameState`` serializer
round-trips byte-identically over a representative state corpus.

This pins the Python side of the cross-language contract. Stage 1 adds the C++
serializer and asserts it emits the identical string for the equivalent state.
"""

from __future__ import annotations

import numpy as np
import pytest

from agricola.agents.base import decider_of
from agricola.canonical import dumps, loads
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.setup import setup_env
from tests.test_utils import filter_implemented

_HARVEST_PHASES = {Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED}


def _collect_states(seed: int, max_states: int = 600) -> list:
    """Play one random game, snapshotting every state along the way.

    Random play sweeps the whole state space — empty-stack worker placements,
    deep pending stacks, the two-player harvest frames, round-card reveals, and
    the terminal state.
    """
    state, env = setup_env(seed)
    rng = np.random.default_rng(10_000 + seed)
    states = [state]
    while state.phase != Phase.BEFORE_SCORING and len(states) < max_states:
        d = decider_of(state)
        if d is None:
            action = env.resolve(state)
        else:
            legal = filter_implemented(legal_actions(state))
            action = legal[int(rng.integers(len(legal)))]
        state = step(state, action)
        states.append(state)
    return states


def _corpus(n_games: int = 6) -> list:
    out: list = []
    for seed in range(n_games):
        out.extend(_collect_states(seed))
    return out


def test_roundtrip_byte_identical():
    corpus = _corpus()
    assert len(corpus) > 1000  # sanity: the corpus is substantial
    for state in corpus:
        s1 = dumps(state)
        restored = loads(s1)
        s2 = dumps(restored)
        assert s1 == s2, "canonical dump is not stable under round-trip"
        # Stronger than byte-equality: the reconstructed object is value-equal
        # and hash-equal (the transposition-table contract).
        assert restored == state
        assert hash(restored) == hash(state)


def test_corpus_exercises_hard_cases():
    """Guard against a vacuous corpus: it must actually contain the subtle
    state shapes (pending stacks, harvest, reveals, terminal)."""
    corpus = _corpus()
    assert any(s.pending_stack for s in corpus), "no pending-stack states"
    assert any(s.phase in _HARVEST_PHASES for s in corpus), "no harvest states"
    # A round-card reveal frame: pending top with player_idx is None.
    assert any(
        s.pending_stack and decider_of(s) is None for s in corpus
    ), "no reveal (nature) states"
    # Multi-player coexisting frames during harvest feed/breed.
    assert any(
        len({getattr(f, "player_idx", -1) for f in s.pending_stack}) > 1
        for s in corpus
    ), "no states with both players' frames on the stack"
    assert any(s.phase == Phase.BEFORE_SCORING for s in corpus), "no terminal state"


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_loads_inverts_dumps(seed):
    for state in _collect_states(seed):
        assert loads(dumps(state)) == state
