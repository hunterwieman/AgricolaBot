"""Profile the PRODUCTION MCTS workload: NN value leaf + combined policy PUCT.

Every profile in PROFILING.md used the V3 heuristic as the leaf evaluator. The
real data-gen workload uses a trained NN value net as the leaf AND a 9-head
combined policy as the PUCT prior. This script profiles THAT path so the hot
spots reflect what data generation actually pays.

Rather than compare a PUCT run to a UCT run (confounded — different fence modes,
different tree shapes, different states reached), we measure each cost component
DIRECTLY by wrapping the relevant callables in accumulating timers during one
production (PUCT) run:

  - policy_fn        -> all PUCT-prior cost (encode + mask + the owning head fwd)
  - evaluator_fn     -> all NN value-leaf cost (2x encode + batched-2 fwd)
  - encode_state     -> shared encoder cost (called from BOTH of the above)
  - step             -> engine transition cost
  - legal_actions_fn -> strict-restricted legality enumeration

The remainder (total - policy - value) is "engine + search bookkeeping"
(selection, backprop, hashing, transposition table).

Usage (conda base python has torch):
    ~/miniconda3/bin/python scripts/profile_mcts_nn.py --sims 160 --max-moves 40
    ~/miniconda3/bin/python scripts/profile_mcts_nn.py --sims 160 --max-moves 40 --cprofile
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class Timer:
    """Accumulating call-timer wrapper."""
    def __init__(self, fn, label):
        self.fn = fn
        self.label = label
        self.total = 0.0
        self.calls = 0

    def __call__(self, *a, **k):
        t0 = time.perf_counter()
        try:
            return self.fn(*a, **k)
        finally:
            self.total += time.perf_counter() - t0
            self.calls += 1

    def report(self, denom):
        per = self.total / self.calls * 1e6 if self.calls else 0.0
        pct = self.total / denom * 100 if denom else 0.0
        print(f"  {self.label:<22} {self.total:7.2f}s  {pct:5.1f}%  "
              f"calls={self.calls:>8}  {per:7.1f} us/call")


def build_search(sims, seed=0, single_pass=False):
    from agricola.agents.mcts import MCTSAgent, MCTSSearch, FenceMode
    from agricola.agents.nn.agent import nn_evaluator, nn_evaluator_differential
    from agricola.agents.nn.model import NormalizedValueModel
    from scripts.nn.build_combined_policy import build

    model = NormalizedValueModel.load(str(ROOT / "nn_models" / "best.pt"))
    model.eval()   # load() leaves TRAIN mode → dropout; production evals (play_mcts_match)
    value_scale = 11.526039123535156  # from best.meta.json
    policy_fn = build("unweighted")    # make_policy_fn now eval()s the heads
    evaluator_fn = nn_evaluator if single_pass else nn_evaluator_differential

    search = MCTSSearch(
        evaluator_fn=evaluator_fn,
        evaluator_config=model,
        leaf_value_scale=value_scale,
        policy_fn=policy_fn,
        fence_mode=FenceMode.FLATTEN,
        rng_seed=seed,
    )
    agent = MCTSAgent(search, sims_per_move=sims, rng_seed=seed)
    return agent, search


def instrument(search):
    """Wrap the cost-bearing callables in Timers; return the timer dict.

    The encoder is captured at two layers: `encode_for_inference` (logical encode
    requests, monkeypatched on agent.py + policy.py) and `encode_state` (the
    actual computation, run only on cache MISSES inside `_encode_p0`). The gap
    between the two call counts is the swap/cache hit rate.
    """
    import agricola.agents.nn.agent as agent_mod
    import agricola.agents.nn.policy as policy_mod
    import agricola.agents.nn.encoder as enc_mod

    timers = {}
    timers["policy_fn"] = Timer(search.policy_fn, "policy_fn (prior)")
    search.policy_fn = timers["policy_fn"]
    timers["evaluator_fn"] = Timer(search.evaluator_fn, "evaluator_fn (value)")
    search.evaluator_fn = timers["evaluator_fn"]
    timers["legal_actions_fn"] = Timer(search.legal_actions_fn, "legal_actions_fn")
    search.legal_actions_fn = timers["legal_actions_fn"]

    enc_logical = Timer(agent_mod.encode_for_inference, "encode (logical)")
    timers["encode_logical"] = enc_logical
    agent_mod.encode_for_inference = enc_logical
    policy_mod.encode_for_inference = enc_logical

    # encode_state is called only on _encode_p0 cache misses (real encodes).
    timers["encode_real"] = Timer(enc_mod.encode_state, "encode_state (real/miss)")
    enc_mod.encode_state = timers["encode_real"]

    # step is called all over the engine; wrap the symbol the mcts module uses.
    import agricola.agents.mcts as mcts_mod
    timers["step"] = Timer(mcts_mod.step, "step (engine)")
    mcts_mod.step = timers["step"]
    return timers


def play_n_moves(agent, search, max_moves, seed=0):
    from agricola.agents.base import decider_of
    from agricola.constants import Phase
    from agricola.engine import step
    from agricola.setup import setup_env

    state, env = setup_env(seed=seed)
    moves = 0
    per_move = []
    while state.phase != Phase.BEFORE_SCORING and moves < max_moves:
        d = decider_of(state)
        if d is None:
            action = env.resolve(state)
        else:
            t0 = time.perf_counter()
            action = agent(state)
            per_move.append(time.perf_counter() - t0)
            moves += 1
        state = step(state, action)
    return per_move


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sims", type=int, default=160)
    ap.add_argument("--max-moves", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=1,
                    help="torch.set_num_threads (1 mirrors per-worker data-gen).")
    ap.add_argument("--single-pass", action="store_true",
                    help="use single-pass nn_evaluator instead of differential.")
    ap.add_argument("--cprofile", action="store_true",
                    help="also run cProfile for the function-level breakdown.")
    ap.add_argument("--wall-only", action="store_true",
                    help="wall-clock only (NO instrument) — runs on old code too; "
                         "for git-stash A/B. Use with --repeats for min-of-N.")
    ap.add_argument("--repeats", type=int, default=1,
                    help="wall-only: timed games (fresh tree each), report min/med.")
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    import torch
    torch.set_num_threads(args.threads)
    print(f"=== MCTS-NN PRODUCTION profile (PUCT): sims={args.sims} "
          f"max_moves={args.max_moves} torch_threads={args.threads} ===")

    # Warm up (lazy model/cache init) on a throwaway agent, NOT timed.
    a0, s0 = build_search(args.sims, seed=args.seed, single_pass=args.single_pass)
    play_n_moves(a0, s0, 2, seed=args.seed)

    if args.wall_only:
        # No instrument (works on pre-rewrite code with no encode_for_inference).
        # Fresh tree + cold encode cache each repeat → per-game-cold, comparable
        # across code versions. Report min (least-contended) + median.
        walls = []
        for _ in range(args.repeats):
            try:
                from agricola.agents.nn.encoder import clear_encoding_cache
                clear_encoding_cache()
            except Exception:
                pass
            agent, search = build_search(
                args.sims, seed=args.seed, single_pass=args.single_pass)
            t0 = time.perf_counter()
            play_n_moves(agent, search, args.max_moves, seed=args.seed)
            walls.append(time.perf_counter() - t0)
        walls.sort()
        mv = args.max_moves
        print(f"\nwall-only repeats={args.repeats}: "
              f"min={walls[0]:.2f}s ({walls[0]/mv*1000:.1f} ms/move)  "
              f"med={walls[len(walls)//2]:.2f}s "
              f"({walls[len(walls)//2]/mv*1000:.1f} ms/move)  "
              f"all={[round(w,2) for w in walls]}")
        return

    if args.cprofile:
        # Clean function-level view: NO instrumentation (monkeypatching would
        # show Timer.__call__ and skew self-times). Smaller slice for speed.
        import cProfile, io, pstats
        agent2, search2 = build_search(args.sims, seed=args.seed, single_pass=args.single_pass)
        pr = cProfile.Profile()
        pr.enable()
        play_n_moves(agent2, search2, max(8, args.max_moves // 4), seed=args.seed)
        pr.disable()
        s = io.StringIO()
        pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(args.top)
        print("\n========== cProfile TOP BY SELF TIME ==========")
        print(s.getvalue())
        return

    agent, search = build_search(args.sims, seed=args.seed, single_pass=args.single_pass)
    timers = instrument(search)

    # The encoding memo is module-global; the warmup populated it. Clear so the
    # measured run starts cold (realistic per-game cache behaviour).
    from agricola.agents.nn.encoder import clear_encoding_cache
    clear_encoding_cache()

    t0 = time.perf_counter()
    per_move = play_n_moves(agent, search, args.max_moves, seed=args.seed)
    wall = time.perf_counter() - t0

    n = len(per_move)
    print(f"\nWall: {wall:.2f}s over {n} moves "
          f"= {wall / max(n,1)*1000:.1f} ms/move "
          f"({wall / max(n,1) / args.sims * 1e6:.1f} us/sim)")
    if per_move:
        srt = sorted(per_move)
        print(f"per-move ms: min={srt[0]*1000:.1f} "
              f"med={srt[len(srt)//2]*1000:.1f} max={srt[-1]*1000:.1f}")

    print("\n--- DIRECT cost attribution (wrapped callables) ---")
    print(f"  {'component':<26} {'total':>7}   {'%wall':>5}  {'calls':>13}   per-call")
    # Order: the two NN paths, the encoder (logical req + real misses), engine.
    for key in ("evaluator_fn", "policy_fn", "encode_logical", "encode_real",
                "legal_actions_fn", "step"):
        timers[key].report(wall)
    nn_total = timers["evaluator_fn"].total + timers["policy_fn"].total
    el, er = timers["encode_logical"], timers["encode_real"]
    hit = (1 - er.calls / el.calls) * 100 if el.calls else 0.0
    print(f"\n  encode cache/swap hit rate: {hit:.1f}% "
          f"({el.calls} logical → {er.calls} real encodes)")
    print(f"  NN total (value+policy): {nn_total:.2f}s = {nn_total/wall*100:.1f}% of wall")
    print(f"  (encoders are a SUBSET of value+policy — not additive.)")
    other = wall - nn_total
    print(f"  Non-NN remainder (engine+search): {other:.2f}s = {other/wall*100:.1f}% of wall")


if __name__ == "__main__":
    main()
