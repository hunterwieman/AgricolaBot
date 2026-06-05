"""The two combined policy functions — one all-`unweighted`, one all-`awr`.

Each is the full multi-head `policy_fn(state, legal) -> {action: prior}` that
MCTS/PUCT consumes (`agricola.agents.nn.policy.make_policy_fn` semantics): it
dispatches by decision type across the trained heads, and falls back to
uniform-over-cell-priority (plow/build cells) or uniform-over-full-legal
(anything else without a head) — see POLICY_HEAD.md.

`UNWEIGHTED_SET` / `AWR_SET` list the head checkpoints for each variant — the
checkpoints differ only in their training loss (unweighted CE vs advantage-weighted
CE). Build one with:

    from scripts.nn.build_combined_policy import build
    policy_fn = build("unweighted")        # or "awr"

CLI: `python scripts/nn/build_combined_policy.py` sanity-checks that both
variants' checkpoints load and produce a prior at a sample decision.

Fencing (`fencing` head, 109 shapes + Stop) is included as an experiment — it has
no spatial encoder signal, so it leans on the legal mask + learned canonical-shape
preferences; trained with FULL legality (no restricted/strict wrapper).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from agricola.agents.nn.policy import load_policy_fn  # noqa: E402

_UNWEIGHTED = [
    "policy_placement_v2_unweighted",
    "policy_choose_subaction_unweighted",
    "policy_commit_build_major_unweighted",
    "policy_commit_sow_unweighted",
    "policy_commit_bake_unweighted",
    "policy_build_stop_unweighted",
    "policy_fencing_unweighted",
    "pointer_animal_frontier_unweighted",
    "pointer_harvest_feed_unweighted",
]
_AWR = [
    "policy_placement_v2_awr",
    "policy_choose_subaction_awr",
    "policy_commit_build_major_awr",
    "policy_commit_sow_awr",
    "policy_commit_bake_awr",
    "policy_build_stop_awr",
    "policy_fencing_awr",
    "pointer_animal_frontier_awr",
    "pointer_harvest_feed_awr",
]

UNWEIGHTED_SET = [ROOT / "nn_models" / d / "best" for d in _UNWEIGHTED]
AWR_SET = [ROOT / "nn_models" / d / "best" for d in _AWR]
SETS = {"unweighted": UNWEIGHTED_SET, "awr": AWR_SET}


def build(variant: str):
    """Return the combined `policy_fn` for `variant` ('unweighted' or 'awr')."""
    if variant not in SETS:
        raise ValueError(f"variant must be one of {sorted(SETS)}; got {variant!r}")
    return load_policy_fn(SETS[variant])


def _sanity_check() -> int:
    from agricola.legality import legal_actions
    from agricola.setup import setup_env
    from tests.test_utils import filter_implemented

    state, _ = setup_env(seed=7)
    legal = filter_implemented(legal_actions(state))
    rc = 0
    for variant in ("unweighted", "awr"):
        missing = [p for p in SETS[variant] if not p.with_suffix(".meta.json").exists()]
        if missing:
            print(f"[{variant}] MISSING {len(missing)} checkpoint(s):")
            for p in missing:
                print(f"    {p}")
            rc = 1
            continue
        pf = build(variant)
        prior = pf(state, legal)
        print(f"[{variant}] OK — loaded {len(SETS[variant])} heads; "
              f"placement prior over {len(prior)} actions (sum={sum(prior.values()):.3f})")
    return rc


if __name__ == "__main__":
    sys.exit(_sanity_check())
