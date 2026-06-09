"""Microbench: the `stop_is_legal` computation in encode_state, 3 ways.

Captures the EXACT states encode_state is called on during a production PUCT
run, then times three ways to compute `stop_is_legal` over that corpus and
asserts they agree with the current (full-legal-actions) behaviour:

  M0  current : any(Stop in legal_actions(state))                 [baseline]
  M1  guard   : bool(pending_stack) and any(Stop in legal_actions(state))
  M2  direct  : empty-stack -> False; PBF/HarvestFeed -> cheap flag;
                else top-frame enumerator                          [fastest]

Also reports how the encoded states split empty- vs non-empty-stack, and the
per-frame-type breakdown of the non-empty ones (so we can see whether the
guard's residual enumeration cost is concentrated in expensive frames).
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def capture_states(n_states=4000, sims=160, seed=0):
    """Run a production PUCT game, capturing every state encode_state sees."""
    import torch
    torch.set_num_threads(1)
    import agricola.agents.nn.agent as agent_mod
    import agricola.agents.nn.policy as policy_mod
    from agricola.agents.mcts import MCTSAgent, MCTSSearch, FenceMode
    from agricola.agents.nn.agent import nn_evaluator
    from agricola.agents.nn.model import NormalizedValueModel
    from agricola.agents.base import decider_of
    from agricola.constants import Phase
    from agricola.engine import step
    from agricola.setup import setup_env
    from scripts.nn.build_combined_policy import build

    captured = []
    # agent.py / policy.py now call `encode_for_inference` (the cached/swap-aware
    # path), not `encode_state` directly — spy on that.
    real_encode = agent_mod.encode_for_inference

    def spy(state, player_idx):
        if len(captured) < n_states:
            captured.append(state)
        return real_encode(state, player_idx)

    agent_mod.encode_for_inference = spy
    policy_mod.encode_for_inference = spy

    model = NormalizedValueModel.load(str(ROOT / "nn_models" / "best.pt"))
    search = MCTSSearch(
        evaluator_fn=nn_evaluator, evaluator_config=model,
        leaf_value_scale=11.526039123535156,
        policy_fn=build("unweighted"), fence_mode=FenceMode.FLATTEN, rng_seed=seed,
    )
    agent = MCTSAgent(search, sims_per_move=sims, rng_seed=seed)

    state, env = setup_env(seed=seed)
    while state.phase != Phase.BEFORE_SCORING and len(captured) < n_states:
        d = decider_of(state)
        action = env.resolve(state) if d is None else agent(state)
        state = step(state, action)

    agent_mod.encode_for_inference = real_encode
    policy_mod.encode_for_inference = real_encode
    return captured


def main():
    from agricola.actions import Stop
    from agricola.legality import legal_actions
    from agricola.pending import PendingBuildFences, PendingHarvestFeed

    print("capturing encoded states from a production PUCT run...")
    states = capture_states()
    print(f"captured {len(states)} states\n")

    # Split stats.
    empty = sum(1 for s in states if not s.pending_stack)
    frame_types = Counter(
        type(s.pending_stack[-1]).__name__ for s in states if s.pending_stack
    )
    print(f"empty-stack (placement): {empty} ({empty/len(states)*100:.1f}%)")
    print(f"non-empty-stack:         {len(states)-empty} "
          f"({(len(states)-empty)/len(states)*100:.1f}%)")
    print("non-empty top-frame breakdown:")
    for name, c in frame_types.most_common():
        print(f"    {name:<28} {c}")
    print()

    def m0(s):  # current
        return any(isinstance(a, Stop) for a in legal_actions(s))

    def m1(s):  # guard
        return bool(s.pending_stack) and any(isinstance(a, Stop) for a in legal_actions(s))

    def m2(s):  # direct
        if not s.pending_stack:
            return False
        top = s.pending_stack[-1]
        if isinstance(top, PendingBuildFences):
            return top.pastures_built >= 1
        if isinstance(top, PendingHarvestFeed):
            return top.conversion_done
        return any(isinstance(a, Stop) for a in legal_actions(s))

    # Equivalence check FIRST (correctness gate).
    bad1 = [s for s in states if m1(s) != m0(s)]
    bad2 = [s for s in states if m2(s) != m0(s)]
    print(f"equivalence vs current: guard mismatches={len(bad1)}  "
          f"direct mismatches={len(bad2)}")
    if bad2:
        s = bad2[0]
        print(f"  first direct mismatch: top="
              f"{type(s.pending_stack[-1]).__name__ if s.pending_stack else None}")
    print()

    # Timing.
    REPS = 20
    for name, fn in (("M0 current", m0), ("M1 guard", m1), ("M2 direct", m2)):
        t0 = time.perf_counter()
        for _ in range(REPS):
            for s in states:
                fn(s)
        dt = time.perf_counter() - t0
        per = dt / (REPS * len(states)) * 1e6
        print(f"{name:<12} {dt:6.3f}s total  {per:7.2f} us/call")


if __name__ == "__main__":
    main()
