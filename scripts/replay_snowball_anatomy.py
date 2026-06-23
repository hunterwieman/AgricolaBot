"""Anatomy of the Fishing-island nonlinearity.

(1) Dump per-child prior + searched Q for the contender actions (constant priors
    across c_uct; the priors + shallow Qs are the 'fuel' of the early race).
(2) Trace the root visit counts of the contenders as a function of sim budget at
    the pivotal c_uct values, to watch which action wins the early race and
    snowballs.
"""
import json
import sys
from pathlib import Path

from agricola.setup import setup_env
from agricola.engine import step
from agricola.canonical import dumps
from agricola.agents.nn.trace_replay import action_from_params

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cpp" / "build"))
import agricola_cpp  # noqa: E402

EXPORT = str(ROOT / "nn_models" / "cpp_export_best")
PRIOR_MIX = 0.05
CONTENDERS = ("fishing", "cattle_market", "farmland")

with open(ROOT / "agricola-trace-seed8836.json") as f:
    trace = json.load(f)
state, env = setup_env(trace["seed"])
for entry in trace["actions"]:
    action = (env.reveal_action(state) if entry["type"] == "RevealCard"
              else action_from_params(entry["type"], entry["params"]))
    state = step(state, action)
state_json = dumps(state)


def lbl(aj):
    a = json.loads(aj) if isinstance(aj, str) else aj
    return a.get("params", {}).get("space", a.get("type", "?"))


def run(c_uct, sims):
    return agricola_cpp.mcts_debug_root(EXPORT, state_json, sims, c_uct, 0, PRIOR_MIX)


# (1) priors are constant in c_uct; print them once (from a small run), plus the
#     "shallow Q" each action gets once visited a handful of times.
dbg = run(0.5, 1600)
detail = {lbl(r[0]): (r[1], r[2], r[3]) for r in dbg["children_detail"]}
print("per-child  prior      (priors are independent of c_uct):")
for name, (prior, visits, q) in sorted(detail.items(), key=lambda kv: -kv[1][0])[:8]:
    print(f"    {name:<22} prior={prior:.4f}")
print()

# (2) snowball trajectory: contender visit counts vs sim budget.
SIM_GRID = [16, 30, 50, 100, 200, 400, 800, 1600]
for c_uct in [0.48, 0.50, 0.55, 0.60]:
    print(f"c_uct={c_uct}:  contender visits vs sim budget")
    header = "    sims  " + "".join(f"{c:>16}" for c in CONTENDERS)
    print(header)
    for sims in SIM_GRID:
        d = run(c_uct, sims)
        vis = {lbl(a): n for a, n in d["visit_distribution"]}
        det = {lbl(r[0]): r for r in d["children_detail"]}
        cells = []
        for c in CONTENDERS:
            n = vis.get(c, 0)
            q = det.get(c, [None, None, None, None])[3]
            qs = f"{q:+.2f}" if isinstance(q, (int, float)) else "  -  "
            cells.append(f"{n:>6}({qs})")
        print(f"    {sims:>4}  " + "".join(f"{c:>16}" for c in cells))
    print()
