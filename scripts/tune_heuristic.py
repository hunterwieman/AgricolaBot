"""Self-play tuning of HubrisHeuristic V1 config coefficients via CMA-ES.

Tunes a subset of `HeuristicConfig`'s scalar fields against
`HubrisHeuristicV1` with the default config as the baseline opponent.
Fitness = mean(candidate_score - baseline_score) over a fixed seed set.
Higher (more positive) margin = better candidate.

Initial sanity-check parameter set (10 floats): family_per_round[3] +
starting_player_bonus + crop_field_pair_{early,mid,late} +
wood_{first5_no_room, per_fence_owed, secondary}. Edit `TUNABLE` to
expand.

Usage:
    # Recommended (parallel + asserts stripped — ~12-15x faster):
    python -O scripts/tune_heuristic.py                    # uses all cores
    python -O scripts/tune_heuristic.py --jobs 4           # cap parallelism
    python    scripts/tune_heuristic.py --jobs 1           # debug / sequential

    python -O scripts/tune_heuristic.py --n-seeds 50 --max-gens 20
    python -O scripts/tune_heuristic.py --output tuned_configs/run1.json
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from dataclasses import asdict, replace
from multiprocessing import Pool
from pathlib import Path
from typing import Any

# Make `agricola` and sibling `scripts/` modules importable when run directly.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cma
import numpy as np

from agricola.agents import (
    CONFIG_V1_T2,
    CONFIG_V3_T1,
    DEFAULT_CONFIG_V3,
    HubrisHeuristicV1,
    HubrisHeuristicV3,
    restricted_legal_actions,
)
from agricola.legality import legal_actions as _unrestricted_legal_actions
from agricola.agents.heuristic import (
    DEFAULT_CONFIG,
    HeuristicConfig,
    HeuristicConfigV3,
)

from play_match import play_match  # noqa: E402  (sibling module via sys.path)


# Named configs. Each maps to (config_obj, architecture_label).
# Used for both --from (warm-start base, must match --arch) and --baseline
# (opponent agent, independent of --arch).
BASE_CONFIGS: dict[str, tuple] = {
    "default":    (DEFAULT_CONFIG, "v1"),
    "t2":         (CONFIG_V1_T2, "v1"),
    "default_v3": (DEFAULT_CONFIG_V3, "v3"),
    "v3_t1":      (CONFIG_V3_T1, "v3"),
}


def _make_agent(arch: str, cfg, seed: int, *, restricted: bool):
    """Construct an agent of the given architecture with the given config.

    When `restricted=True`, the agent is constructed with
    `legal_actions_fn=restricted_legal_actions` so every legality
    consultation (top-level pick, singleton-skip, rollout) sees the
    action-pruned set defined by `agricola.agents.restricted`.
    """
    extra = {"legal_actions_fn": restricted_legal_actions} if restricted else {}
    # Read temperature off the config if present (V3 configs carry it as
    # an opt-in field; default 0.0 = argmax). V1 configs don't have it.
    temp = float(getattr(cfg, "temperature", 0.0))
    if arch == "v1":
        return HubrisHeuristicV1(config=cfg, seed=seed,
                                  temperature=temp, lookahead="turn", **extra)
    if arch == "v3":
        return HubrisHeuristicV3(config=cfg, seed=seed,
                                  temperature=temp, lookahead="turn", **extra)
    raise ValueError(f"Unknown arch {arch!r}")


def _resolve_config(spec: str) -> tuple:
    """Resolve a --from / --baseline spec into (config_obj, arch).

    `spec` is either:
      - A name from BASE_CONFIGS (e.g. 'default', 't2', 'default_v3'), OR
      - A path to a JSON file produced by a previous tuning run; the
        'best_config' field is loaded into the appropriate dataclass
        (HeuristicConfig if 'candidate_arch' == 'v1', else HeuristicConfigV3).

    The JSON-path form lets the warm-start base reflect the latest
    cross-category tuning progress when iterating between categories.
    """
    if spec in BASE_CONFIGS:
        return BASE_CONFIGS[spec]

    path = Path(spec)
    if not path.is_file():
        raise SystemExit(
            f"Config spec {spec!r} is not a known name "
            f"({sorted(BASE_CONFIGS)}) and not a file path."
        )

    with open(path) as f:
        data = json.load(f)
    cfg_dict = data.get("best_config")
    if cfg_dict is None:
        raise SystemExit(f"{path} has no 'best_config' field.")
    arch = data.get("candidate_arch", "v1")  # legacy JSONs default to v1
    if arch == "v1":
        return HeuristicConfig(**cfg_dict), "v1"
    if arch == "v3":
        return HeuristicConfigV3(**cfg_dict), "v3"
    raise SystemExit(f"Unknown candidate_arch {arch!r} in {path}.")


class _Tee:
    """Mirror writes across multiple streams (stdout + log file).

    Used to send all print() output to both the terminal and the
    timestamped .log companion file. Set up early in main(); restored on
    exit by the try/finally."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, s: str) -> int:
        for stream in self.streams:
            stream.write(s)
        return len(s)

    def flush(self) -> None:
        for stream in self.streams:
            stream.flush()


# ---------------------------------------------------------------------------
# TUNABLE specs
# ---------------------------------------------------------------------------
#
# Each TUNABLE entry: (name, default, lower, upper, config_path).
# config_path = ("field_name",) for a scalar, ("field_name", idx) for
# tuple-valued, or ("field_name", outer, inner) for tuple-of-tuples.
#
# Each named CATEGORY in CATEGORIES is a (tunable_list, arch) pair.
# `--category` selects which one to run; `--arch` is enforced to match.


# --- V1 add-only (used in round 3; kept for reproducibility / V1 follow-ups) ---
TUNABLE_V1_ADDONLY: list[tuple[str, float, float, float, tuple]] = [
    ("renovation_bonus_per_step_early", 0.75, 0.0, 3.0, ("renovation_bonus_per_step_early",)),
    ("renovation_bonus_per_step_late",  1.5,  0.0, 4.0, ("renovation_bonus_per_step_late",)),
    ("field_center_bonus",    0.10, -0.20, 1.00, ("field_center_bonus",)),
    ("pasture_location_bonus", 0.05, -0.20, 0.50, ("pasture_location_bonus",)),
    ("hubris_unfenced_stable_value_early", 0.40, -0.50, 2.00,
     ("hubris_unfenced_stable_value_early",)),
    ("well_value",            4.0, 0.0, 10.0, ("well_value",)),
    ("well_food_per_future",  0.4, 0.0,  2.0, ("well_food_per_future",)),
    ("clay_oven_value",       2.0, 0.0,  6.0, ("clay_oven_value",)),
    ("stone_oven_value",      3.0, 0.0,  8.0, ("stone_oven_value",)),
    ("joinery_value",         2.0, 0.0,  6.0, ("joinery_value",)),
    ("pottery_value",         2.0, 0.0,  6.0, ("pottery_value",)),
    ("basketmaker_value",     2.0, 0.0,  6.0, ("basketmaker_value",)),
]


# --- V3 RESOURCES (63 params) ---
# Tunes wood/clay/reed/stone vectors + scalars + per-stage weights.
# Other V3 categories (fields/crops, pastures/animals, food) frozen at
# DEFAULT_CONFIG_V3 via the warm-start base.
TUNABLE_V3_RESOURCES: list[tuple[str, float, float, float, tuple]] = [
    # Wood: 15 fence_vector + 5 pre_3rd_room + 1 generic + 6 stage = 27
    *[(f"wood_fence_{i}", v, 0.0, 3.0, ("wood_fence_vector", i))
      for i, v in enumerate([0.7]*10 + [0.5]*5)],
    *[(f"wood_pre_3rd_room_{i}", 0.8, 0.0, 3.0, ("wood_pre_3rd_room_vector", i))
      for i in range(5)],
    ("wood_generic_value", 0.1, 0.0, 1.5, ("wood_generic_value",)),
    *[(f"wood_weight_stage{i+1}", v, 0.0, 3.0, ("wood_weight_by_stage", i))
      for i, v in enumerate([1.5, 1.0, 1.0, 1.0, 0.9, 0.2])],

    # Reed: 6 room + 2 renovation + 1 generic + 6 stage = 15
    *[(f"reed_room_{i}", v, 0.0, 8.0, ("reed_room_vector", i))
      for i, v in enumerate([5.0, 1.5, 0.3, 0.3, 0.0, 0.0])],
    *[(f"reed_renovation_{i}", v, 0.0, 3.0, ("reed_renovation_vector", i))
      for i, v in enumerate([0.5, 0.3])],
    ("reed_generic_value", 0.2, 0.0, 1.5, ("reed_generic_value",)),
    *[(f"reed_weight_stage{i+1}", v, 0.0, 3.0, ("reed_weight_by_stage", i))
      for i, v in enumerate([1.5, 1.0, 1.0, 1.0, 0.9, 0.2])],

    # Clay: 5 cookware + 1 renovation_per_room + 1 generic + 6 stage = 13
    *[(f"clay_cookware_{i}", 0.8, 0.0, 3.0, ("clay_cookware_vector", i))
      for i in range(5)],
    ("clay_renovation_per_room", 0.8, 0.0, 3.0, ("clay_renovation_per_room",)),
    ("clay_generic_value", 0.1, 0.0, 1.5, ("clay_generic_value",)),
    *[(f"clay_weight_stage{i+1}", v, 0.0, 3.0, ("clay_weight_by_stage", i))
      for i, v in enumerate([1.5, 1.0, 1.0, 1.0, 0.9, 0.2])],

    # Stone: 1 renovation_per_room + 1 generic + 6 stage = 8
    ("stone_renovation_per_room", 0.5, 0.0, 3.0, ("stone_renovation_per_room",)),
    ("stone_generic_value", 0.5, 0.0, 3.0, ("stone_generic_value",)),
    *[(f"stone_weight_stage{i+1}", v, 0.0, 3.0, ("stone_weight_by_stage", i))
      for i, v in enumerate([1.5, 1.0, 1.0, 1.0, 1.0, 0.7])],
]


# --- V3 FIELDS & CROPS (60 params) ---
TUNABLE_V3_FIELDS_CROPS: list[tuple[str, float, float, float, tuple]] = [
    # Fields (7+6 = 13)
    *[(f"plowed_field_value_{i}", v, -3.0, 8.0, ("plowed_field_value", i))
      for i, v in enumerate([-1.0, -1.0, 1.0, 2.0, 3.0, 4.0, 4.0])],
    *[(f"field_blend_alpha_stage{i+1}", 0.5, 0.0, 1.0, ("field_blend_alpha_by_stage", i))
      for i in range(6)],
    # Grain (10+6 = 16)
    *[(f"grain_value_{i}", v, -3.0, 8.0, ("grain_value", i))
      for i, v in enumerate([-1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0, 4.0])],
    *[(f"grain_blend_alpha_stage{i+1}", 0.5, 0.0, 1.0, ("grain_blend_alpha_by_stage", i))
      for i in range(6)],
    # Veg (5+6 = 11)
    *[(f"veg_value_{i}", v, -3.0, 8.0, ("veg_value", i))
      for i, v in enumerate([-1.0, 1.0, 2.0, 3.0, 4.0])],
    *[(f"veg_blend_alpha_stage{i+1}", 0.5, 0.0, 1.0, ("veg_blend_alpha_by_stage", i))
      for i in range(6)],
    # Grain-field pairs (4+6 = 10)
    *[(f"grain_pair_value_{i}", v, 0.0, 5.0, ("grain_pair_value", i))
      for i, v in enumerate([0.0, 0.6, 1.2, 1.8])],
    *[(f"grain_pair_weight_stage{i+1}", v, 0.0, 3.0, ("grain_pair_weight_by_stage", i))
      for i, v in enumerate([1.0, 1.0, 0.8, 0.6, 0.4, 0.0])],
    # Veg-field pairs (4+6 = 10)
    *[(f"veg_pair_value_{i}", v, 0.0, 5.0, ("veg_pair_value", i))
      for i, v in enumerate([0.0, 0.6, 1.2, 1.8])],
    *[(f"veg_pair_weight_stage{i+1}", v, 0.0, 3.0, ("veg_pair_weight_by_stage", i))
      for i, v in enumerate([1.0, 1.0, 0.8, 0.6, 0.4, 0.0])],
]


# --- V3 PASTURES & ANIMALS (101 params) ---
TUNABLE_V3_PASTURES_ANIMALS: list[tuple[str, float, float, float, tuple]] = [
    # Pastures (5+5+6 = 16)
    *[(f"pasture_value_all_{i}", v, -3.0, 8.0, ("pasture_value_all", i))
      for i, v in enumerate([-1.0, 1.0, 2.0, 3.0, 4.0])],
    *[(f"pasture_value_large_{i}", 0.0, -1.0, 5.0, ("pasture_value_large", i))
      for i in range(5)],
    *[(f"pasture_blend_alpha_stage{i+1}", 0.5, 0.0, 1.0, ("pasture_blend_alpha_by_stage", i))
      for i in range(6)],
    # Sheep (9+6 = 15)
    *[(f"sheep_value_{i}", v, -3.0, 8.0, ("sheep_value", i))
      for i, v in enumerate([-1.0, 1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0])],
    *[(f"sheep_blend_alpha_stage{i+1}", 0.5, 0.0, 1.0, ("sheep_blend_alpha_by_stage", i))
      for i in range(6)],
    # Boar (8+6 = 14)
    *[(f"boar_value_{i}", v, -3.0, 8.0, ("boar_value", i))
      for i, v in enumerate([-1.0, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0])],
    *[(f"boar_blend_alpha_stage{i+1}", 0.5, 0.0, 1.0, ("boar_blend_alpha_by_stage", i))
      for i in range(6)],
    # Cattle (7+6 = 13)
    *[(f"cattle_value_{i}", v, -3.0, 8.0, ("cattle_value", i))
      for i, v in enumerate([-1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 4.0])],
    *[(f"cattle_blend_alpha_stage{i+1}", 0.5, 0.0, 1.0, ("cattle_blend_alpha_by_stage", i))
      for i in range(6)],
    # Fenced stables (5+6 = 11)
    *[(f"fenced_stable_value_{i}", v, -3.0, 8.0, ("fenced_stable_value", i))
      for i, v in enumerate([0.0, 1.0, 2.0, 3.0, 4.0])],
    *[(f"fenced_stable_blend_alpha_stage{i+1}", 0.5, 0.0, 1.0,
       ("fenced_stable_blend_alpha_by_stage", i))
      for i in range(6)],
    # Breeding pairs — cattle (1+6 = 7)
    ("cattle_breeding_pair_value", 1.0, 0.0, 5.0, ("cattle_breeding_pair_value",)),
    *[(f"cattle_breed_weight_stage{i+1}", v, 0.0, 3.0, ("cattle_breeding_pair_weight_by_stage", i))
      for i, v in enumerate([1.0, 1.0, 1.0, 0.5, 0.0, 0.0])],
    # Breeding pairs — boar (1+6 = 7)
    ("boar_breeding_pair_value", 1.0, 0.0, 5.0, ("boar_breeding_pair_value",)),
    *[(f"boar_breed_weight_stage{i+1}", v, 0.0, 3.0, ("boar_breeding_pair_weight_by_stage", i))
      for i, v in enumerate([1.0, 1.0, 1.0, 0.5, 0.0, 0.0])],
    # Breeding pairs — sheep (1+6 = 7)
    ("sheep_breeding_pair_value", 1.0, 0.0, 5.0, ("sheep_breeding_pair_value",)),
    *[(f"sheep_breed_weight_stage{i+1}", v, 0.0, 3.0, ("sheep_breeding_pair_weight_by_stage", i))
      for i, v in enumerate([1.0, 1.0, 1.0, 0.5, 0.0, 0.0])],
    # Unfenced stables (5+6 = 11)
    *[(f"unfenced_stable_value_{i}", v, 0.0, 3.0, ("unfenced_stable_value", i))
      for i, v in enumerate([0.0, 0.4, 0.8, 1.2, 1.6])],
    *[(f"unfenced_stable_weight_stage{i+1}", v, 0.0, 3.0, ("unfenced_stable_weight_by_stage", i))
      for i, v in enumerate([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])],
]


# --- V3 MAJORS PER STAGE (48 params) ---
# Tunes the 8 per-stage major-improvement value arrays added in the
# post-iter2 refactor (see V3_DESIGN.md §3 D, V3_TRAINING_PIPELINE.md §8.1).
# 8 majors × 6 stages each.
#
# Defaults: cooking values (fireplace/hearth) derived from CONFIG_V1_T2's
# 3-tier scalars expanded to 6 stages (stages 1-4 = "full", stage 5 = "_mid",
# stage 6 = "_late"). Other majors flat at V1's hand-picked single-scalar
# defaults across all 6 stages.
#
# Bounds aligned with the v1_addonly precedent: cooking 0-10, well 0-10,
# clay_oven 0-6, stone_oven 0-8, crafts (joinery/pottery/basketmaker) 0-6.
# Cooking gets a more generous upper bound since hearth_value_late in T2
# is already ~5.25.
_FP_DEFAULTS = (4.80973022568891, 4.80973022568891, 4.80973022568891,
                4.80973022568891, 2.471273053448844, 0.1474925121229842)
_HE_DEFAULTS = (5.246727936850129, 5.246727936850129, 5.246727936850129,
                5.246727936850129, 2.718190472453053, 0.8213097609387353)

TUNABLE_V3_MAJORS_PER_STAGE: list[tuple[str, float, float, float, tuple]] = [
    # Fireplace per-stage (6)
    *[(f"fireplace_value_stage{i+1}", v, 0.0, 10.0, ("fireplace_value_by_stage", i))
      for i, v in enumerate(_FP_DEFAULTS)],
    # Hearth per-stage (6)
    *[(f"hearth_value_stage{i+1}", v, 0.0, 10.0, ("hearth_value_by_stage", i))
      for i, v in enumerate(_HE_DEFAULTS)],
    # Well per-stage (6) — defaults flat at 4.0 (V1 hand-picked); drops the
    # old well_food_per_future term which is no longer read.
    *[(f"well_value_stage{i+1}", 4.0, 0.0, 10.0, ("well_value_by_stage", i))
      for i in range(6)],
    # Clay Oven per-stage (6) — defaults flat at 2.0 (V1 hand-picked)
    *[(f"clay_oven_value_stage{i+1}", 2.0, 0.0, 6.0, ("clay_oven_value_by_stage", i))
      for i in range(6)],
    # Stone Oven per-stage (6) — defaults flat at 3.0 (V1 hand-picked)
    *[(f"stone_oven_value_stage{i+1}", 3.0, 0.0, 8.0, ("stone_oven_value_by_stage", i))
      for i in range(6)],
    # Joinery per-stage (6)
    *[(f"joinery_value_stage{i+1}", 2.0, 0.0, 6.0, ("joinery_value_by_stage", i))
      for i in range(6)],
    # Pottery per-stage (6)
    *[(f"pottery_value_stage{i+1}", 2.0, 0.0, 6.0, ("pottery_value_by_stage", i))
      for i in range(6)],
    # Basketmaker per-stage (6)
    *[(f"basketmaker_value_stage{i+1}", 2.0, 0.0, 6.0, ("basketmaker_value_by_stage", i))
      for i in range(6)],
]


# --- V3 ALPHAS + CARRY-OVERS (22 params) ---
# Joint TUNABLE over three groups that are otherwise uncovered by any
# V3 category-specific TUNABLE (see V3_TRAINING_PIPELINE.md §8.1):
#
#   B1 (V3-specific stage curves, hand-picked, never tuned)
#     - score_joint_alpha_by_stage (6): modulator on (clay_rooms +
#       stone_rooms + people + bonus_points) score leaves.
#     - unused_spaces_alpha_by_stage (6): scales the unused-spaces
#       penalty (parameterized side fixed at 0).
#
#   B3 (V1_T2-tuned carry-overs still actively read in V3, never re-tuned
#       in V3 context)
#     - family_per_round (3): per-future-round value for 3rd/4th/5th
#       family members.
#     - empty_room_rate_pre_basic_wish + _post_basic_wish (2): anticipated
#       value of empty rooms for future people.
#     - starting_player_bonus (1): flat bonus when holding SP token.
#
#   B4 (V1 carry-overs never tuned at all — V1 round 3 attempted some;
#       none promoted)
#     - field_center_bonus (1): per-cell bonus for center 4 field cells.
#     - pasture_location_bonus (1): per-cell bonus for c >= 3 pasture
#       cells (V3-c≥3 helper; V1 used c≥2).
#     - renovation_bonus_per_step_early + _late (2): per-renovation-step
#       bonus, currently 0.0 (backwards-compat).
#
# Bounds: alphas constrained to plausible modulator ranges (0..1.5 for
# joint, 0..1 for unused-spaces per its design). Carry-over scalars use
# the v1_addonly precedent where applicable, generous bounds otherwise.
TUNABLE_V3_ALPHAS_AND_CARRYOVERS: list[tuple[str, float, float, float, tuple]] = [
    # B1: V3-specific stage curves (6+6 = 12)
    *[(f"score_joint_alpha_stage{i+1}", v, 0.0, 1.5, ("score_joint_alpha_by_stage", i))
      for i, v in enumerate([0.5, 0.6, 0.7, 0.8, 0.9, 1.0])],
    *[(f"unused_spaces_alpha_stage{i+1}", v, 0.0, 1.0, ("unused_spaces_alpha_by_stage", i))
      for i, v in enumerate([1.0, 0.7, 0.5, 0.3, 0.1, 0.0])],

    # B3: V1_T2-tuned carry-overs (3+1+1+1 = 6)
    *[(f"family_per_round_{i}", v, 0.0, 6.0, ("family_per_round", i))
      for i, v in enumerate([3.292323267102328, 2.2556860160847774, 2.004865826860955])],
    ("empty_room_rate_pre_basic_wish",  2.616157917681491, 0.0, 6.0,
        ("empty_room_rate_pre_basic_wish",)),
    ("empty_room_rate_post_basic_wish", 2.922029893978679, 0.0, 6.0,
        ("empty_room_rate_post_basic_wish",)),
    ("starting_player_bonus",           1.2280813469772174, 0.0, 4.0,
        ("starting_player_bonus",)),

    # B4: V1 untuned carry-overs (1+1+1+1 = 4)
    ("field_center_bonus",              0.10, -0.20, 1.00, ("field_center_bonus",)),
    ("pasture_location_bonus",          0.05, -0.20, 0.50, ("pasture_location_bonus",)),
    ("renovation_bonus_per_step_early", 0.0,   0.0,  3.0, ("renovation_bonus_per_step_early",)),
    ("renovation_bonus_per_step_late",  0.0,   0.0,  4.0, ("renovation_bonus_per_step_late",)),
]


# --- V3 FOOD (18 params) ---
# hubris_food_by_stage[stage][0=at_need, 1=excess] + hubris_begging_by_moves.
# Defaults are CONFIG_V1_T2's tuned values (carried over into DEFAULT_CONFIG_V3).
TUNABLE_V3_FOOD: list[tuple[str, float, float, float, tuple]] = [
    # Food per stage (6 stages × 2 rates = 12)
    *[(f"food_at_need_stage{s+1}", v, 0.0, 3.0, ("hubris_food_by_stage", s, 0))
      for s, v in enumerate([1.168, 1.213, 0.794, 0.126, 0.874, 0.302])],
    *[(f"food_excess_stage{s+1}", v, 0.0, 2.0, ("hubris_food_by_stage", s, 1))
      for s, v in enumerate([1.057, 0.452, 0.316, 0.295, 0.587, 0.000])],
    # Begging penalty by moves remaining (6)
    *[(f"begging_moves_{i}", v, -5.0, 0.0, ("hubris_begging_by_moves", i))
      for i, v in enumerate([-2.785, -2.362, -1.633, -0.931, -0.976, -0.575])],
]


# Category registry. (tunable_list, arch_label).
# All V3 parameters combined into one TUNABLE. ~312 params total.
# Use with `--category v3_all` to tune every V3 field in a single CMA-ES
# call rather than the block-coordinate-descent pattern enforced by
# `run_iterative_v3.py`. Recommended popsize for d=312 is ~30 (≈ 4+3·ln(d)),
# so `--popsize 30 --max-gens 50+` for a serious run. The historical
# motivation for splitting into smaller categories was partly the
# "chained baseline drift" failure mode now addressed by --baselines /
# --regression-baseline; the per-category split is no longer load-bearing.
TUNABLE_V3_ALL: list[tuple[str, float, float, float, tuple]] = (
    TUNABLE_V3_FIELDS_CROPS
    + TUNABLE_V3_FOOD
    + TUNABLE_V3_RESOURCES
    + TUNABLE_V3_PASTURES_ANIMALS
    + TUNABLE_V3_MAJORS_PER_STAGE
    + TUNABLE_V3_ALPHAS_AND_CARRYOVERS
)

CATEGORIES: dict[str, tuple[list, str]] = {
    "v1_addonly":           (TUNABLE_V1_ADDONLY,         "v1"),
    "v3_resources":         (TUNABLE_V3_RESOURCES,       "v3"),
    "v3_fields_crops":      (TUNABLE_V3_FIELDS_CROPS,    "v3"),
    "v3_pastures_animals":  (TUNABLE_V3_PASTURES_ANIMALS,"v3"),
    "v3_food":              (TUNABLE_V3_FOOD,            "v3"),
    "v3_majors_per_stage":  (TUNABLE_V3_MAJORS_PER_STAGE,"v3"),
    "v3_alphas_and_carryovers": (TUNABLE_V3_ALPHAS_AND_CARRYOVERS, "v3"),
    "v3_all":               (TUNABLE_V3_ALL,             "v3"),
}


# Default `TUNABLE` for callers that don't go through the dispatch
# (preserves legacy import-as-list behavior). Defaults to V3 resources.
TUNABLE: list = TUNABLE_V3_RESOURCES


def _x0_from_base(tunable: list, base_config) -> np.ndarray:
    """Extract the warm-start base's current values for each TUNABLE entry's
    path. Returns a numpy array suitable as CMA-ES's x0.

    Path shapes follow `vector_to_config`'s convention:
      ("field",)               → scalar
      ("field", idx)           → tuple-indexed
      ("field", outer, inner)  → nested tuple-of-tuples

    This is the inverse of `vector_to_config`: where vector_to_config
    writes x's values INTO the config at each path, this READS the
    config's values OUT into a vector. So `vector_to_config(_x0_from_base(t, base), base, t) == base` for any base that has values within bounds.
    """
    values: list[float] = []
    for (_name, _default, _lo, _hi, path) in tunable:
        val = getattr(base_config, path[0])
        for idx in path[1:]:
            val = val[idx]
        values.append(float(val))
    return np.array(values, dtype=float)


def vector_to_config(x: np.ndarray, base, tunable: list | None = None):
    """Apply CMA-ES candidate vector to `base` config, returning a new config.

    Path shapes:
      ("field",)               → scalar field
      ("field", idx)           → flat tuple of floats (e.g. family_per_round)
      ("field", outer, inner)  → tuple of tuples (e.g. hubris_food_by_stage)

    Buffer policy: writes accumulate into list-of-lists (or list-of-floats)
    keyed by field name, then are converted back to tuples in a single
    `replace(...)` call at the end.

    `tunable` defaults to the module-level `TUNABLE` (kept for callers
    that bind to the default category). Workers receive their tunable
    via `_WORKER_TUNABLE` (set by `_init_worker`).
    """
    if tunable is None:
        tunable = _WORKER_TUNABLE if _WORKER_TUNABLE is not None else TUNABLE
    overrides: dict[str, Any] = {}
    tuple_buffers: dict[str, list] = {}        # flat tuple[float]
    nested_buffers: dict[str, list[list]] = {}  # nested tuple[tuple[float]]

    for value, (_name, _default, _lo, _hi, path) in zip(x, tunable):
        field = path[0]
        if len(path) == 1:
            overrides[field] = float(value)
        elif len(path) == 2:
            idx = path[1]
            if field not in tuple_buffers:
                tuple_buffers[field] = list(getattr(base, field))
            tuple_buffers[field][idx] = float(value)
        elif len(path) == 3:
            outer, inner = path[1], path[2]
            if field not in nested_buffers:
                nested_buffers[field] = [list(row) for row in getattr(base, field)]
            nested_buffers[field][outer][inner] = float(value)
        else:
            raise ValueError(f"Unsupported path length {len(path)}: {path!r}")

    for field, lst in tuple_buffers.items():
        overrides[field] = tuple(lst)
    for field, lst_of_lst in nested_buffers.items():
        overrides[field] = tuple(tuple(row) for row in lst_of_lst)

    return replace(base, **overrides)


# Worker-side global state. Populated by `_init_worker` in pool workers
# (via Pool's `initializer` argument) and by `main()` directly for the
# sequential / sanity-check path.
_WORKER_SEEDS: list[int] | None = None
_WORKER_BASELINE_CONFIGS: list | None = None  # opponent configs (multi-baseline)
_WORKER_BASELINE_ARCHS: list[str] | None = None  # opponent architectures
_WORKER_BASE_CONFIG = None        # warm-start base for the candidate
_WORKER_BASE_ARCH: str = "v3"     # candidate architecture
_WORKER_TUNABLE: list | None = None  # which TUNABLE list is active
_WORKER_RESTRICTED: bool = False  # whether agents use restricted_legal_actions
_WORKER_FITNESS_KIND: str = "margin"  # "margin" | "sublinear" | "truncated" | "win_rate"
_WORKER_FITNESS_K: float = 0.5  # exponent for sublinear; cap for truncated
_WORKER_CANDIDATE_R1_FOREST: bool = False  # wrap candidate evaluator with r1_force_forest_bonus


def _init_worker(seeds: list[int],
                 baseline_configs: list, baseline_archs: list,
                 base_config, base_arch: str,
                 tunable: list,
                 restricted: bool = False,
                 fitness_kind: str = "margin",
                 fitness_k: float = 0.5,
                 candidate_r1_force_forest: bool = False) -> None:
    """Pool initializer: copy seeds, baselines (opponents), warm-start base,
    architecture labels, the active TUNABLE, and the restricted flag into
    worker globals.

    - `baseline_configs` / `baseline_archs`: parallel lists of opponent
      configs that the candidate plays against. When more than one is
      supplied, the candidate's fitness is the mean margin across all
      baselines (each evaluated on the same seed set). This prevents
      overfitting to a single opponent — the "chained baseline drift"
      failure mode that caused V3 to silently regress against V1+T2
      during iter2.
    - `base_config`: starting point for `vector_to_config` — fields not in
      TUNABLE inherit values from this config (add-only tuning).
    - `restricted`: when True, candidate and baseline agents are built with
      `legal_actions_fn=restricted_legal_actions`, so the tuning runs in
      the action-pruned space.
    """
    global _WORKER_SEEDS, _WORKER_BASELINE_CONFIGS, _WORKER_BASELINE_ARCHS
    global _WORKER_BASE_CONFIG, _WORKER_BASE_ARCH, _WORKER_TUNABLE
    global _WORKER_RESTRICTED, _WORKER_FITNESS_KIND, _WORKER_FITNESS_K
    global _WORKER_CANDIDATE_R1_FOREST
    _WORKER_SEEDS = seeds
    _WORKER_BASELINE_CONFIGS = list(baseline_configs)
    _WORKER_BASELINE_ARCHS = list(baseline_archs)
    _WORKER_BASE_CONFIG = base_config
    _WORKER_BASE_ARCH = base_arch
    _WORKER_TUNABLE = tunable
    _WORKER_RESTRICTED = restricted
    _WORKER_FITNESS_KIND = fitness_kind
    _WORKER_FITNESS_K = fitness_k
    _WORKER_CANDIDATE_R1_FOREST = candidate_r1_force_forest


def _per_game_fitness(per_game, kind: str, k: float) -> float:
    """Aggregate a match's per-game results into a scalar baseline fitness.

    - `margin`:    avg(score_p0 − score_p1)          — original behavior.
    - `sublinear`: avg(sign(m) · |m|^k), k≈0.5       — diminishing returns
                   on blowouts; bounds easy-opponent attractor effects.
    - `truncated`: avg(clip(m, -k, +k)), k≈5         — hard cap; same intent
                   as sublinear, sharper threshold.
    - `win_rate`:  fraction of games won (+0.5 per draw), shifted to
                   [-0.5, +0.5] so it has the same sign as margin.
    """
    import math
    n = len(per_game)
    if kind == "margin":
        return sum(g.score_p0 - g.score_p1 for g in per_game) / n
    if kind == "sublinear":
        total = 0.0
        for g in per_game:
            m = g.score_p0 - g.score_p1
            total += math.copysign(abs(m) ** k, m)
        return total / n
    if kind == "truncated":
        return sum(max(-k, min(k, g.score_p0 - g.score_p1)) for g in per_game) / n
    if kind == "win_rate":
        wins = sum(1 for g in per_game if g.winner == 0)
        draws = sum(1 for g in per_game if g.winner not in (0, 1))
        return (wins + 0.5 * draws) / n - 0.5
    raise ValueError(f"unknown fitness kind {kind!r}")


def _eval_candidate(task) -> float:
    """Top-level fitness function. Returns -mean_aggregate_across_baselines,
    where the per-baseline aggregate is computed per `_WORKER_FITNESS_KIND`.

    Accepts either:
      - bare ndarray x (legacy): uses `_WORKER_SEEDS` (fixed across gens).
      - tuple `(x, seeds)`: uses the supplied seeds. Enables per-gen seed
        rotation without re-initializing the Pool.

    Top-level (not a closure) so `multiprocessing.Pool` can pickle it.

    Negative-margin convention: CMA-ES minimizes; we want to MAXIMIZE
    the candidate's aggregate over the baselines.
    """
    if isinstance(task, tuple):
        x, seeds = task
        seeds = tuple(seeds)  # pickled as part of the task
    else:
        x = task
        assert _WORKER_SEEDS is not None, "worker globals not initialized"
        seeds = _WORKER_SEEDS
    assert _WORKER_BASELINE_CONFIGS, "worker globals not initialized"
    assert _WORKER_BASE_CONFIG is not None, "worker globals not initialized"
    candidate_cfg = vector_to_config(np.asarray(x), base=_WORKER_BASE_CONFIG)
    candidate_arch = _WORKER_BASE_ARCH

    margins: list[float] = []
    for baseline_cfg, baseline_arch in zip(
        _WORKER_BASELINE_CONFIGS, _WORKER_BASELINE_ARCHS,
    ):
        def p0_factory(seed: int, _cfg=candidate_cfg, _arch=candidate_arch):
            agent = _make_agent(_arch, _cfg, seed, restricted=_WORKER_RESTRICTED)
            # Optionally compose the candidate's evaluator with auxiliary
            # bonuses (e.g., force a specific opening move during tuning so
            # CMA-ES learns the corresponding follow-up). Only applies to V3
            # candidates — V1's evaluator has a different signature path.
            if _WORKER_CANDIDATE_R1_FOREST and _arch == "v3":
                from agricola.agents.heuristic import (
                    compose_evaluators, r1_force_forest_bonus,
                )
                agent.evaluator = compose_evaluators(
                    agent.evaluator, r1_force_forest_bonus,
                )
            return agent

        def p1_factory(seed: int, _cfg=baseline_cfg, _arch=baseline_arch):
            return _make_agent(_arch, _cfg, seed + 1, restricted=_WORKER_RESTRICTED)

        result = play_match(p0_factory, p1_factory, seeds)
        margins.append(_per_game_fitness(result.per_game,
                                          _WORKER_FITNESS_KIND,
                                          _WORKER_FITNESS_K))

    return -(sum(margins) / len(margins))


def _eval_against_baseline_task(args):
    """Pool-callable wrapper around `_eval_against_baseline`.

    Tasks are tuples (candidate_cfg, candidate_arch, baseline_cfg,
    baseline_arch, seeds, restricted, candidate_r1_force_forest).
    Returns a MatchResult. Lets the per-baseline diagnostic run in
    parallel across the worker pool instead of sequentially in the
    master process. Each task plays n_diag_seeds games against one
    baseline.

    Backwards-compatible: accepts the old 6-tuple too (defaults
    `candidate_r1_force_forest` to False) so old pickles still work."""
    if len(args) == 7:
        cand_cfg, cand_arch, base_cfg, base_arch, seeds, restricted, r1ff = args
    else:
        cand_cfg, cand_arch, base_cfg, base_arch, seeds, restricted = args
        r1ff = False
    return _eval_against_baseline(
        candidate_cfg=cand_cfg, candidate_arch=cand_arch,
        baseline_cfg=base_cfg, baseline_arch=base_arch,
        seeds=list(seeds), restricted=restricted,
        candidate_r1_force_forest=r1ff,
    )


def _eval_against_baseline(candidate_cfg, candidate_arch: str,
                            baseline_cfg, baseline_arch: str,
                            seeds: list[int], restricted: bool,
                            *,
                            candidate_r1_force_forest: bool = False):
    """Single-baseline match. Returns the full `MatchResult` (avg_margin,
    p0_wins, p1_wins, draws, per_game, ...). Used by the regression-detector
    and per-baseline diagnostic paths — NOT in the fitness aggregate.

    Callers that only need the margin should read `.avg_margin`. Callers
    that want W/L counts read `.p0_wins / .p1_wins / .draws`.

    When `candidate_r1_force_forest=True`, the candidate's evaluator is
    composed with r1_force_forest_bonus — matching how the candidate is
    constructed during fitness eval in `_eval_candidate`. Ensures the
    diagnostic / regression / holdout measurements are TAKEN ON THE SAME
    AGENT CMA-ES IS OPTIMIZING (no train/eval mismatch).
    """
    def p0_factory(seed: int):
        agent = _make_agent(candidate_arch, candidate_cfg, seed,
                             restricted=restricted)
        if candidate_r1_force_forest and candidate_arch == "v3":
            from agricola.agents.heuristic import (
                compose_evaluators, r1_force_forest_bonus,
            )
            agent.evaluator = compose_evaluators(
                agent.evaluator, r1_force_forest_bonus,
            )
        return agent

    def p1_factory(seed: int):
        return _make_agent(baseline_arch, baseline_cfg, seed + 1,
                            restricted=restricted)

    return play_match(p0_factory, p1_factory, seeds)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-seeds", type=int, default=50,
                        help="Games per evaluation (seeds 0..n-1). Default 50.")
    parser.add_argument("--max-gens", type=int, default=10,
                        help="Max CMA-ES generations. Default 10.")
    parser.add_argument("--popsize", type=int, default=12,
                        help="CMA-ES population size. Default 12 (≈ 4 + 3 ln(d), d=10).")
    parser.add_argument("--sigma0", type=float, default=0.3,
                        help="Initial CMA-ES step size. Default 0.3.")
    parser.add_argument("--cma-seed", type=int, default=1,
                        help="CMA-ES internal RNG seed. Default 1.")
    parser.add_argument("--holdout-start", type=int, default=1000,
                        help="First seed of the holdout set for the post-tuning verification "
                             "match. Default 1000 (disjoint from the training seeds 0..n-1).")
    parser.add_argument("--holdout-n", type=int, default=100,
                        help="Number of holdout games for the post-tuning verification match. "
                             "Default 100.")
    parser.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                        help="Number of parallel processes for population evaluation. "
                             f"Default {os.cpu_count() or 1} (all cores). Set to 1 for sequential "
                             "execution (easier debugging).")
    parser.add_argument("--category", choices=tuple(CATEGORIES.keys()),
                        default="v3_resources",
                        help="Which TUNABLE set to optimize. The category implies a "
                             "candidate architecture (v1 or v3); --from must match it.")
    parser.add_argument("--from", dest="from_config", default="default_v3",
                        help="Base config for the candidate (warm-start). Either a "
                             f"named config ({sorted(BASE_CONFIGS)}) or a path to a "
                             "JSON file from a previous tuning run (its 'best_config' is "
                             "loaded). Default 'default_v3'.")
    parser.add_argument("--baseline", default=None,
                        help="DEPRECATED single-opponent flag. Same name-or-path "
                             "semantics as --from. If set, equivalent to "
                             "`--baselines <value>`. Use --baselines for multi-opponent "
                             "fitness.")
    parser.add_argument("--baselines", nargs="+", default=None,
                        help="OPPONENT configs for the fitness function. The candidate "
                             "plays against each, on the same seed set; fitness = mean "
                             "margin across all baselines. Use one entry for the "
                             "classic single-opponent setup, multiple to prevent "
                             "overfitting to one opponent. Names or paths, same as "
                             "--from. Default 't2'.")
    parser.add_argument("--regression-baseline", default="t2",
                        help="Fixed reference opponent used as a REGRESSION DETECTOR. "
                             "Measured per-generation on the session-best candidate "
                             "(NOT in the fitness aggregate). The trajectory is "
                             "recorded in the output JSON as `regression_history` so "
                             "you can see when tuning starts drifting away from a "
                             "known-strong reference. Default 't2' (V1+T2). Set to "
                             "'' to disable.")
    parser.add_argument("--resume", type=Path, default=None,
                        help="Path to a previously-saved CMA-ES state (.cma.pkl). If set, "
                             "CMA-ES picks up exactly where it left off (mean, σ, "
                             "covariance, paths, counters all restored). --max-gens "
                             "becomes the number of ADDITIONAL generations to run from "
                             "the resumed state. The TUNABLE size must match the saved "
                             "state's dimension.")
    parser.add_argument("--output", type=Path, default=None,
                        help="Where to write JSON result. Default tuned_configs/<timestamp>.json. "
                             "A companion .log file with human-readable progress is written next to it.")
    parser.add_argument("--restricted", action=argparse.BooleanOptionalAction, default=True,
                        help="If set (default), both candidate and baseline agents use "
                             "agricola.agents.restricted_legal_actions — the action-pruned set "
                             "(rooms-before-stables ordering, cell priorities, room cap, "
                             "first-pasture-cells, min-begging at harvest feed). Use "
                             "--no-restricted to run tuning in the unrestricted action space "
                             "(matches pre-restricted behavior). The flag is recorded in the "
                             "output JSON.")
    parser.add_argument("--reset-floor-after-promote",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="After a fresh promotion of <arch>_best.json, re-measure the "
                             "new champion's self-match floor on the holdout seeds and "
                             "overwrite the stored holdout.avg_margin with the floor. "
                             "Fixes the chained-baseline auto-update issue: without this, "
                             "the stored margin is the champion's gain over its (now-obsolete) "
                             "predecessor, which is much larger than the meaningful self-match "
                             "floor and blocks future legitimate promotions. Adds ~holdout_n "
                             "games of compute per promoted run. Recommended for sequential "
                             "single-category runs that re-tune against the current champion.")
    parser.add_argument("--no-promote", action="store_true", default=False,
                        help="Skip the <arch>_best.json auto-promotion step entirely. Use for "
                             "exploratory / validation runs where you want the JSON output but "
                             "don't want to risk overwriting the current champion pointer. The "
                             "regression-history JSON is still written and reported.")
    parser.add_argument("--fitness", default="margin",
                        choices=("margin", "sublinear", "truncated", "win_rate"),
                        help="Fitness aggregation per baseline. 'margin' (default) is the "
                             "original avg(p0-p1) per-game; 'sublinear' uses "
                             "sign(m)·|m|^k (caps blowout influence smoothly); 'truncated' "
                             "uses clip(m, -k, +k); 'win_rate' uses fraction-of-wins shifted "
                             "to [-0.5, +0.5]. The aggregate fitness is the mean across "
                             "baselines of this per-baseline aggregate.")
    parser.add_argument("--fitness-k", type=float, default=0.5,
                        help="Exponent for --fitness sublinear (default 0.5), or cap K for "
                             "--fitness truncated (default 5.0 — pass --fitness-k 5 then). "
                             "Ignored for margin and win_rate.")
    parser.add_argument("--rotate-seeds", action=argparse.BooleanOptionalAction,
                        default=False,
                        help="Rotate training seeds per generation. Each gen N uses "
                             "seeds [rotate_start + N*n_seeds, rotate_start + (N+1)*n_seeds). "
                             "All members of a gen face the same seeds, but seeds differ "
                             "across gens — prevents CMA-ES from compounding seed-specific "
                             "selection bias across generations. Default OFF (fixed seeds 0..n-1).")
    parser.add_argument("--rotate-start", type=int, default=10000,
                        help="Starting seed for rotation. Default 10000 (well clear of "
                             "the canonical holdout window 1000..1099). Ignored when "
                             "--rotate-seeds is OFF.")
    parser.add_argument("--validation-pool", type=int, default=0,
                        help="Number of fixed seeds used for the per-baseline + regression "
                             "diagnostics each generation (independent of training seeds). "
                             "0 (default) means reuse the training seeds (legacy behavior). "
                             "Set e.g. 50 to use a separate validation pool — gives a stable "
                             "diagnostic across gens even when --rotate-seeds is on.")
    parser.add_argument("--validation-pool-start", type=int, default=500,
                        help="Starting seed for the validation pool. Default 500. Should be "
                             "disjoint from training seeds and the holdout window.")
    parser.add_argument("--candidate-r1-force-forest",
                        action=argparse.BooleanOptionalAction, default=False,
                        help="Wrap the CANDIDATE's evaluator with r1_force_forest_bonus "
                             "during fitness evaluation, so CMA-ES samples configs that "
                             "learn the wood-rich post-R1 follow-up. Baselines play "
                             "normally (no override). Used to test the strategic claim "
                             "that wood-first R1 is stronger than V3's default reed-first "
                             "preference: a tune with this flag converges to V3-wood-tuned "
                             "configs that can then be head-to-head'd against V3-default. "
                             "V3 candidates only — V1 candidates are unaffected.")
    args = parser.parse_args()

    seeds = list(range(args.n_seeds))
    holdout_seeds = list(range(args.holdout_start, args.holdout_start + args.holdout_n))
    # Diagnostic seeds: fixed validation pool, OR training seeds (legacy).
    if args.validation_pool > 0:
        validation_seeds = list(range(args.validation_pool_start,
                                        args.validation_pool_start + args.validation_pool))
    else:
        validation_seeds = None  # signal: use training seeds (per-gen)

    # Resolve TUNABLE + architectures.
    tunable, candidate_arch = CATEGORIES[args.category]
    base_config, from_arch = _resolve_config(args.from_config)

    # Resolve baselines. --baselines (list) is the new canonical form;
    # --baseline (singular) is a backwards-compat alias for a one-element
    # list. Default is ['t2'] when neither is set.
    if args.baselines is None and args.baseline is None:
        baseline_specs = ["t2"]
    elif args.baselines is not None and args.baseline is not None:
        raise SystemExit("Set either --baselines or --baseline, not both.")
    elif args.baselines is not None:
        baseline_specs = list(args.baselines)
    else:
        baseline_specs = [args.baseline]

    baselines: list = []  # list of (config, arch) tuples
    for spec in baseline_specs:
        cfg, arch = _resolve_config(spec)
        baselines.append((cfg, arch))
    baseline_configs = [c for c, _ in baselines]
    baseline_archs = [a for _, a in baselines]

    # Regression-detector baseline (separate; not in fitness aggregate).
    if args.regression_baseline:
        regression_cfg, regression_arch = _resolve_config(args.regression_baseline)
    else:
        regression_cfg, regression_arch = None, None

    if from_arch != candidate_arch:
        raise SystemExit(
            f"--from {args.from_config!r} (arch {from_arch!r}) does not match "
            f"--category {args.category!r} (arch {candidate_arch!r}). "
            f"Use --from default_v3 for v3_* categories, --from default/t2 for v1_*."
        )

    # Populate module-level globals for the sequential code path (sanity
    # check, --jobs 1). Parallel workers receive these via Pool initializer.
    _init_worker(seeds, baseline_configs, baseline_archs,
                  base_config, candidate_arch, tunable,
                  restricted=args.restricted,
                  fitness_kind=args.fitness, fitness_k=args.fitness_k,
                  candidate_r1_force_forest=args.candidate_r1_force_forest)

    # CMA-ES starting vector: extract from `base_config` at each tuned
    # field's path. This means x0 EXACTLY corresponds to the warm-start
    # base, so the candidate at x0 equals the warm-start config (sanity
    # fitness ≈ warm-start performance). TUNABLE's `default` field is
    # informational only — describes the intended fresh-start point — but
    # the actual x0 always reflects the current base_config values.
    #
    # The earlier behavior (x0 = TUNABLE defaults) was a bug: it caused
    # regression at every category handoff where the warm-start base
    # already had tuned values for the about-to-be-tuned category. The
    # handoff would throw away those tuned values via x0 override.
    x0 = _x0_from_base(tunable, base_config)
    lower = [t[2] for t in tunable]
    upper = [t[3] for t in tunable]
    # Clip x0 into the bounds in case the base_config's value sits outside
    # the TUNABLE bounds for this category (CMA-ES would otherwise reject).
    x0 = np.clip(x0, lower, upper)

    if args.output is None:
        out_dir = ROOT / "tuned_configs"
        out_dir.mkdir(exist_ok=True)
        args.output = out_dir / f"{int(time.time())}.json"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    log_path = args.output.with_suffix(".log")

    # Open the log file and tee stdout into it. The original stdout is
    # restored in the finally block at the end of main(). Workers don't
    # print (they emit no stdout), so this is safe across multiprocessing.
    log_file = open(log_path, "w", buffering=1)  # line-buffered
    _original_stdout = sys.stdout
    sys.stdout = _Tee(_original_stdout, log_file)

    try:
        n_params = len(tunable)
        total_evals = args.popsize * args.max_gens
        per_game_sec = 0.5 if sys.flags.optimize else 1.0
        est_seconds_seq = total_evals * args.n_seeds * per_game_sec
        est_seconds_par = est_seconds_seq / max(1, args.jobs) * 1.15  # ~15% load-balance loss
        print(f"Tuning {n_params} parameters via CMA-ES")
        print(f"  category: {args.category!r}  (arch: {candidate_arch})")
        print(f"  warm-start base: {args.from_config!r}")
        if len(baseline_specs) == 1:
            print(f"  baseline opponent: {baseline_specs[0]!r} (arch: {baseline_archs[0]})")
        else:
            print(f"  baseline opponents (mean margin across all):")
            for spec, arch in zip(baseline_specs, baseline_archs):
                print(f"    - {spec!r} (arch: {arch})")
        if regression_cfg is not None:
            print(f"  regression detector: {args.regression_baseline!r} "
                  f"(arch: {regression_arch}) — measured per-gen on session-best")
        else:
            print(f"  regression detector: disabled")
        print(f"  restricted action set: {'ON (wrapper active for both sides)' if args.restricted else 'OFF (unrestricted legal_actions)'}")
        print(f"  seeds: {args.n_seeds} games per evaluation (training: 0..{args.n_seeds - 1})")
        print(f"  holdout: {args.holdout_n} games "
              f"({args.holdout_start}..{args.holdout_start + args.holdout_n - 1})")
        if args.resume:
            print(f"  resume: {args.resume}  (continues a previous run's CMA-ES state)")
        print(f"  popsize: {args.popsize}, max_gens: {args.max_gens}, sigma0: {args.sigma0}")
        if args.fitness == "margin":
            print(f"  fitness: margin (raw avg score-difference per game)")
        elif args.fitness == "sublinear":
            print(f"  fitness: sublinear  (per-game = sign(m)·|m|^{args.fitness_k})")
        elif args.fitness == "truncated":
            print(f"  fitness: truncated  (per-game = clip(m, -{args.fitness_k}, +{args.fitness_k}))")
        elif args.fitness == "win_rate":
            print(f"  fitness: win_rate   (fraction-of-wins shifted to [-0.5, +0.5])")
        if args.rotate_seeds:
            print(f"  rotate seeds: ON (each gen N uses seeds "
                  f"[{args.rotate_start}+N·{args.n_seeds}, {args.rotate_start}+(N+1)·{args.n_seeds}))")
        else:
            print(f"  rotate seeds: OFF (fixed training seeds 0..{args.n_seeds - 1})")
        if validation_seeds is not None:
            print(f"  validation pool: seeds {args.validation_pool_start}.."
                  f"{args.validation_pool_start + args.validation_pool - 1} "
                  f"(stable per-baseline diagnostic across gens)")
        else:
            print(f"  validation pool: OFF (per-baseline check uses training seeds)")
        if args.candidate_r1_force_forest:
            print(f"  candidate R1-force-forest: ON  (candidate's evaluator "
                  f"composed with +1000 bonus for R1 wood≥3; baselines unaffected)")
        print(f"  total evals: {total_evals}")
        print(f"  jobs: {args.jobs}; python -O: {'ON' if sys.flags.optimize else 'OFF'}")
        print(f"  estimated wall time: ~{est_seconds_par / 60:.1f} min "
              f"(vs ~{est_seconds_seq / 60:.1f} min if 1-job & no -O)")
        if not sys.flags.optimize:
            print(f"  TIP: re-run as `python -O ...` for ~2x speedup (strips debug asserts).")
        print(f"  Output: {args.output} (JSON, rewritten after every generation)")
        print(f"  Log:    {log_path} (human-readable progress mirror)")
        print()

        f0 = _eval_candidate(x0)
        if len(baseline_specs) == 1:
            print(f"Sanity: fitness(starting point vs {baseline_specs[0]!r} baseline) "
                  f"= {-f0:+.3f} margin")
        else:
            print(f"Sanity: fitness(starting point, mean margin across "
                  f"{len(baseline_specs)} baselines) = {-f0:+.3f}")
        print(f"  (sign/magnitude reflects warm-start config vs baseline strength gap)\n")
        return _run_optimization(args, seeds, holdout_seeds, base_config, candidate_arch,
                                  baseline_configs, baseline_archs, baseline_specs,
                                  regression_cfg, regression_arch, tunable,
                                  x0, lower, upper, log_path, sanity_f0=f0,
                                  validation_seeds=validation_seeds)
    finally:
        sys.stdout = _original_stdout
        log_file.close()


def _run_optimization(args, seeds, holdout_seeds, base_config, candidate_arch: str,
                      baseline_configs: list, baseline_archs: list,
                      baseline_specs: list,
                      regression_cfg, regression_arch,
                      tunable: list,
                      x0, lower, upper, log_path: Path, *, sanity_f0: float,
                      validation_seeds: list[int] | None = None) -> int:
    # The CMA-ES state pickle lives next to the JSON output, sharing its stem.
    pkl_path = args.output.with_suffix(".cma.pkl")

    if args.resume is not None:
        if not args.resume.is_file():
            raise SystemExit(f"--resume path {args.resume} not found")
        with open(args.resume, "rb") as f:
            es = pickle.load(f)
        if es.N != len(tunable):
            raise SystemExit(
                f"--resume state has dimension {es.N} but TUNABLE has {len(tunable)} "
                f"params. The category likely doesn't match the saved state."
            )
        start_gen = es.countiter
        target_gen = start_gen + args.max_gens
        # Raise the saved maxiter so es.stop() doesn't trigger on the
        # already-reached generation count from the prior session.
        es.opts["maxiter"] = target_gen
        print(f"Resumed from {args.resume}: countiter={start_gen}, "
              f"σ={es.sigma:.4f}, will run until gen {target_gen} "
              f"({args.max_gens} additional generations).")
        history = []  # local history for THIS resume session
    else:
        es = cma.CMAEvolutionStrategy(
            x0=x0, sigma0=args.sigma0,
            inopts={
                "bounds": [lower, upper],
                "popsize": args.popsize,
                "maxiter": args.max_gens,
                "seed": args.cma_seed,
                "verbose": -9,  # suppress cma's stdout; we print our own
            },
        )
        start_gen = 0
        target_gen = args.max_gens
        history = []

    t_start = time.perf_counter()

    # Session-best state, accessible to both the loop (which updates it) and
    # `write_results` (which serializes it). Defined as mutable so closures
    # see updates without rebinding. Initialized to x0 / sanity_f0 so the
    # very first write_results call (called before any gen completes) sees
    # the warm-start values rather than None/stale-es.best.
    session_best: dict = {
        "x": np.array(x0, copy=True),
        "f": float(sanity_f0),
    }

    def save_cma_state() -> None:
        """Pickle the full ES state to <output>.cma.pkl. Atomically write
        via a temp file then rename, so a crash mid-write can't corrupt
        the previous good state."""
        tmp_path = pkl_path.with_suffix(".cma.pkl.tmp")
        with open(tmp_path, "wb") as f:
            pickle.dump(es, f)
        tmp_path.replace(pkl_path)

    def write_results(*, status: str, holdout: dict | None = None) -> None:
        """Serialize current optimizer state to `args.output`.

        Called after every generation (status="in_progress") so a crash
        mid-run still leaves a usable artifact, and once at the end
        (status="complete", holdout populated)."""
        # Use the session-best (initialized to x0 / sanity_f0; updated by
        # the main loop as candidates beat it). Never uses es.best.x
        # directly because on --resume es.best can be stale.
        best_x = np.asarray(session_best["x"])
        best_margin = -float(session_best["f"])
        best_cfg = vector_to_config(best_x, base=base_config, tunable=tunable)
        # Backwards-compat single-baseline fields (first listed baseline)
        # are still surfaced so existing tooling that reads `baseline` /
        # `baseline_arch` continues to work. The new `baselines` /
        # `baseline_archs` lists are the canonical multi-baseline view.
        primary_baseline_spec = baseline_specs[0] if baseline_specs else None
        primary_baseline_arch = baseline_archs[0] if baseline_archs else None
        payload = {
            "status":            status,
            "category":          args.category,
            "candidate_arch":    candidate_arch,
            "from_config":       args.from_config,
            "baseline":          primary_baseline_spec,    # backwards-compat
            "baseline_arch":     primary_baseline_arch,    # backwards-compat
            "baselines":         list(baseline_specs),
            "baseline_archs":    list(baseline_archs),
            "regression_baseline":      args.regression_baseline or None,
            "regression_baseline_arch": regression_arch,
            "regression_history":       regression_history,
            "per_baseline_history":     per_baseline_history,
            "restricted":        bool(args.restricted),
            "fitness_kind":      args.fitness,
            "fitness_k":         float(args.fitness_k),
            "rotate_seeds":      bool(args.rotate_seeds),
            "rotate_start":      int(args.rotate_start),
            "validation_pool":   int(args.validation_pool),
            "validation_pool_start": int(args.validation_pool_start),
            "candidate_r1_force_forest": bool(args.candidate_r1_force_forest),
            "tunable_spec": [
                {"name": t[0], "default": t[1], "lower": t[2], "upper": t[3], "path": list(t[4])}
                for t in tunable
            ],
            "n_seeds":         args.n_seeds,
            "training_seeds":  seeds,
            "holdout_seeds":   holdout_seeds,
            "popsize":         args.popsize,
            "max_gens":        args.max_gens,
            "sigma0":          args.sigma0,
            "cma_seed":        args.cma_seed,
            "best_x":          list(map(float, best_x)),
            "best_margin":     best_margin,
            "best_config":     asdict(best_cfg),
            "history":         history,
            "holdout":         holdout,
            "log_path":        str(log_path),
            "cma_pkl_path":    str(pkl_path),
            "resumed_from":    str(args.resume) if args.resume else None,
            "start_gen":       start_gen,
        }
        args.output.write_text(json.dumps(payload, indent=2))

    # Per-generation drift trajectory: list of {generation, regression_margin}
    # measurements of session-best vs the regression baseline. Empty if
    # regression detector is disabled.
    regression_history: list[dict] = []
    # Per-generation per-baseline breakdown for the session-best candidate.
    # Each entry is {generation, per_baseline: [{baseline, margin}, ...]}.
    # Useful for post-mortems: "did fitness rise because we got better vs
    # every baseline, or did we trade wins on one for losses on another?"
    per_baseline_history: list[dict] = []
    # Per-baseline cache: the per-baseline check is deterministic in
    # (session_best["x"], seeds, baselines, restricted). When session_best
    # doesn't change across a generation, the result is identical to the
    # prior gen's. Cache and reuse to skip 6×n_seeds redundant games per
    # idle generation (significant for popsize/n-seeds combos where
    # session_best updates infrequently, e.g. small popsize on large
    # categories).
    cached_per_baseline_x: np.ndarray | None = None
    cached_per_baseline: list[dict] | None = None
    cached_diag_seeds: tuple | None = None  # invalidates cache when seeds rotate

    pool: Pool | None = None
    if args.jobs > 1:
        pool = Pool(
            processes=args.jobs,
            initializer=_init_worker,
            initargs=(seeds, baseline_configs, baseline_archs,
                      base_config, candidate_arch, tunable,
                      args.restricted, args.fitness, args.fitness_k,
                      args.candidate_r1_force_forest),
        )

    try:
        # `session_best` is the mutable shared dict initialized above
        # (before write_results). The loop updates it; write_results reads
        # from it. Initialization to (x0, sanity_f0) guarantees session-best
        # is never worse than the warm-start point (the previous "x0
        # fallback" block becomes implicit).

        # Loop until target_gen is reached, or until ES signals a "real"
        # stop condition (convergence etc.). We ignore the 'maxiter' stop
        # because we drive that ourselves via target_gen — a resumed ES has
        # its old maxiter cached and would short-circuit immediately.
        while not es.stop(ignore_list=["maxiter"]) and es.countiter < target_gen:
            X = es.ask()
            # Compute this gen's training seeds (rotated or fixed).
            gen_for_seeds = es.countiter + 1   # countiter is 0-indexed pre-ask
            if args.rotate_seeds:
                lo = args.rotate_start + gen_for_seeds * args.n_seeds
                train_seeds = list(range(lo, lo + args.n_seeds))
            else:
                train_seeds = seeds
            # Pack seeds into each task so workers use this gen's seed slice.
            # Falls back to legacy bare-ndarray task when rotation is off
            # (the worker globals already hold the right seeds).
            if args.rotate_seeds:
                tasks = [(np.asarray(x), train_seeds) for x in X]
            else:
                tasks = list(X)
            if pool is not None:
                fitnesses = pool.map(_eval_candidate, tasks)
            else:
                fitnesses = [_eval_candidate(t) for t in tasks]
            es.tell(X, fitnesses)

            # Update session-best from this generation's samples.
            for x, f in zip(X, fitnesses):
                if f < session_best["f"]:
                    session_best["f"] = float(f)
                    session_best["x"] = np.array(x, copy=True)

            gen = es.countiter
            gen_best = min(fitnesses)
            gen_mean = sum(fitnesses) / len(fitnesses)
            elapsed = time.perf_counter() - t_start
            print()
            print()
            print(f"gen {gen:>3}  best so far: {-session_best['f']:+.3f}  "
                  f"gen best: {-gen_best:+.3f}  gen mean: {-gen_mean:+.3f}  "
                  f"({elapsed / 60:.1f} min)")
            # Find the index of the gen-best sample so we can persist its
            # vector. Without this, only the session-best vector is recorded
            # and gens where session_best didn't update lose the gen-best
            # candidate's specific config. Useful for post-hoc analysis:
            # gen-bests with lower aggregate fitness may still be stronger
            # against individual baselines (the aggregate is a mean, so a
            # candidate that crushes one opponent and is mediocre on another
            # can rank below a more-balanced session_best yet be a useful
            # specialist to study).
            gen_best_idx = fitnesses.index(gen_best)
            gen_best_x = X[gen_best_idx]
            history.append({
                "generation":         gen,
                "best_margin_so_far": -session_best["f"],
                "best_x_so_far":      list(map(float, session_best["x"])),
                "gen_best_margin":    -float(gen_best),
                "gen_best_x":         list(map(float, gen_best_x)),
                "gen_mean_margin":    -float(gen_mean),
                "elapsed_seconds":    elapsed,
            })

            # Per-baseline diagnostic: measure the session-best candidate
            # against EACH fitness baseline individually, so we can attribute
            # fitness drift to specific opponents. The aggregate fitness
            # (mean across baselines) hides whether a gen-best is winning
            # uniformly or trading wins on one baseline for losses on another.
            # NOT part of the fitness signal — purely diagnostic. Recorded
            # in per_baseline_history alongside the regression check.
            best_cfg_for_drift = vector_to_config(
                np.asarray(session_best["x"]),
                base=base_config, tunable=tunable,
            )
            # Cache check: if session_best didn't change AND the diagnostic
            # seeds didn't change, the per-baseline result is deterministic
            # and identical to last gen's. Reuse and skip the redundant games.
            # Diagnostic seeds change when --rotate-seeds is on AND no
            # validation_pool is set (so diag seeds == per-gen train seeds).
            # With validation_pool set, diag seeds are fixed → cache valid.
            cur_x = np.asarray(session_best["x"])
            cur_diag_seeds = tuple(validation_seeds) if validation_seeds is not None else tuple(train_seeds)
            if (cached_per_baseline_x is not None
                and np.array_equal(cur_x, cached_per_baseline_x)
                and cached_diag_seeds == cur_diag_seeds):
                per_baseline = cached_per_baseline
                cached_this_gen = True
            else:
                # Diagnostic seeds: validation_pool if set (stable across
                # gens), otherwise the current gen's training seeds (legacy).
                diag_seeds = (validation_seeds if validation_seeds is not None
                               else train_seeds)
                # Parallelize across baselines via the worker pool when
                # available (gen-end is post-pool.map so the pool is idle).
                # Saves ~10 min per session-best-change generation: 7
                # baselines × 60 seeds went from sequential-in-master to
                # parallel-across-8-workers.
                diag_tasks = [
                    (best_cfg_for_drift, candidate_arch,
                     b_cfg, b_arch, diag_seeds, args.restricted,
                     bool(args.candidate_r1_force_forest))
                    for b_cfg, b_arch in zip(baseline_configs, baseline_archs)
                ]
                if pool is not None:
                    diag_results = pool.map(_eval_against_baseline_task, diag_tasks)
                else:
                    diag_results = [_eval_against_baseline_task(t) for t in diag_tasks]
                per_baseline = []
                for spec, r in zip(baseline_specs, diag_results):
                    per_baseline.append({
                        "baseline": spec,
                        "margin":   float(r.avg_margin),
                        "wins":     int(r.p0_wins),
                        "losses":   int(r.p1_wins),
                        "draws":    int(r.draws),
                    })
                cached_per_baseline_x = np.array(cur_x, copy=True)
                cached_per_baseline = per_baseline
                cached_diag_seeds = cur_diag_seeds
                cached_this_gen = False
            per_baseline_history.append({
                "generation":   gen,
                "per_baseline": per_baseline,
            })
            if len(per_baseline) > 1:
                # Compact label: strip "tuned_configs/" prefix and ".json"
                # suffix from baseline spec strings so the line stays
                # readable. "t2" / "default_v3" aliases pass through.
                def _label(spec: str) -> str:
                    s = spec
                    if s.startswith("tuned_configs/"):
                        s = s[len("tuned_configs/"):]
                    if s.endswith(".json"):
                        s = s[:-len(".json")]
                    return s
                breakdown = "  ".join(
                    f"{_label(row['baseline'])} {row['wins']:>2}-"
                    f"{row['draws']}-{row['losses']:<2} m={row['margin']:+5.2f}"
                    for row in per_baseline
                )
                cache_note = " [cached: session_best unchanged]" if cached_this_gen else ""
                print(f"           per-baseline (W-D-L  m=margin in raw score): "
                      f"{breakdown}{cache_note}")

            # Regression-detector check: measure the session-best candidate
            # against the fixed reference opponent (typically V1+T2).
            # NOT part of the fitness aggregate — this is purely diagnostic.
            # Recorded as RAW MARGIN in regression_history (the auto-promote
            # gate compares against this in margin units, regardless of what
            # fitness CMA-ES is optimizing). If this trend goes DOWN while
            # session_best fitness goes UP, the tuning is overfitting to the
            # multi-baseline aggregate.
            if regression_cfg is not None:
                # If the regression baseline is also one of the fitness
                # baselines, reuse the just-computed per-baseline result
                # instead of paying for the same match twice.
                drift_margin = None
                drift_record = None
                for row in per_baseline:
                    if row["baseline"] == args.regression_baseline:
                        drift_margin = row["margin"]
                        drift_record = (row["wins"], row["draws"], row["losses"])
                        break
                if drift_margin is None:
                    diag_seeds_reg = (validation_seeds if validation_seeds is not None
                                       else train_seeds)
                    r = _eval_against_baseline(
                        candidate_cfg=best_cfg_for_drift,
                        candidate_arch=candidate_arch,
                        baseline_cfg=regression_cfg,
                        baseline_arch=regression_arch,
                        seeds=diag_seeds_reg, restricted=args.restricted,
                        candidate_r1_force_forest=bool(args.candidate_r1_force_forest),
                    )
                    drift_margin = r.avg_margin
                    drift_record = (r.p0_wins, r.draws, r.p1_wins)
                regression_history.append({
                    "generation":         gen,
                    "regression_margin":  float(drift_margin),
                    "wins":               int(drift_record[0]),
                    "draws":              int(drift_record[1]),
                    "losses":             int(drift_record[2]),
                })
                wins, draws, losses = drift_record
                print(f"           regression vs {args.regression_baseline!r}: "
                      f"{wins:>2}-{draws}-{losses:<2}  m={drift_margin:+.3f}")

            write_results(status="in_progress")
            save_cma_state()
    finally:
        if pool is not None:
            pool.close()
            pool.join()

    best_x = np.asarray(session_best["x"])
    best_margin = -session_best["f"]
    sanity_margin = -sanity_f0

    # If session best didn't beat x0, the run produced no improvement.
    # By construction session_best["x"] == x0 in that case (initialization
    # was never overridden), so best_x equals the warm-start base's values
    # for the tuned fields. Print an informational warning so the user
    # knows the category had no slack.
    if session_best["f"] >= sanity_f0 - 1e-9:
        print()
        print(f"ℹ️  No CMA-ES sample beat x0 (warm-start base). Using x0 as best.")
        print(f"   This run preserves the warm-start config for the {len(tunable)} "
              f"tuned fields. Likely either: (a) the category was already "
              f"near-optimal in the warm-start, or (b) σ was too large/small "
              f"for this generation budget.")

    print()
    print(f"Optimization complete in {(time.perf_counter() - t_start) / 60:.1f} min.")
    print(f"Best margin (training): {best_margin:+.3f}")
    print()
    # "start" is the actual warm-start x0 (extracted from --from at each
    # TUNABLE path, then clipped into bounds) — i.e. the same x0 used by
    # the sanity-margin evaluation above. NOT the TUNABLE spec's static
    # `default` field, which is fresh-start reference metadata and would
    # be identical across every invocation regardless of --from. "delta"
    # is therefore best_x - x0: total movement from the warm-start in
    # this run (across resumed gens too).
    print(f"{'parameter':<35}  {'start':>9}  {'tuned':>9}  {'delta':>9}")
    print("-" * 70)
    for (name, _default, _lo, _hi, _path), start_val, val in zip(tunable, x0, best_x):
        print(f"{name:<35}  {start_val:>9.3f}  {val:>9.3f}  {val - start_val:>+9.3f}")

    # --- Holdout verification match ---
    # Holdout runs against the PRIMARY (first listed) baseline only, so
    # the recorded `holdout.avg_margin` stays directly comparable to
    # previous runs that used a single baseline. Multi-baseline tuning
    # still surfaces a per-baseline holdout breakdown in `holdout_by_baseline`.
    print()
    primary_spec = baseline_specs[0]
    primary_cfg = baseline_configs[0]
    primary_arch = baseline_archs[0]
    print(f"Running holdout match: tuned vs {primary_spec!r} primary baseline on "
          f"{len(holdout_seeds)} disjoint seeds...")
    best_cfg = vector_to_config(best_x, base=base_config, tunable=tunable)

    def tuned_factory(seed: int):
        agent = _make_agent(candidate_arch, best_cfg, seed,
                             restricted=args.restricted)
        # End-of-run holdout: candidate plays as it was tuned. When
        # --candidate-r1-force-forest is on, the candidate's evaluator
        # must include the bonus in deployment too, or the measurement
        # is on a different agent than CMA-ES optimized.
        if args.candidate_r1_force_forest and candidate_arch == "v3":
            from agricola.agents.heuristic import (
                compose_evaluators, r1_force_forest_bonus,
            )
            agent.evaluator = compose_evaluators(
                agent.evaluator, r1_force_forest_bonus,
            )
        return agent

    def baseline_factory(seed: int, _cfg=primary_cfg, _arch=primary_arch):
        return _make_agent(_arch, _cfg, seed, restricted=args.restricted)

    holdout_result = play_match(tuned_factory, baseline_factory, holdout_seeds)
    print(f"  holdout {holdout_result.summary_line()}")
    if holdout_result.avg_margin >= best_margin - 1.0:
        print("  → consistent with training (within 1pt). Tuning generalizes.")
    elif holdout_result.avg_margin > 0:
        print("  → smaller than training margin but still positive. Mild overfitting.")
    else:
        print("  → NEGATIVE on holdout. Likely overfit; treat training result with caution.")

    # Multi-baseline holdout breakdown — measure vs each baseline so users
    # can see per-opponent generalization. Always include the primary even
    # though it was just measured above; this keeps the structure uniform.
    holdout_by_baseline: list[dict] = []
    for spec, cfg, arch in zip(baseline_specs, baseline_configs, baseline_archs):
        def opp_factory(seed: int, _cfg=cfg, _arch=arch):
            return _make_agent(_arch, _cfg, seed, restricted=args.restricted)
        r = play_match(tuned_factory, opp_factory, holdout_seeds)
        holdout_by_baseline.append({
            "baseline": spec, "baseline_arch": arch,
            "avg_margin": r.avg_margin, "p0_wins": r.p0_wins,
            "p1_wins": r.p1_wins, "draws": r.draws,
        })
        if len(baseline_specs) > 1:
            print(f"  vs {spec!r}: margin {r.avg_margin:+.3f}  "
                  f"({r.p0_wins}-{r.draws}-{r.p1_wins})")

    # Regression detector on holdout (separate from the fitness baselines).
    regression_holdout: dict | None = None
    if regression_cfg is not None:
        def reg_factory(seed: int):
            return _make_agent(regression_arch, regression_cfg, seed,
                                restricted=args.restricted)
        r = play_match(tuned_factory, reg_factory, holdout_seeds)
        regression_holdout = {
            "baseline": args.regression_baseline,
            "baseline_arch": regression_arch,
            "avg_margin": r.avg_margin,
            "p0_wins": r.p0_wins, "p1_wins": r.p1_wins, "draws": r.draws,
        }
        print(f"  regression vs {args.regression_baseline!r}: "
              f"margin {r.avg_margin:+.3f}  ({r.p0_wins}-{r.draws}-{r.p1_wins})")

    holdout_payload = {
        "n_games":         holdout_result.n_games,
        "p0_wins":         holdout_result.p0_wins,
        "p1_wins":         holdout_result.p1_wins,
        "draws":           holdout_result.draws,
        "avg_score_p0":    holdout_result.avg_score_p0,
        "avg_score_p1":    holdout_result.avg_score_p1,
        "avg_margin":      holdout_result.avg_margin,
        "elapsed_seconds": holdout_result.elapsed_seconds,
        "by_baseline":     holdout_by_baseline,
        "regression":      regression_holdout,
    }
    write_results(status="complete", holdout=holdout_payload)
    save_cma_state()
    print(f"\nWritten: {args.output}")
    print(f"Log:     {log_path}")
    print(f"CMA pkl: {pkl_path}  (use --resume {pkl_path} to continue this run)")

    # --- Maintain a fixed best-of-architecture pointer ---
    # tuned_configs/<arch>_best.json always holds the highest-holdout-margin
    # result we've seen for this architecture. Drivers (e.g. play_web.py
    # --v3-config) can point at this stable path to always use the current
    # champion without remembering individual timestamped paths.
    if args.no_promote:
        print(f"Best:    skipped (--no-promote)")
    else:
        promoted = _enable_best_pointer_update(args.output, candidate_arch,
                                                holdout_payload)
        if promoted and args.reset_floor_after_promote:
            _reset_floor_in_best_pointer(
                arch=candidate_arch,
                champion_cfg=best_cfg,
                candidate_arch=candidate_arch,
                holdout_seeds=holdout_seeds,
                restricted=args.restricted,
            )
    return 0


def _enable_best_pointer_update(new_json_path: Path, arch: str,
                                new_holdout_payload: dict,
                                min_regression_n: int = 30) -> bool:
    """If the new run's holdout result beats the current
    `tuned_configs/<arch>_best.json`, copy `new_json_path` to that path.

    Comparison metric: ``holdout.regression.avg_margin`` — the candidate's
    margin against a FIXED reference baseline (typically t2 for V3). This
    is what protects against chained-baseline drift: ``holdout.avg_margin``
    is computed against whatever the current tuning baseline is, so it
    shifts with every promotion and can silently regress in absolute terms
    while looking like an improvement in relative terms. The regression
    margin doesn't have that bug — it's measured against a fixed anchor
    that doesn't move between runs.

    Gating requirements (all must hold for promotion):
      1. New payload has a non-null ``regression`` block. Without it we
         can't make a drift-safe comparison, so the run is held back.
      2. ``new_holdout_payload["n_games"] >= existing["n_games"]`` — same
         sample-size protection as before, against the held-out baseline.
      3. ``regression.n_games >= min_regression_n`` (default 30) — small
         regression samples are too noisy to trust as a drift signal.
      4. ``regression.baseline`` matches between existing and new — comparing
         margins against different reference baselines is apples-to-oranges.
      5. ``new_regression_margin > existing_regression_margin``.

    Existing files that predate the regression block are treated as having
    ``regression.avg_margin = -inf`` (any drift-safe candidate beats them).
    First-time initialization (no existing file) always accepts.

    Returns True on initialization or genuine promotion; False otherwise.
    The caller may use this to gate a subsequent floor-reset step.
    """
    import math
    import shutil
    best_path = ROOT / "tuned_configs" / f"{arch}_best.json"

    new_reg = (new_holdout_payload.get("regression") or {})
    new_reg_margin = new_reg.get("avg_margin")
    new_reg_n = new_reg.get("n_games") or new_holdout_payload.get("n_games") or 0
    new_reg_baseline = new_reg.get("baseline")
    new_n = new_holdout_payload.get("n_games") or 0

    # No regression block → can't make a drift-safe call. Hold the pointer.
    if new_reg_margin is None:
        print(f"Best:    {best_path}  (unchanged; new run has no regression block — "
              f"cannot compare drift-safely. Pass --regression-baseline to enable promotion.)")
        return False

    # Sample-size guard on the regression measurement itself.
    if new_reg_n < min_regression_n:
        print(f"Best:    {best_path}  (unchanged; new regression sample n={new_reg_n} "
              f"< min {min_regression_n} — too noisy to promote on)")
        return False

    # No existing best — initialize with the new file.
    if not best_path.exists():
        best_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(new_json_path, best_path)
        print(f"Best:    {best_path}  (initialized; regression vs {new_reg_baseline!r} "
              f"margin {new_reg_margin:+.2f}, n={new_reg_n})")
        return True

    # Load existing for comparison.
    try:
        existing = json.loads(best_path.read_text())
        existing_ho = existing.get("holdout") or {}
        existing_reg = existing_ho.get("regression") or {}
    except (json.JSONDecodeError, KeyError):
        existing_ho = {}
        existing_reg = {}

    existing_reg_margin = existing_reg.get("avg_margin", -math.inf)
    existing_reg_n = existing_reg.get("n_games") or existing_ho.get("n_games") or 0
    existing_reg_baseline = existing_reg.get("baseline")
    existing_n = existing_ho.get("n_games") or 0

    # Same-baseline check on the regression anchor.
    if (existing_reg_baseline is not None
        and existing_reg_baseline != new_reg_baseline):
        print(f"Best:    {best_path}  (unchanged; existing regression baseline "
              f"{existing_reg_baseline!r} ≠ new {new_reg_baseline!r} — different anchors, "
              f"comparison not meaningful)")
        return False

    # Sample-size guard on the held-out baseline summary (the original guard).
    if new_n < existing_n:
        print(f"Best:    {best_path}  (unchanged; new holdout sample {new_n} "
              f"< existing {existing_n})")
        return False

    if new_reg_margin > existing_reg_margin:
        best_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(new_json_path, best_path)
        print(f"Best:    {best_path}  (UPDATED on regression vs {new_reg_baseline!r}: "
              f"{existing_reg_margin:+.2f} (n={existing_reg_n}) → "
              f"{new_reg_margin:+.2f} (n={new_reg_n}))")
        return True
    else:
        print(f"Best:    {best_path}  (unchanged; existing regression "
              f"{existing_reg_margin:+.2f} (n={existing_reg_n}) >= new "
              f"{new_reg_margin:+.2f} (n={new_reg_n}))")
        return False


def _reset_floor_in_best_pointer(arch: str, champion_cfg, candidate_arch: str,
                                   holdout_seeds: list, restricted: bool) -> None:
    """After a fresh promotion, re-measure the just-promoted champion's
    self-match floor on the same holdout seeds and overwrite the stored
    `holdout.avg_margin` so future auto-promote decisions are apples-to-apples.

    Without this, chained-baseline runs (where the baseline keeps shifting
    to the latest champion) leave a stale `holdout.avg_margin` that
    represents "champion's gain over a now-obsolete predecessor" — far
    larger than the meaningful self-match floor, blocking future legitimate
    promotions. See V3_TRAINING_PIPELINE.md §X on the auto-update bug.
    """
    import shutil
    best_path = ROOT / "tuned_configs" / f"{arch}_best.json"
    if not best_path.exists():
        print(f"  (--reset-floor-after-promote: best file not found at {best_path}, skipping)")
        return

    def champion_factory(seed):
        return _make_agent(candidate_arch, champion_cfg, seed, restricted=restricted)

    print(f"  --reset-floor-after-promote: measuring self-match floor of "
          f"newly-promoted {arch} champion ({len(holdout_seeds)} games)...")
    res = play_match(champion_factory, champion_factory, holdout_seeds)
    print(f"  self-match floor: {res.summary_line()}")

    # Overwrite the holdout block in the promoted file with the self-match
    # measurement. n_games stays the same (same seed count), so future
    # n-comparison still works.
    d = json.loads(best_path.read_text())
    # Preserve regression/by_baseline blocks — they are our drift anchors,
    # not the self-match floor. The floor only replaces the held-out
    # baseline summary stats.
    prev_ho = d.get("holdout") or {}
    d["holdout"] = {
        "n_games":         res.n_games,
        "p0_wins":         res.p0_wins,
        "p1_wins":         res.p1_wins,
        "draws":           res.draws,
        "avg_score_p0":    res.avg_score_p0,
        "avg_score_p1":    res.avg_score_p1,
        "avg_margin":      res.avg_margin,
        "elapsed_seconds": res.elapsed_seconds,
        "holdout_seeds":   list(holdout_seeds),
        "by_baseline":     prev_ho.get("by_baseline"),
        "regression":      prev_ho.get("regression"),
        "note":            (f"Self-match floor (current champion vs self, "
                            f"restricted={restricted}, n={res.n_games}). "
                            f"Reset post-promotion by --reset-floor-after-promote. "
                            f"Note: comparison metric is now holdout.regression.avg_margin, "
                            f"not holdout.avg_margin — floor reset is informational only."),
    }
    best_path.write_text(json.dumps(d, indent=2))
    print(f"  {best_path}: holdout.avg_margin reset to {res.avg_margin:+.2f}")


if __name__ == "__main__":
    sys.exit(main())
