"""Tests for the PUCT (policy-prior-guided) path in `agricola/agents/mcts.py`.

Covers the c0 slice (POLICY_PUCT_DESIGN.md §7):

  - `FenceMode` invariants: PUCT forbids MACRO; SEQUENCE_PRIOR not yet
    implemented.
  - `uniform_policy` helper.
  - FLATTEN leaves fencing triggers as plain `PlaceWorker("fencing")` (no
    macros), vs MACRO which collapses them into `MacroFencingAction`s.
  - `_action_priors` populated once at expansion; normalized over the legal set.
  - PUCT prior actually steers visit allocation (constant value eval isolates
    the prior from Q).
  - `root_visit_distribution` accessor.
  - End-to-end: PUCT + uniform prior + FLATTEN completes a full game (vs Random
    and in self-play).
"""
from __future__ import annotations

import pytest

from agricola.actions import PlaceWorker
from agricola.agents.base import RandomAgent, play_game
from agricola.agents.mcts import (
    FenceMode,
    MCTSAgent,
    MCTSSearch,
    MacroFencingAction,
    uniform_policy,
)
from agricola.agents.restricted import restricted_legal_actions
from agricola.constants import Phase
from agricola.setup import setup, setup_env

from tests.factories import with_current_player, with_resources, with_space


def _flatten_search(*, policy_fn=uniform_policy, **kw):
    """A PUCT search: policy_fn + FLATTEN + regular legality."""
    return MCTSSearch(
        rng_seed=0,
        policy_fn=policy_fn,
        fence_mode=FenceMode.FLATTEN,
        legal_actions_fn=restricted_legal_actions,
        **kw,
    )


# ---------------------------------------------------------------------------
# FenceMode invariants
# ---------------------------------------------------------------------------

def test_puct_forbids_macro_fencing():
    """A policy_fn with MACRO fencing is rejected (macros aren't engine actions)."""
    with pytest.raises(ValueError):
        MCTSSearch(policy_fn=uniform_policy, fence_mode=FenceMode.MACRO)


def test_puct_default_fence_mode_is_macro_so_policy_requires_explicit_flatten():
    """The constructor default is MACRO, so supplying a policy without an
    explicit FLATTEN raises — PUCT must opt into FLATTEN."""
    with pytest.raises(ValueError):
        MCTSSearch(policy_fn=uniform_policy)


def test_sequence_prior_not_implemented():
    with pytest.raises(NotImplementedError):
        MCTSSearch(fence_mode=FenceMode.SEQUENCE_PRIOR)


def test_uct_default_unchanged():
    """No policy_fn, no fence_mode → vanilla UCT with MACRO fencing."""
    search = MCTSSearch(rng_seed=0)
    assert search.policy_fn is None
    assert search.fence_mode is FenceMode.MACRO


# ---------------------------------------------------------------------------
# uniform_policy helper
# ---------------------------------------------------------------------------

def test_uniform_policy_helper():
    actions = [PlaceWorker(space="forest"), PlaceWorker(space="clay_pit")]
    p = uniform_policy(None, actions)
    assert p == {actions[0]: 0.5, actions[1]: 0.5}
    assert uniform_policy(None, []) == {}


# ---------------------------------------------------------------------------
# FLATTEN vs MACRO at a fencing trigger
# ---------------------------------------------------------------------------

def _state_at_fencing_placeworker():
    """State where `PlaceWorker("fencing")` is a legal P0 move (Fencing revealed,
    ample wood). Mirrors the helper in test_mcts.py."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, wood=10)
    state = with_space(state, "fencing", revealed=True)
    return state


def test_flatten_leaves_fencing_trigger_unmacroed():
    state = _state_at_fencing_placeworker()

    # MACRO (UCT): the fencing trigger is replaced by MacroFencingAction(s).
    macro_search = MCTSSearch(rng_seed=0, n_random_fencing=1, fence_mode=FenceMode.MACRO)
    mnode = macro_search.find_or_create_node(state)
    mnode._compute_legal_actions()
    assert any(isinstance(a, MacroFencingAction) for a in mnode._legal_actions)
    assert PlaceWorker(space="fencing") not in mnode._legal_actions

    # FLATTEN: the fencing trigger stays a plain PlaceWorker; no macros.
    flat_search = _flatten_search()
    fnode = flat_search.find_or_create_node(state)
    fnode._compute_legal_actions()
    assert not any(isinstance(a, MacroFencingAction) for a in fnode._legal_actions)
    assert PlaceWorker(space="fencing") in fnode._legal_actions


# ---------------------------------------------------------------------------
# Priors at expansion
# ---------------------------------------------------------------------------

def test_action_priors_set_at_expansion_and_normalized():
    search = _flatten_search()
    agent = MCTSAgent(search, sims_per_move=10, c_uct=2.0, rng_seed=0)
    initial, _ = setup_env(seed=0)
    agent(initial)
    root = search.root
    assert root._action_priors is not None
    assert set(root._action_priors) == set(root._legal_actions)
    assert abs(sum(root._action_priors.values()) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# The prior steers selection
# ---------------------------------------------------------------------------

def test_puct_prior_steers_visits():
    """With a constant value eval (Q identical for all children), PUCT selection
    is driven purely by the prior: peaking the prior on `target` gives it the
    argmax of root visits and strictly more visits than a uniform prior does."""
    initial, _ = setup_env(seed=0)
    legal = restricted_legal_actions(initial)
    target = legal[0]

    def peaked(state, actions):
        if target in actions and len(actions) > 1:
            hi = 0.5
            rest = (1.0 - hi) / (len(actions) - 1)
            return {a: (hi if a == target else rest) for a in actions}
        return uniform_policy(state, actions)

    def visits_for(policy_fn):
        search = _flatten_search(
            policy_fn=policy_fn,
            evaluator_fn=lambda s, p, c: 0.0,   # constant Q → isolate the prior
        )
        agent = MCTSAgent(search, sims_per_move=40, c_uct=2.0,
                          action_selection_temperature=0.0, rng_seed=0)
        agent(initial)
        return agent.root_visit_distribution(search.root)

    peaked_dist = visits_for(peaked)
    uniform_dist = visits_for(uniform_policy)

    assert peaked_dist[target] == max(peaked_dist.values())
    assert peaked_dist[target] > uniform_dist.get(target, 0)


def test_root_visit_distribution_matches_children():
    search = _flatten_search()
    agent = MCTSAgent(search, sims_per_move=12, c_uct=2.0, rng_seed=0)
    initial, _ = setup_env(seed=0)
    agent(initial)
    dist = agent.root_visit_distribution(search.root)
    assert dist == {a: c.visits for a, c in search.root.children.items()}
    assert sum(dist.values()) >= 1


# ---------------------------------------------------------------------------
# End-to-end smoke (covers FLATTEN fencing + chance nodes under PUCT)
# ---------------------------------------------------------------------------

def test_puct_uniform_completes_full_game():
    search = _flatten_search()
    mcts = MCTSAgent(search, sims_per_move=5, c_uct=2.0, rng_seed=0)
    random_agent = RandomAgent(seed=1, legal_actions_fn=restricted_legal_actions)
    initial, env = setup_env(seed=0)
    final, trace = play_game(initial, (mcts, random_agent), env.resolve)
    assert final.phase == Phase.BEFORE_SCORING
    assert len(trace) > 50
    # FLATTEN produces no MacroFencingAction, so the agent's macro queue is never used.
    assert mcts._pending_macro_actions == []


def test_puct_self_play_completes():
    search = _flatten_search()
    agent = MCTSAgent(search, sims_per_move=5, c_uct=2.0, rng_seed=0)
    initial, env = setup_env(seed=2)
    final, _ = play_game(initial, (agent, agent), env.resolve)
    assert final.phase == Phase.BEFORE_SCORING


# ---------------------------------------------------------------------------
# Forced-move step-through invariant (applies to both UCT and PUCT)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("policy_fn", [uniform_policy, None])
def test_v_never_evaluated_at_a_forced_singleton(policy_fn):
    """The step-through invariant: V is queried only at real decisions (>1 legal
    action) or terminals — never at a forced (singleton) state. A forced move is
    stepped through in the same sim, with V evaluated downstream. Holds for both
    PUCT (`policy_fn` set) and UCT (`policy_fn=None`)."""
    from agricola.agents.base import decider_of

    seen = []

    def recording_eval(state, player_idx, config):
        if player_idx == 0:
            seen.append(state)
        return 0.0

    search = MCTSSearch(
        rng_seed=0, policy_fn=policy_fn, fence_mode=FenceMode.FLATTEN,
        legal_actions_fn=restricted_legal_actions,
        evaluator_fn=recording_eval,
    )
    agent = MCTSAgent(search, sims_per_move=40, c_uct=2.0, rng_seed=0)
    initial, _ = setup_env(seed=0)
    agent(initial)

    assert seen  # V was actually called
    for s in seen:
        if s.phase != Phase.BEFORE_SCORING and decider_of(s) is not None:
            assert len(restricted_legal_actions(s)) != 1, (
                "V evaluated at a forced singleton state — step-through failed"
            )
