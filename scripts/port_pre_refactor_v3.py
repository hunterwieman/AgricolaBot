"""Port a pre-refactor V3 JSON into the post-refactor `HeuristicConfigV3` schema.

The refactor (CHANGES.md Change 10, 2026-05-23) introduced 48 new per-stage
major-improvement scalars and switched the evaluator to use them via
`_hubris_major_value_v3`. The OLD scalar fields (fireplace_value,
fireplace_value_mid, fireplace_value_late, hearth_value, hearth_value_mid,
hearth_value_late, well_value, well_food_per_future, clay_oven_value,
stone_oven_value, joinery_value, pottery_value, basketmaker_value,
cooking_secondary_vp) are still ON the dataclass for backwards-compat
but NOT READ by the new evaluator.

A direct `HeuristicConfigV3(**old_json["best_config"])` populates the OLD
fields but leaves the NEW per-stage arrays at their defaults (which are
V1_T2-derived for cooking, hand-picked for everything else). So loading
an iter1 JSON doesn't actually use iter1's tuned major values.

This script does the port mechanically:

  fireplace_value_by_stage[0..3] = old["fireplace_value"]       (stages 1-4)
  fireplace_value_by_stage[4]    = old["fireplace_value_mid"]   (stage 5)
  fireplace_value_by_stage[5]    = old["fireplace_value_late"]  (stage 6)
  hearth_value_by_stage[...] same pattern
  well_value_by_stage[0..5]      = old["well_value"]            (flat — lose well_food_per_future)
  <other>_value_by_stage[0..5]   = old["<other>_value"]         (flat broadcast)

cooking_secondary_vp is dropped (refactor hard-codes "extra cooking = +1").
pasture_location_bonus is preserved as-is (the bonus value); the SEMANTIC
changed under the refactor (c≥3 cells only vs old c≥2) — we can't recover
the old semantic without reverting the helper.

Outputs a NEW JSON file. Then runs a 40-game match: ported V3 vs V1+T2.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path("/Users/hunterwieman/Desktop/Agricola/AgricolaBot")
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from agricola.agents import (
    CONFIG_V1_T2, HeuristicConfigV3,
    HubrisHeuristicV1, HubrisHeuristicV3,
    restricted_legal_actions,
)
from play_match import play_match


def port_old_to_new(old_bc: dict) -> dict:
    """Take an old (pre-refactor) best_config dict and produce a new (post-refactor)
    dict with the per-stage major arrays populated from the old scalars."""
    new_bc = dict(old_bc)  # copy old fields (most are still on the schema)

    # ---- Cooking implements: V1_T2-style 3-tier mapping per stage ----
    # fireplace_value (full) → stages 1-4 (indices 0-3)
    # fireplace_value_mid    → stage 5 (index 4)
    # fireplace_value_late   → stage 6 (index 5)
    new_bc["fireplace_value_by_stage"] = (
        [old_bc["fireplace_value"]] * 4
        + [old_bc["fireplace_value_mid"]]
        + [old_bc["fireplace_value_late"]]
    )
    new_bc["hearth_value_by_stage"] = (
        [old_bc["hearth_value"]] * 4
        + [old_bc["hearth_value_mid"]]
        + [old_bc["hearth_value_late"]]
    )

    # ---- Other majors: broadcast single scalar across all 6 stages ----
    # Well loses its `well_food_per_future` term (the refactor dropped it).
    for old_field, new_field in [
        ("well_value", "well_value_by_stage"),
        ("clay_oven_value", "clay_oven_value_by_stage"),
        ("stone_oven_value", "stone_oven_value_by_stage"),
        ("joinery_value", "joinery_value_by_stage"),
        ("pottery_value", "pottery_value_by_stage"),
        ("basketmaker_value", "basketmaker_value_by_stage"),
    ]:
        new_bc[new_field] = [old_bc[old_field]] * 6

    return new_bc


def main() -> int:
    SRC = ROOT / "tuned_configs" / "iter_p2_v3_fields_crops.json"
    DST = ROOT / "tuned_configs" / "iter1_v3_ported_to_refactor.json"

    with open(SRC) as f:
        src = json.load(f)
    old_bc = src["best_config"]

    new_bc = port_old_to_new(old_bc)
    cfg = HeuristicConfigV3(**new_bc)  # construct the dataclass — validates field names

    # Sanity-check the new per-stage fields
    print(f"Source: {SRC.name}")
    print(f"Ported field samples:")
    print(f"  fireplace_value_by_stage = {cfg.fireplace_value_by_stage}")
    print(f"  hearth_value_by_stage    = {cfg.hearth_value_by_stage}")
    print(f"  well_value_by_stage      = {cfg.well_value_by_stage}")
    print(f"  clay_oven_value_by_stage = {cfg.clay_oven_value_by_stage}")
    print(f"  joinery_value_by_stage   = {cfg.joinery_value_by_stage}")
    print(f"  pasture_location_bonus   = {cfg.pasture_location_bonus}  "
          f"(SEMANTIC CHANGED: now c≥3 only)")
    print()

    # Write the ported JSON, mirroring tune_heuristic.py's output shape so
    # downstream tools can load it.
    ported = dict(src)
    ported["best_config"] = new_bc
    ported["label"] = "iter1_ported_to_refactor"
    ported["candidate_arch"] = "v3"
    with open(DST, "w") as f:
        json.dump(ported, f, indent=2)
    print(f"Wrote: {DST.name}")
    print()

    # Run a quick match vs V1+T2 (same setup as the V3 history sweep).
    N = 40
    print(f"Match: ported_v3 vs V1+T2, {N} games, heuristic-only")
    print(f"  P0 = V1+T2  vs  P1 = ported_v3")
    print(f"  margin (V1-V3): positive = V1 wins, negative = V3 wins")

    def make_v1(seed: int):
        return HubrisHeuristicV1(
            seed=seed, config=CONFIG_V1_T2, lookahead="turn",
            legal_actions_fn=restricted_legal_actions,
        )

    def make_ported(seed: int):
        return HubrisHeuristicV3(
            seed=seed + 1, config=cfg, lookahead="turn",
            legal_actions_fn=restricted_legal_actions,
        )

    t0 = time.perf_counter()
    r = play_match(make_v1, make_ported, range(N))
    elapsed = time.perf_counter() - t0
    print()
    print(f"FINAL: V1 {r.p0_wins}-{r.draws}-{r.p1_wins} ported_v3   "
          f"avg V1={r.avg_score_p0:+.2f}  ported_v3={r.avg_score_p1:+.2f}  "
          f"margin (V1-V3) = {r.avg_margin:+.2f}   wall {elapsed:.1f}s")
    print()
    print(f"Reference: iter_p2_v3_fields_crops.json (pre-refactor, original) "
          f"scored -11.92 vs V1 (V3 winning by ~12).")
    print(f"If the port preserved strength, the margin here should be similar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
