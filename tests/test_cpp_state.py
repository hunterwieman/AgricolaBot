"""Stage 1 gate (CPP_ENGINE_PLAN.md §8): the C++ state model + canonical serde +
pasture flood-fill + structural hash/equality match Python exactly over a
representative state corpus.

This is the first *cross-language* gate: the C++ engine deserializes a
Python-produced canonical dump, operates on it, and re-serializes — and the
result must be byte-identical to Python's. Skips cleanly if the module isn't
built (see cpp/README.md).
"""

from __future__ import annotations

import pathlib
import sys

import numpy as np
import pytest

from agricola.agents.base import decider_of
from agricola.canonical import dumps
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.setup import setup_env
from tests.test_utils import filter_implemented

_BUILD_DIR = pathlib.Path(__file__).resolve().parent.parent / "cpp" / "build"
if str(_BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(_BUILD_DIR))

agricola_cpp = pytest.importorskip(
    "agricola_cpp",
    reason="cpp module not built — see cpp/README.md (cmake -S cpp -B cpp/build ...)",
)

_HARVEST_PHASES = {Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED}


def _collect_states(seed: int, max_states: int = 600) -> list:
    state, env = setup_env(seed)
    rng = np.random.default_rng(20_000 + seed)
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


def test_cpp_canonical_roundtrip_byte_identical():
    """C++ deserialize -> serialize reproduces Python's dump exactly."""
    corpus = _corpus()
    assert len(corpus) > 1000
    for state in corpus:
        d = dumps(state)
        assert agricola_cpp.canonical_roundtrip(d) == d


def test_cpp_pasture_flood_fill_matches_python():
    """C++ recomputes each player's pastures from grid+fences and reproduces
    Python's cached decomposition (validates flood-fill + canonical ordering)."""
    for state in _corpus():
        d = dumps(state)
        assert agricola_cpp.recompute_pastures(d) == d


def test_cpp_hash_and_equality_contract():
    corpus = _corpus()
    dumps_list = [dumps(s) for s in corpus]

    # Determinism + stability under round-trip.
    for d in dumps_list:
        assert agricola_cpp.state_hash(d) == agricola_cpp.state_hash(d)
        assert agricola_cpp.state_hash(agricola_cpp.canonical_roundtrip(d)) == \
            agricola_cpp.state_hash(d)

    # Equal states (same dump) -> equal hash + states_equal True.
    for d in dumps_list[:50]:
        assert agricola_cpp.states_equal(d, d)

    # Cross-language equality: C++ states_equal agrees with Python state equality.
    # (Sample pairs to keep it O(n).)
    n = len(corpus)
    rng = np.random.default_rng(7)
    for _ in range(400):
        i = int(rng.integers(n))
        j = int(rng.integers(n))
        py_equal = corpus[i] == corpus[j]
        cpp_equal = agricola_cpp.states_equal(dumps_list[i], dumps_list[j])
        assert cpp_equal == py_equal

    # Hash spread: a hash MAY collide — correctness comes from operator== (the
    # transposition table resolves bucket collisions by equality), not from a
    # zero-collision guarantee. The fast field-wise state_hash deliberately omits
    # pending-frame flags/counters (== still distinguishes them), so a handful of
    # states that differ ONLY in a pending flag can share a hash. We only require
    # the collision rate to be very low (the hash spreads well over the corpus).
    by_dump = {}
    for d in dumps_list:
        by_dump.setdefault(d, agricola_cpp.state_hash(d))
    hashes = list(by_dump.values())
    n_states = len(hashes)
    n_collisions = n_states - len(set(hashes))
    assert n_collisions <= max(3, n_states // 200), (
        f"{n_collisions} hash collisions in {n_states} distinct states — "
        f"the hash is not spreading well enough"
    )


def test_corpus_exercises_hard_cases():
    corpus = _corpus()
    assert any(s.pending_stack for s in corpus)
    assert any(s.phase in _HARVEST_PHASES for s in corpus)
    assert any(s.pending_stack and decider_of(s) is None for s in corpus)
    assert any(s.phase == Phase.BEFORE_SCORING for s in corpus)
