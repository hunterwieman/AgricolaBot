"""Replay agricola-trace-seed8836.json to its final state, then sweep the
analysis MCTS over c_uct values and report the per-action visit counts.

Investigates whether the top-action flip at c_uct=0.5 is a value-specific
anomaly or a chaotic knife-edge of low-c_uct winner-take-all PUCT.
"""
import json
import os
import subprocess
import sys

from agricola.setup import setup_env
from agricola.engine import step
from agricola.canonical import dumps
from agricola.agents.base import decider_of
from agricola.agents.nn.trace_replay import action_from_params

TRACE = "agricola-trace-seed8836.json"
BINARY = "cpp/build/selfplay"
EXPORT = "nn_models/cpp_export_best"
SIMS = 1600
PRIOR_MIX = 0.05

with open(TRACE) as f:
    trace = json.load(f)

state, env = setup_env(trace["seed"])
for entry in trace["actions"]:
    if entry["type"] == "RevealCard":
        # Web trace drops the card name; reconstruct from the deterministic
        # reveal order in the environment (same seed → same card).
        action = env.reveal_action(state)
    else:
        action = action_from_params(entry["type"], entry["params"])
    state = step(state, action)

print(f"final round={state.round_number} phase={state.phase.name} "
      f"decider={decider_of(state)}")
state_json = dumps(state)

def run(c_uct: float):
    cmd = [BINARY, "--analyze", "--model-dir", EXPORT,
           "--sims", str(SIMS), "--c-uct", repr(c_uct),
           "--temperature", "0.2", "--prior-mix", str(PRIOR_MIX)]
    out = subprocess.run(cmd, input=state_json, capture_output=True,
                         text=True, check=True).stdout
    children = json.loads(out)["children"]
    children.sort(key=lambda c: -c["visits"])
    return children

sweep = [0.30, 0.40, 0.45, 0.48, 0.49, 0.50, 0.51, 0.52, 0.55, 0.60, 0.70, 1.0]
for c in sweep:
    kids = run(c)
    top = kids[0]
    second = kids[1] if len(kids) > 1 else {"params": {}, "visits": 0, "q": 0}
    def label(k):
        p = k["params"]
        return p.get("space", k.get("type", "?"))
    print(f"c_uct={c:<5} top={label(top):<22} v={top['visits']:<5} q={top['q']:+.2f}"
          f"  | 2nd={label(second):<18} v={second['visits']:<5} q={second['q']:+.2f}"
          f"  | total_v={sum(k['visits'] for k in kids)}")
