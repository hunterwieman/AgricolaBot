"""Tests for the joint inference adapter (`shared_policy.make_joint_fns`).

Covers the MCTS-facing contract of the shared-trunk model: value_fn is a P0-frame
margin with a terminal short-circuit; policy_fn is a valid distribution over the
legal set for every decision type; and crucially the **one-forward-per-node**
optimization — value and policy for a leaf share a single trunk forward (and
re-seen states reuse the cached embedding). Self-contained: a small random
`SharedTrunkModel`, no trained checkpoint or self-play data needed.
"""
from __future__ import annotations

import random

import numpy as np

from agricola.agents.base import decider_of
from agricola.agents.nn.dataset import NormStats
from agricola.agents.nn.encoder import ENCODED_DIM, ENCODING_VERSION
from agricola.agents.nn.policy_heads import HEADS, POINTER_HEADS
from agricola.agents.nn.shared_model import SharedTrunkModel
from agricola.agents.nn.shared_policy import make_joint_fns
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.scoring import score
from agricola.setup import setup_env


def _model() -> SharedTrunkModel:
    stats = NormStats(np.zeros(ENCODED_DIM, np.float32), np.ones(ENCODED_DIM, np.float32),
                      12.0, ENCODING_VERSION)
    return SharedTrunkModel(
        fixed_head_specs={n: h.num_classes for n, h in HEADS.items()},
        pointer_head_specs={n: h.candidate_dim for n, h in POINTER_HEADS.items()},
        norm_stats=stats, trunk_hidden_dims=[32, 32], embedding_dim=16,
        pointer_head_dims=[8])


def _decision_states(n_seeds: int = 8) -> list:
    """Multi-option decision states across a few random games (+ a terminal)."""
    states, terminal = [], None
    for seed in range(n_seeds):
        s, env = setup_env(seed)
        rng = random.Random(seed)
        while s.phase.name != "BEFORE_SCORING":
            d = decider_of(s)
            if d is None:
                s = step(s, env.reveal_action(s))
                continue
            la = legal_actions(s)
            if len(la) > 1:
                states.append(s)
            s = step(s, rng.choice(la))
        terminal = s
    return states, terminal


def test_value_finite_and_policy_normalized():
    m = _model().eval()
    vf, pf = make_joint_fns(m)
    states, _ = _decision_states()
    assert len(states) > 50
    for s in states[:80]:
        v = vf(s)
        assert np.isfinite(v)
        pri = pf(s, legal_actions(s))
        assert abs(sum(pri.values()) - 1.0) < 1e-5
        # every key is a legal action
        assert set(pri).issubset(set(legal_actions(s)))


def test_one_trunk_forward_per_node():
    """value_fn + policy_fn for the same leaf share a single trunk forward (and a
    re-seen state reuses the cached embedding → 0 forwards)."""
    m = _model().eval()
    calls = {"n": 0}
    orig = m.embed
    m.embed = lambda x: (calls.__setitem__("n", calls["n"] + 1), orig(x))[1]
    vf, pf = make_joint_fns(m)
    states, _ = _decision_states()
    for s in states[:40]:
        calls["n"] = 0
        vf(s)
        pf(s, legal_actions(s))
        assert calls["n"] <= 1, f"expected ≤1 trunk forward, got {calls['n']}"


def test_value_terminal_short_circuit_is_exact():
    m = _model().eval()
    vf, _ = make_joint_fns(m)
    _, terminal = _decision_states(n_seeds=3)
    assert terminal is not None and terminal.phase.name == "BEFORE_SCORING"
    own, _ = score(terminal, 0)
    opp, _ = score(terminal, 1)
    assert abs(vf(terminal) - float(own - opp)) < 1e-9   # exact margin, not NN guess
