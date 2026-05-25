"""Tests for the V3-specific major-improvement override and pasture
location bonus introduced when V3 stopped calling V1's `_hubris_major_value`
and `_hubris_pasture_location_bonus`.

What's covered:
- `_hubris_major_value_v3` — per-stage lookup, primary-cooking semantics,
  +1 per extra cooking implement, well no-longer-scales-with-future-food,
  per-stage variance across rounds.
- `_hubris_pasture_location_bonus_v3` — only credits cells with c >= 3
  (vs V1's c >= 2), per-cell granularity.
- Backwards compatibility: legacy major fields still on the dataclass,
  and dict-style construction from an old JSON without the new per-stage
  fields fills them from defaults.

Out of scope: V1's `_hubris_major_value` and `_hubris_pasture_location_bonus`
remain unchanged and aren't re-tested here.
"""

from __future__ import annotations

import dataclasses
import json
import math

from agricola.agents.heuristic import (
    HeuristicConfigV3,
    DEFAULT_CONFIG_V3,
    CONFIG_V3_T1,
    _hubris_major_value_v3,
    _hubris_pasture_location_bonus_v3,
    _PASTURE_BONUS_CELLS_V3,
    evaluate_hubris_v3,
)
from agricola.pasture import Pasture
from agricola.setup import setup
from agricola.state import Farmyard
from tests.factories import with_majors, with_round


# ---------------------------------------------------------------------------
# A small per-stage-distinguishable config makes lookups visually obvious.
# Each cell of each per-stage tuple is unique so a wrong-stage / wrong-major
# bug surfaces as a wrong number rather than a coincidence.
# ---------------------------------------------------------------------------

PROBE_CONFIG = dataclasses.replace(
    DEFAULT_CONFIG_V3,
    fireplace_value_by_stage=(10.0, 11.0, 12.0, 13.0, 14.0, 15.0),
    hearth_value_by_stage=(20.0, 21.0, 22.0, 23.0, 24.0, 25.0),
    well_value_by_stage=(30.0, 31.0, 32.0, 33.0, 34.0, 35.0),
    clay_oven_value_by_stage=(40.0, 41.0, 42.0, 43.0, 44.0, 45.0),
    stone_oven_value_by_stage=(50.0, 51.0, 52.0, 53.0, 54.0, 55.0),
    joinery_value_by_stage=(60.0, 61.0, 62.0, 63.0, 64.0, 65.0),
    pottery_value_by_stage=(70.0, 71.0, 72.0, 73.0, 74.0, 75.0),
    basketmaker_value_by_stage=(80.0, 81.0, 82.0, 83.0, 84.0, 85.0),
)


# ---------------------------------------------------------------------------
# _hubris_major_value_v3 — cooking implements
# ---------------------------------------------------------------------------

def test_v3_major_no_owners_returns_zero():
    s = setup(seed=0)
    assert _hubris_major_value_v3(s, 0, PROBE_CONFIG) == 0.0


def test_v3_major_hearth_only_uses_per_stage_hearth_value():
    s = with_majors(setup(seed=0), owner_by_idx={2: 0})
    # Fresh setup → round 1 → stage 1 → idx 0 → hearth_value_by_stage[0] = 20.0
    assert _hubris_major_value_v3(s, 0, PROBE_CONFIG) == 20.0


def test_v3_major_fireplace_only_uses_per_stage_fireplace_value():
    s = with_majors(setup(seed=0), owner_by_idx={0: 0})
    assert _hubris_major_value_v3(s, 0, PROBE_CONFIG) == 10.0


def test_v3_major_hearth_plus_fireplace_is_hearth_plus_one():
    """Hearth wins as primary; the fireplace counts as +1 extra (flat)."""
    s = with_majors(setup(seed=0), owner_by_idx={0: 0, 2: 0})
    # Hearth primary = 20.0, +1 extra cooking = 21.0 total
    assert _hubris_major_value_v3(s, 0, PROBE_CONFIG) == 21.0


def test_v3_major_two_fireplaces_is_fireplace_plus_one():
    """Both fireplaces owned: primary fireplace + flat +1 extra."""
    s = with_majors(setup(seed=0), owner_by_idx={0: 0, 1: 0})
    assert _hubris_major_value_v3(s, 0, PROBE_CONFIG) == 11.0


def test_v3_major_three_cookings_is_primary_plus_two():
    """Hearth + 2 fireplaces: hearth primary + 2 extras."""
    s = with_majors(setup(seed=0), owner_by_idx={0: 0, 1: 0, 2: 0})
    assert _hubris_major_value_v3(s, 0, PROBE_CONFIG) == 22.0


def test_v3_major_two_hearths_is_hearth_plus_one():
    """Owning both Cooking Hearths (rare but legal): primary + 1 extra."""
    s = with_majors(setup(seed=0), owner_by_idx={2: 0, 3: 0})
    assert _hubris_major_value_v3(s, 0, PROBE_CONFIG) == 21.0


def test_v3_major_opponent_cookings_dont_count():
    """A cooking implement owned by player 1 does NOT count for player 0."""
    s = with_majors(setup(seed=0), owner_by_idx={0: 1, 2: 0})
    # P0 has just the hearth; the fireplace belongs to P1
    assert _hubris_major_value_v3(s, 0, PROBE_CONFIG) == 20.0
    # P1 has just the fireplace
    assert _hubris_major_value_v3(s, 1, PROBE_CONFIG) == 10.0


# ---------------------------------------------------------------------------
# _hubris_major_value_v3 — well and other singletons
# ---------------------------------------------------------------------------

def test_v3_major_well_uses_per_stage_value():
    s = with_majors(setup(seed=0), owner_by_idx={4: 0})
    assert _hubris_major_value_v3(s, 0, PROBE_CONFIG) == 30.0


def test_v3_major_well_does_not_scale_with_future_food():
    """V3 drops `well_food_per_future`. Well's value is constant w.r.t. the
    player's future_resources, only varying by stage."""
    s0 = with_majors(setup(seed=0), owner_by_idx={4: 0})
    p = s0.players[0]
    # Force future_resources to all-zero (no food deposits scheduled). In a
    # fresh post-setup state Well isn't owned, so future_resources has no
    # well-related food anyway — but we make the no-food case explicit.
    new_player_no_food = dataclasses.replace(
        p, future_resources=tuple(
            dataclasses.replace(fr, food=0) for fr in p.future_resources
        ),
    )
    no_food = dataclasses.replace(
        s0,
        players=(new_player_no_food, s0.players[1]),
    )
    # And a state with 5 food rounds scheduled.
    from agricola.resources import Resources
    new_player_full_food = dataclasses.replace(
        p, future_resources=tuple(Resources(food=1) for _ in p.future_resources),
    )
    full_food = dataclasses.replace(
        s0,
        players=(new_player_full_food, s0.players[1]),
    )
    # V3: identical contribution regardless of future-food schedule.
    assert _hubris_major_value_v3(no_food, 0, PROBE_CONFIG) == \
        _hubris_major_value_v3(full_food, 0, PROBE_CONFIG)


def test_v3_major_all_singleton_majors_sum_correctly():
    """Player owns one of every singleton major (well, both ovens, all 3
    crafts) — total should be the sum of per-stage values at stage 1."""
    s = with_majors(setup(seed=0), owner_by_idx={4: 0, 5: 0, 6: 0, 7: 0, 8: 0, 9: 0})
    # stage 1 idx 0: 30 + 40 + 50 + 60 + 70 + 80 = 330
    assert _hubris_major_value_v3(s, 0, PROBE_CONFIG) == 330.0


# ---------------------------------------------------------------------------
# Per-stage variance: same ownership in a different round yields different value
# ---------------------------------------------------------------------------

def test_v3_major_stage_variance_across_rounds():
    """A pottery owner produces pottery_value_by_stage[stage] each round.
    Walk through every stage boundary and check the lookup."""
    base = with_majors(setup(seed=0), owner_by_idx={8: 0})
    # Stage mapping per _stage_of_round: 1-4:s1, 5-7:s2, 8-9:s3, 10-11:s4, 12-13:s5, 14:s6
    expected = [
        (1, 70.0), (4, 70.0),         # stage 1
        (5, 71.0), (7, 71.0),         # stage 2
        (8, 72.0), (9, 72.0),         # stage 3
        (10, 73.0), (11, 73.0),       # stage 4
        (12, 74.0), (13, 74.0),       # stage 5
        (14, 75.0),                   # stage 6
    ]
    for round_n, want in expected:
        s = with_round(base, round_n)
        got = _hubris_major_value_v3(s, 0, PROBE_CONFIG)
        assert got == want, f"round {round_n}: got {got}, want {want}"


# ---------------------------------------------------------------------------
# _hubris_pasture_location_bonus_v3
# ---------------------------------------------------------------------------

def test_v3_pasture_bonus_cell_set_is_c_geq_3():
    """The V3 bonus cells are exactly the rightmost 6 cells (c in {3, 4})."""
    expected = {(r, c) for r in range(3) for c in (3, 4)}
    assert set(_PASTURE_BONUS_CELLS_V3) == expected
    # And not the c=2 cells, which V1 included.
    assert (0, 2) not in _PASTURE_BONUS_CELLS_V3
    assert (1, 2) not in _PASTURE_BONUS_CELLS_V3


def test_v3_pasture_bonus_excludes_c_equals_2_pasture():
    """A pasture occupying only c=2 cells now contributes 0 (V1 would have
    credited it)."""
    s = setup(seed=0)
    p = s.players[0]
    past = Pasture(cells=frozenset({(0, 2), (1, 2), (2, 2)}), num_stables=0, capacity=6)
    new_farm = dataclasses.replace(p.farmyard, pastures=(past,))
    new_p = dataclasses.replace(p, farmyard=new_farm)
    s2 = dataclasses.replace(s, players=(new_p, s.players[1]))
    cfg = dataclasses.replace(DEFAULT_CONFIG_V3, pasture_location_bonus=1.0)
    assert _hubris_pasture_location_bonus_v3(new_p, cfg) == 0.0


def test_v3_pasture_bonus_credits_only_c_geq_3_cells():
    """A pasture spanning c=2,3,4 in row 0: only 2 of 3 cells contribute."""
    p = setup(seed=0).players[0]
    past = Pasture(cells=frozenset({(0, 2), (0, 3), (0, 4)}), num_stables=0, capacity=6)
    new_farm = dataclasses.replace(p.farmyard, pastures=(past,))
    new_p = dataclasses.replace(p, farmyard=new_farm)
    cfg = dataclasses.replace(DEFAULT_CONFIG_V3, pasture_location_bonus=1.0)
    # Cells in V3 bonus set: (0,3) and (0,4) only.
    assert _hubris_pasture_location_bonus_v3(new_p, cfg) == 2.0


def test_v3_pasture_bonus_zero_when_pasture_bonus_param_is_zero():
    """Sanity: the per-cell bonus scalar zeros out the contribution."""
    p = setup(seed=0).players[0]
    past = Pasture(cells=frozenset({(0, 3), (0, 4)}), num_stables=0, capacity=4)
    new_farm = dataclasses.replace(p.farmyard, pastures=(past,))
    new_p = dataclasses.replace(p, farmyard=new_farm)
    cfg = dataclasses.replace(DEFAULT_CONFIG_V3, pasture_location_bonus=0.0)
    assert _hubris_pasture_location_bonus_v3(new_p, cfg) == 0.0


# ---------------------------------------------------------------------------
# Backwards compat: legacy fields still present + JSON load round-trip
# ---------------------------------------------------------------------------

def test_v3_legacy_major_fields_still_on_dataclass():
    """The pre-refactor field names are still attributes of the dataclass
    (unused, but kept so old JSONs construct cleanly)."""
    legacy = (
        "fireplace_value", "fireplace_value_mid", "fireplace_value_late",
        "hearth_value", "hearth_value_mid", "hearth_value_late",
        "cooking_secondary_vp", "well_value", "well_food_per_future",
        "clay_oven_value", "stone_oven_value",
        "joinery_value", "pottery_value", "basketmaker_value",
    )
    for name in legacy:
        assert hasattr(DEFAULT_CONFIG_V3, name), f"missing legacy field: {name}"


def test_v3_default_config_has_per_stage_arrays():
    """Sanity: every new per-stage array exists with length 6 on the defaults."""
    per_stage = (
        "fireplace_value_by_stage", "hearth_value_by_stage", "well_value_by_stage",
        "clay_oven_value_by_stage", "stone_oven_value_by_stage",
        "joinery_value_by_stage", "pottery_value_by_stage", "basketmaker_value_by_stage",
    )
    for name in per_stage:
        v = getattr(DEFAULT_CONFIG_V3, name)
        assert len(v) == 6, f"{name} has length {len(v)}, expected 6"


def test_v3_load_iter2_best_json_fills_defaults_for_new_fields():
    """Backwards-compat: a JSON written before the per-stage major fields
    existed must still load via `HeuristicConfigV3(**cfg_dict)`, filling
    the new fields from dataclass defaults.

    Note: `tuned_configs/v3_best.json` itself may now contain the new
    fields (every subsequent tuning run includes them). To keep the test
    grounded in the OLD shape it was written to validate, we synthesize
    that shape by stripping the new fields from v3_best.json before
    loading."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "tuned_configs" / "v3_best.json"
    if not path.exists():
        # v3_best.json is auto-maintained but might not exist in a fresh
        # checkout — skip rather than fail.
        import pytest
        pytest.skip(f"{path} does not exist; cannot run backwards-compat test")
    cfg_dict = json.loads(path.read_text())["best_config"]
    # Strip every per-stage major field to simulate an old-format JSON.
    new_field_names = (
        "fireplace_value_by_stage", "hearth_value_by_stage",
        "well_value_by_stage", "clay_oven_value_by_stage",
        "stone_oven_value_by_stage", "joinery_value_by_stage",
        "pottery_value_by_stage", "basketmaker_value_by_stage",
    )
    for name in new_field_names:
        cfg_dict.pop(name, None)
    assert "fireplace_value_by_stage" not in cfg_dict
    assert "well_value_by_stage" not in cfg_dict
    # Construct: new fields fill from defaults.
    cfg = HeuristicConfigV3(**cfg_dict)
    assert cfg.fireplace_value_by_stage == DEFAULT_CONFIG_V3.fireplace_value_by_stage
    assert cfg.well_value_by_stage == DEFAULT_CONFIG_V3.well_value_by_stage


def test_v3_evaluator_runs_with_iter2_best_json():
    """End-to-end: load the iter2-final config, eval on a fresh setup,
    confirm finite float (the agent runs)."""
    from pathlib import Path
    repo_root = Path(__file__).resolve().parents[1]
    path = repo_root / "tuned_configs" / "v3_best.json"
    if not path.exists():
        import pytest
        pytest.skip(f"{path} does not exist; cannot run end-to-end test")
    cfg = HeuristicConfigV3(**json.loads(path.read_text())["best_config"])
    s = setup(seed=42)
    v0 = evaluate_hubris_v3(s, 0, cfg)
    v1 = evaluate_hubris_v3(s, 1, cfg)
    assert math.isfinite(v0)
    assert math.isfinite(v1)
