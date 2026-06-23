"""Decisive test of the RNG-vs-deterministic-c_uct hypothesis.

Replays agricola-trace-seed8836.json to its final state, then for each c_uct
runs the native MCTS across many RNG seeds (mcts_debug_root, 1600 sims,
prior_mix is baked into the model's policy path — note: mcts_debug_root does
NOT set prior_uniform_mix, so this is the pure-policy regime; see caveat in
output). Reports how the top action / visit split varies with seed.

If the Fishing-vs-Cattle outcome is stable across seeds at fixed c_uct, RNG is
not the driver (deterministic c_uct dynamics). If it flips across seeds, RNG is
a driver.
"""
import json
import sys
from collections import Counter
from pathlib import Path

from agricola.setup import setup_env
from agricola.engine import step
from agricola.canonical import dumps
from agricola.agents.base import decider_of
from agricola.agents.nn.trace_replay import action_from_params

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cpp" / "build"))
import agricola_cpp  # noqa: E402

EXPORT = str(ROOT / "nn_models" / "cpp_export_best")
SIMS = 1600
N_SEEDS = 16
PRIOR_MIX = 0.05  # faithful to the analyze overlay regime

with open(ROOT / "agricola-trace-seed8836.json") as f:
    trace = json.load(f)

state, env = setup_env(trace["seed"])
for entry in trace["actions"]:
    if entry["type"] == "RevealCard":
        action = env.reveal_action(state)
    else:
        action = action_from_params(entry["type"], entry["params"])
    state = step(state, action)

print(f"final round={state.round_number} phase={state.phase.name} "
      f"decider={decider_of(state)}  sims={SIMS}  seeds=0..{N_SEEDS-1}  "
      f"prior_mix={PRIOR_MIX}\n")
state_json = dumps(state)


def label(action_json):
    a = json.loads(action_json) if isinstance(action_json, str) else action_json
    p = a.get("params", {})
    return p.get("space", a.get("type", "?"))


for c_uct in [0.40, 0.50, 0.55, 1.00]:
    rows = []
    for seed in range(N_SEEDS):
        dbg = agricola_cpp.mcts_debug_root(EXPORT, state_json, SIMS, c_uct,
                                           seed, PRIOR_MIX)
        vd = sorted(dbg["visit_distribution"], key=lambda pr: -pr[1])
        top_label, top_v = label(vd[0][0]), vd[0][1]
        second = label(vd[1][0]) if len(vd) > 1 else "-"
        second_v = vd[1][1] if len(vd) > 1 else 0
        rows.append((seed, top_label, top_v, second, second_v))
    winners = Counter(r[1] for r in rows)
    print(f"c_uct={c_uct}:  top-action across {N_SEEDS} seeds -> {dict(winners)}")
    for seed, tl, tv, sl, sv in rows:
        print(f"    seed={seed:<2} top={tl:<16} v={tv:<5} 2nd={sl:<14} v={sv}")
    print()
