"""PROTOTYPE: measure the end-to-end wall win of jit.trace+freeze on the NN
forwards in the production MCTS workload (value leaf + combined policy PUCT).

Approach: swap each model's inner `.net` (the ConfigurableMLP) for a
`torch.jit.freeze(torch.jit.trace(net, example))` version. This keeps all the
wrapper logic (input/output normalization, masked softmax, the pointer segment
math) in Python and only compiles the dispatch-heavy MLP. `freeze` inlines the
weights as constants (so `model.parameters()` goes empty) → we pre-cache the
device via `model_device` BEFORE freezing.

Measures eager vs traced wall (min of N games each, interleaved to share the
machine-load state) and checks numerical equivalence on sample states.

    ~/miniconda3/bin/python scripts/proto_jit_trace.py --sims 160 --max-moves 40 --repeats 5
"""
from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _net_input_dim(model):
    """Input dim the inner net expects (value/fixed = 170; pointer = 170+cand)."""
    return int(model.net.config_dict()["input_dim"])


def traceify(model):
    """Replace model.net with a traced+frozen copy (in place). Pre-caches the
    device first (freeze empties model.parameters())."""
    import torch
    from agricola.agents.nn.model import model_device

    model.eval()
    model_device(model)                      # populate the device cache pre-freeze
    dim = _net_input_dim(model)
    ex = torch.randn(2, dim)
    with torch.no_grad(), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        traced = torch.jit.trace(model.net.eval(), ex)
        model.net = torch.jit.freeze(traced)
    return model


def load_models():
    """Load the value model + 9 policy/pointer head models (unweighted set)."""
    from agricola.agents.nn.model import NormalizedValueModel
    from agricola.agents.nn.policy import _load_head_model
    from scripts.nn.build_combined_policy import UNWEIGHTED_SET

    value = NormalizedValueModel.load(str(ROOT / "nn_models" / "best.pt"))
    heads = [_load_head_model(p) for p in UNWEIGHTED_SET]
    # CRITICAL: load() leaves models in TRAIN mode (dropout active). Production
    # (play_mcts_match.py) eval()s before search; do the same so the eager
    # baseline is correct and the eager-vs-traced comparison is apples-to-apples
    # (both eval = dropout is a no-op; the trace win is then pure dispatch).
    value.eval()
    for h in heads:
        h.eval()
    return value, heads


def build_search(value, heads, sims, seed=0):
    from agricola.agents.mcts import MCTSAgent, MCTSSearch, FenceMode
    from agricola.agents.nn.agent import nn_evaluator
    from agricola.agents.nn.policy import make_policy_fn

    search = MCTSSearch(
        evaluator_fn=nn_evaluator, evaluator_config=value,
        leaf_value_scale=11.526039123535156,
        policy_fn=make_policy_fn(heads), fence_mode=FenceMode.FLATTEN, rng_seed=seed,
    )
    return MCTSAgent(search, sims_per_move=sims, rng_seed=seed), search


def measure(value, heads, sims, max_moves, seed):
    from agricola.agents.base import decider_of
    from agricola.constants import Phase
    from agricola.engine import step
    from agricola.setup import setup_env
    from agricola.agents.nn.encoder import clear_encoding_cache

    clear_encoding_cache()
    agent, _ = build_search(value, heads, sims, seed=seed)
    state, env = setup_env(seed=seed)
    n = 0
    t0 = time.perf_counter()
    while state.phase != Phase.BEFORE_SCORING and n < max_moves:
        d = decider_of(state)
        if d is None:
            a = env.resolve(state)
        else:
            a = agent(state); n += 1
        state = step(state, a)
    return time.perf_counter() - t0


def equivalence_check(value_eager, value_traced):
    """Compare eager vs traced predict_margin over a corpus of real states."""
    import numpy as np
    import torch
    from agricola.agents.base import decider_of
    from agricola.constants import Phase
    from agricola.engine import step
    from agricola.legality import legal_actions
    from agricola.setup import setup_env
    from agricola.agents.nn.encoder import encode_state
    from tests.test_utils import filter_implemented

    rng = np.random.default_rng(0); states = []
    for sd in range(3):
        s, env = setup_env(seed=sd); k = 0
        while s.phase != Phase.BEFORE_SCORING and k < 200:
            d = decider_of(s)
            if d is None:
                a = env.resolve(s)
            else:
                states.append(s)
                acts = filter_implemented(legal_actions(s)); a = acts[int(rng.integers(len(acts)))]
            s = step(s, a); k += 1
    max_abs = 0.0
    with torch.no_grad():
        for s in states[:1500]:
            x = torch.from_numpy(encode_state(s, 0)).unsqueeze(0)
            e = float(value_eager.predict_margin(x).item())
            t = float(value_traced.predict_margin(x).item())
            max_abs = max(max_abs, abs(e - t))
    return max_abs, len(states)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=160)
    ap.add_argument("--max-moves", type=int, default=40)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    import torch
    torch.set_num_threads(1)

    # Two independent model sets so eager stays eager while we trace the other.
    value_e, heads_e = load_models()
    value_t, heads_t = load_models()
    for m in [value_t, *heads_t]:
        traceify(m)

    max_abs, n_states = equivalence_check(value_e, value_t)
    print(f"value predict_margin eager-vs-traced: max|Δ|={max_abs:.2e} "
          f"over {n_states} states (margin units)")

    # Warm both (jit warmup + lazy init), not timed.
    measure(value_e, heads_e, args.sims, 3, args.seed)
    measure(value_t, heads_t, args.sims, 3, args.seed)

    eager, traced = [], []
    for i in range(args.repeats):
        eager.append(measure(value_e, heads_e, args.sims, args.max_moves, args.seed))
        traced.append(measure(value_t, heads_t, args.sims, args.max_moves, args.seed))
    eager.sort(); traced.sort()
    mv = args.max_moves
    print(f"\nrepeats={args.repeats} (interleaved), single-thread, sims={args.sims}")
    print(f"  EAGER : min={eager[0]:.2f}s ({eager[0]/mv*1000:.1f} ms/move)  "
          f"all={[round(x,2) for x in eager]}")
    print(f"  TRACED: min={traced[0]:.2f}s ({traced[0]/mv*1000:.1f} ms/move)  "
          f"all={[round(x,2) for x in traced]}")
    print(f"  speedup (min/min): {eager[0]/traced[0]:.2f}x  "
          f"({(1-traced[0]/eager[0])*100:.0f}% faster)")


if __name__ == "__main__":
    main()
