"""Measure the encoding-collision rate for the value/policy-by-encoding cache.

Hypothesis (user): because `encode_state` is lossy (no spatial info, aggregated
counts), many DISTINCT GameStates map to the SAME 170-d encoding — so caching NN
outputs keyed on the encoding bytes would skip forward passes that the
GameState-keyed transposition table cannot dedup.

This instrument hooks `encode_state` during a production PUCT game and reports,
per perspective:
  - total encode calls
  - distinct encodings        (the cache's working set)
  - distinct GameStates        (object-identity, what the DAG already dedups)
  - encoding repeat rate       = 1 - distinct_encodings / total_calls
        -> the fraction of forwards an encoding-keyed cache could skip
  - GameState repeat rate      = 1 - distinct_gamestates / total_calls
        -> repeats the DAG node-cache / value+policy double-encode already incur
  - collisions: distinct GameStates that share an encoding (the *extra* hits the
        encoding cache buys over a GameState-keyed cache)

The forward-pass savings ceiling = encoding-repeat-rate x forward cost. encode
itself is NOT saved (you must encode to get the key).
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(sims=160, max_moves=80, seed=0):
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

    # records[player_idx] = list of (encoding_bytes, gamestate_hash)
    records = {0: [], 1: []}
    # agent.py / policy.py call `encode_for_inference` (the cached/swap-aware path).
    real_encode = agent_mod.encode_for_inference

    def spy(state, player_idx):
        arr = real_encode(state, player_idx)
        records[player_idx].append((arr.tobytes(), hash(state)))
        return arr

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
    moves = 0
    while state.phase != Phase.BEFORE_SCORING and moves < max_moves:
        d = decider_of(state)
        if d is None:
            action = env.resolve(state)
        else:
            action = agent(state)
            moves += 1
        state = step(state, action)

    agent_mod.encode_for_inference = real_encode
    policy_mod.encode_for_inference = real_encode

    print(f"=== encoding-collision report: sims={sims} moves={moves} seed={seed} ===\n")
    # Combined + per-perspective.
    for label, recs in (("perspective 0", records[0]),
                        ("perspective 1", records[1]),
                        ("ALL (both)", records[0] + records[1])):
        total = len(recs)
        if not total:
            continue
        encs = [e for e, _ in recs]
        gss = [g for _, g in recs]
        uniq_enc = len(set(encs))
        uniq_gs = len(set(gss))
        # distinct GameStates per encoding (collisions).
        gs_by_enc = defaultdict(set)
        for e, g in recs:
            gs_by_enc[e].add(g)
        colliding_encs = sum(1 for s in gs_by_enc.values() if len(s) > 1)
        extra_hits = sum(len(s) - 1 for s in gs_by_enc.values())  # distinct GS folded away
        print(f"[{label}] calls={total}")
        print(f"    distinct encodings = {uniq_enc}  "
              f"(encoding repeat rate = {(1-uniq_enc/total)*100:.1f}%  "
              f"-> forwards skippable by an encoding cache)")
        print(f"    distinct GameStates = {uniq_gs}  "
              f"(GameState repeat rate = {(1-uniq_gs/total)*100:.1f}%)")
        print(f"    encodings hit by >1 distinct GameState = {colliding_encs}  "
              f"({colliding_encs/uniq_enc*100:.1f}% of encodings)")
        print(f"    distinct GameStates folded by encoding-key = {extra_hits}  "
              f"({extra_hits/total*100:.1f}% of calls = the EXTRA win over a "
              f"GameState-keyed cache)")
        print()


if __name__ == "__main__":
    main()
