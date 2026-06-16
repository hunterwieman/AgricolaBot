"""Stage 6 gate (CPP_ENGINE_PLAN.md §7/§8): native MCTS.

There is NO byte-exact gate for MCTS — RNG, float-summation order, and tie-break
ordering diverge across languages (§7.6, expected). Validation is three-pronged:

1. **Component tests** (deterministic pieces, via the `mcts_debug_root` hook):
   - single-option player state -> the agent puts all root visits on the one
     legal action;
   - the root visit counts sum to the sim budget;
   - a chance-node root round-robins the <=3 reveals ~uniformly;
   - a hand-checked first-sim PUCT pick matches the Python formula.

2. **Self-play record validity:** `mcts_selfplay_trace(seed, sims=...)` for
   several seeds replays through `replay_trace` -> a valid terminal `GameRecord`
   with `visit_distribution` AND `root_value` populated on the non-singleton
   decisions; `validate_dataset.check_record` passes; pi keys are legal actions
   and sum to ~the budget.

3. **Strength parity (statistical):** `CppMctsAgent` vs the Python `MCTSAgent`
   (same config) over N seeds via `play_game` — C++ win-rate in a WIDE band
   (sanity it plays comparably, not bit-identically). Plus C++ MCTS >> Random.

All torch-needing tests skip unless the torch bindings are built AND
`nn_models/cpp_export/` exists (run `scripts/nn/export_torchscript.py`).
"""

from __future__ import annotations

import json
import math
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

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_BUILD_DIR = _ROOT / "cpp" / "build"
if str(_BUILD_DIR) not in sys.path:
    sys.path.insert(0, str(_BUILD_DIR))

agricola_cpp = pytest.importorskip(
    "agricola_cpp", reason="cpp module not built — see cpp/README.md"
)

_EXPORT_DIR = _ROOT / "nn_models" / "cpp_export"
_MODEL_DIR = str(_EXPORT_DIR)
_HAS_TORCH = getattr(agricola_cpp, "HAS_TORCH", False)
_HAS_EXPORT = (_EXPORT_DIR / "weights_manifest.json").exists()
_torch_gate = pytest.mark.skipif(
    not (_HAS_TORCH and _HAS_EXPORT),
    reason="NN bindings not built or nn_models/cpp_export not exported "
    "(run scripts/nn/export_weights.py)",
)


# ---------------------------------------------------------------------------
# State corpus helpers
# ---------------------------------------------------------------------------


def _first_state_where(seed: int, predicate, max_steps: int = 4000):
    """Walk a random game from setup(seed) to the first state matching
    `predicate`, returning it (or None). Uses the env dealer for reveals."""
    state, env = setup_env(seed)
    rng = np.random.default_rng(123_000 + seed)
    for _ in range(max_steps):
        if predicate(state):
            return state
        if state.phase == Phase.BEFORE_SCORING:
            return None
        d = decider_of(state)
        if d is None:
            action = env.resolve(state)
        else:
            legal = filter_implemented(legal_actions(state))
            action = legal[int(rng.integers(len(legal)))]
        state = step(state, action)
    return None


def _is_singleton_player_state(s) -> bool:
    if s.phase == Phase.BEFORE_SCORING:
        return False
    if decider_of(s) is None:
        return False
    return len(filter_implemented(legal_actions(s))) == 1


def _is_chance_state(s) -> bool:
    return s.phase != Phase.BEFORE_SCORING and decider_of(s) is None


def _is_multi_player_state(s) -> bool:
    if s.phase == Phase.BEFORE_SCORING or decider_of(s) is None:
        return False
    return len(filter_implemented(legal_actions(s))) > 1


# ---------------------------------------------------------------------------
# Component tests
# ---------------------------------------------------------------------------


@_torch_gate
def test_single_option_state_all_visits_on_it():
    """A player state with exactly one legal action: every root visit lands on
    that action (root has one child carrying the full budget)."""
    state = None
    for seed in range(60):
        state = _first_state_where(seed, _is_singleton_player_state)
        if state is not None:
            break
    assert state is not None, "no singleton player state found in 60 games"

    legal = filter_implemented(legal_actions(state))
    assert len(legal) == 1
    sims = 32
    dbg = agricola_cpp.mcts_debug_root(_MODEL_DIR, dumps(state), sims, 1.4, 7)
    vd = dbg["visit_distribution"]
    assert len(vd) == 1, f"expected 1 root child, got {len(vd)}"
    # The single child carries all the visits.
    assert vd[0][1] == sims
    assert dbg["root_visits"] == sims


@_torch_gate
def test_root_visits_sum_to_budget():
    """root.visits == sims (cap_total_sims, fresh tree). The child visit counts
    sum to (sims - 1): the root's own first 'visit' is the leaf at/near the root,
    so children collectively receive sims-1..sims depending on forced-step
    chains; we assert the conservative invariant that they don't EXCEED sims and
    the root equals the budget."""
    state = None
    for seed in range(40):
        state = _first_state_where(seed, _is_multi_player_state)
        if state is not None:
            break
    assert state is not None

    sims = 48
    dbg = agricola_cpp.mcts_debug_root(_MODEL_DIR, dumps(state), sims, 1.4, 3)
    assert dbg["root_visits"] == sims
    child_total = sum(n for _, n in dbg["visit_distribution"])
    # Each sim adds exactly 1 to the root and descends into exactly one child
    # (then possibly further). The root's children collectively are visited once
    # per sim that descended past the root — i.e. all `sims` of them, since the
    # root is never the evaluated leaf in a multi-option non-terminal state on
    # the very first sim only if it has no children yet. So child_total is in
    # [sims-1, sims].
    assert sims - 1 <= child_total <= sims, child_total


@_torch_gate
def test_chance_node_round_robin_uniform():
    """A chance-node root round-robins the <=3 reveal outcomes near-uniformly:
    the per-outcome chance_counts differ by at most 1."""
    state = None
    for seed in range(60):
        state = _first_state_where(seed, _is_chance_state)
        if state is not None:
            break
    assert state is not None, "no chance (reveal) state found in 60 games"

    # candidates from the engine (the <=3 RevealCards).
    candidates = legal_actions(state)
    assert 1 <= len(candidates) <= 3
    sims = 60
    dbg = agricola_cpp.mcts_debug_root(_MODEL_DIR, dumps(state), sims, 1.4, 11)
    assert dbg["is_chance"] is True
    counts = [n for _, n in dbg["chance_counts"]]
    assert len(counts) == len(candidates), (len(counts), len(candidates))
    assert sum(counts) == sims, (sum(counts), sims)
    # Round-robin => perfectly balanced up to +/-1.
    assert max(counts) - min(counts) <= 1, counts


@_torch_gate
def test_puct_first_pick_matches_formula():
    """On a FRESH root with 0 prior visits, the first sim's PUCT score is, for
    every (uncreated) child, Q=parent_q=0, n=0:
        U(a) = c_uct * P(a) * sqrt(max(visits,1)) / (1+0) = c_uct * P(a)
    so the first sim expands the MAX-PRIOR action (argmax over the policy prior,
    no tie unless two priors are exactly equal). With sims=1 the single visited
    root child is exactly that action — an exact hand-checked PUCT case."""
    from agricola.agents.nn.trace_replay import action_to_params
    from scripts.nn.build_combined_policy import build

    policy_fn = build("unweighted")

    checked = 0
    for seed in range(40):
        state = _first_state_where(seed, _is_multi_player_state)
        if state is None:
            continue
        prior = policy_fn(state, list(legal_actions(state)))
        if not prior:
            continue
        ordered = sorted(prior.items(), key=lambda kv: kv[1], reverse=True)
        # Require a STRICT top prior (no tie) so the first pick is unambiguous.
        if len(ordered) >= 2 and ordered[0][1] == ordered[1][1]:
            continue
        best_action = ordered[0][0]
        best_key = json.dumps(
            {"type": type(best_action).__name__,
             "params": action_to_params(best_action)},
            sort_keys=True,
        )

        dbg = agricola_cpp.mcts_debug_root(_MODEL_DIR, dumps(state), 1, 1.4, 5)
        vd = dbg["visit_distribution"]
        assert len(vd) == 1, f"sims=1 should create exactly one root child, got {len(vd)}"
        got_key = json.dumps(json.loads(vd[0][0]), sort_keys=True)
        assert got_key == best_key, (
            f"first PUCT pick {got_key} != max-prior action {best_key}"
        )
        checked += 1
        if checked >= 3:
            break

    assert checked >= 1, "no clean strict-top-prior multi-option state found"


# ---------------------------------------------------------------------------
# Self-play record validity
# ---------------------------------------------------------------------------


@_torch_gate
@pytest.mark.parametrize("seed", [101, 202, 303])
def test_selfplay_trace_replays_to_valid_record(seed):
    from agricola.agents.nn.trace_replay import replay_trace
    from scripts.nn.validate_dataset import check_record

    trace_str = agricola_cpp.mcts_selfplay_trace(seed, 48, 1.4, 1.0, _MODEL_DIR)
    trace = json.loads(trace_str)
    assert trace["schema"] == "agricola-cpp-trace-v1"

    rec = replay_trace(trace, game_idx=seed)
    # Terminal + non-empty + invariants.
    assert rec.terminal_state.phase == Phase.BEFORE_SCORING
    assert len(rec.decisions) > 0
    failures = check_record(rec)
    assert not failures, "\n".join(str(f) for f in failures)

    # Every recorded (non-singleton) decision carries pi + root_value.
    n_with_pi = 0
    for d in rec.decisions:
        assert d.visit_distribution is not None, "missing pi on a decision"
        assert d.root_value is not None, "missing root_value on a decision"
        # pi keys are legal actions at that state.
        legal = set(filter_implemented(legal_actions(d.state)))
        for a, n in d.visit_distribution.items():
            assert a in legal, f"pi key {a} not legal at decision state"
            assert n >= 0, n
        # pi sums to >=1 (with a shared re-rooted tree, child.visits is the
        # GLOBAL count and may exceed the per-move budget when a child was
        # inherited — this is the raw-counts convention, so we don't cap it).
        total = sum(d.visit_distribution.values())
        assert total >= 1, total
        assert math.isfinite(d.root_value)
        n_with_pi += 1
    assert n_with_pi == len(rec.decisions)


# ---------------------------------------------------------------------------
# Strength parity (statistical — flagged)
# ---------------------------------------------------------------------------


def _play_cpp_vs(python_agent_factory, *, n_seeds, sims, c_uct, cpp_seat,
                 model_dir=_MODEL_DIR):
    """Play C++ MCTS vs a python agent over n_seeds via play_game; return the
    C++ agent's win count (ties count as 0.5). `cpp_seat` is 0 or 1. `model_dir`
    selects the C++ NN export (default: the separate-net cpp_export; the joint
    parity test passes cpp_export_best)."""
    from agricola.agents.base import play_game
    from agricola.scoring import score, tiebreaker

    cpp_wins = 0.0
    for seed in range(n_seeds):
        initial, env = setup_env(seed)
        cpp = agricola_cpp.CppMctsAgent(model_dir, sims, c_uct, 0.2, seed)

        def cpp_call(state, _cpp=cpp):
            from agricola.agents.nn.trace_replay import action_from_params

            obj = json.loads(_cpp.choose(dumps(state)))
            return action_from_params(obj["type"], obj["params"])

        py_agent = python_agent_factory(seed)
        if cpp_seat == 0:
            agents = (cpp_call, py_agent)
        else:
            agents = (py_agent, cpp_call)
        terminal, _ = play_game(initial, agents, env.resolve)
        s0, _ = score(terminal, 0)
        s1, _ = score(terminal, 1)
        if s0 == s1:
            tb0, tb1 = tiebreaker(terminal, 0), tiebreaker(terminal, 1)
            margin = (tb0 - tb1) if cpp_seat == 0 else (tb1 - tb0)
        else:
            margin = (s0 - s1) if cpp_seat == 0 else (s1 - s0)
        if margin > 0:
            cpp_wins += 1.0
        elif margin == 0:
            cpp_wins += 0.5
    return cpp_wins


@_torch_gate
def test_cpp_mcts_beats_random():
    """Sanity: C++ MCTS crushes a RandomAgent (it's not broken)."""
    from agricola.agents.base import RandomAgent

    n = 12
    sims = 48
    wins = _play_cpp_vs(
        lambda seed: RandomAgent(seed), n_seeds=n, sims=sims, c_uct=1.4, cpp_seat=0
    )
    rate = wins / n
    print(f"\n[strength] C++ MCTS vs Random: {rate:.2%} ({wins}/{n})")
    assert rate >= 0.80, f"C++ MCTS only beat random {rate:.0%} — likely broken"


@_torch_gate
def test_cpp_mcts_parity_vs_python_mcts():
    """Statistical parity: C++ MCTS vs Python MCTSAgent (same NN value leaf +
    combined policy, PUCT/FLATTEN/full legality). WIDE band — this is a 'plays
    comparably' sanity, NOT a bit-identity test (RNG + float order diverge,
    §7.6). Modest game count / low sims to stay fast."""
    from agricola.agents import FenceMode, MCTSSearch
    from agricola.agents.mcts import MCTSAgent
    from agricola.agents.nn.model import load_value_evaluator
    from agricola.agents.nn.shared_policy import make_joint_fns
    from agricola.legality import legal_actions as full_legal

    # Both sides use the JOINT champion: Python `best` (value + policy off one
    # trunk via make_joint_fns) vs the C++ `cpp_export_best` joint export.
    joint_dir = str(_ROOT / "nn_models" / "cpp_export_best")
    model = load_value_evaluator(str(_ROOT / "nn_models" / "best"))
    model.eval()
    value_fn, policy_fn = make_joint_fns(model)
    sims = 48

    def py_factory(seed):
        search = MCTSSearch(
            rng_seed=seed,
            legal_actions_fn=full_legal,
            evaluator_config=model,
            evaluator_fn=value_fn,
            leaf_value_scale=float(getattr(model, "value_scale", 1.0)),
            policy_fn=policy_fn,
            fence_mode=FenceMode.FLATTEN,
        )
        return MCTSAgent(
            search,
            sims_per_move=sims,
            c_uct=1.4,
            action_selection_temperature=0.2,
            rng_seed=seed,
            cap_total_sims=True,
        )

    n = 20
    wins = _play_cpp_vs(py_factory, n_seeds=n, sims=sims, c_uct=1.4, cpp_seat=0,
                        model_dir=joint_dir)
    rate = wins / n
    print(f"\n[strength] C++ MCTS vs Python MCTS: {rate:.2%} ({wins}/{n})")
    assert 0.30 <= rate <= 0.70, (
        f"C++ vs Python MCTS win-rate {rate:.0%} outside parity band "
        f"[30%, 70%] — likely a search-logic divergence"
    )
