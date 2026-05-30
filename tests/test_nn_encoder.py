"""Tests for the NN input encoder (`agricola/agents/nn/encoder.py`).

Coverage:
- Output contract: shape, dtype, dim, names-length consistency.
- Determinism.
- Player-perspective: flipping player_idx swaps the own/opp blocks.
- Golden feature checks on hand-built states (resources, rooms, animals,
  crops, majors, starting player).
- food_owed: harvest-round vs non-harvest-round, newborn discount.
- Independent breeding-pair logic (a state where independent ≠ joint).
- Mid-action `subaction_available` (OR across the stack).
- Terminal-state zeroing (`game_end_indicator` + zeroed features).
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from agricola.agents.nn.encoder import (
    ENCODED_DIM,
    encode_state,
    feature_names,
)
from agricola.constants import HouseMaterial, Phase
from agricola.pending import (
    PendingCultivation,
    PendingFarmExpansion,
    PendingHarvestBreed,
    PendingHarvestFeed,
    PendingSow,
)
from agricola.setup import setup
from tests.factories import (
    with_animals,
    with_house,
    with_majors,
    with_pending_stack,
    with_phase,
    with_resources,
    with_round,
    with_sown_fields,
)


def _idx(name: str) -> int:
    """Index of a feature by name (built from the default setup state)."""
    return feature_names().index(name)


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


def test_output_shape_dtype():
    vec = encode_state(setup(0), 0)
    assert vec.shape == (ENCODED_DIM,)
    assert vec.dtype == np.float32


def test_feature_names_length_matches_dim():
    assert len(feature_names()) == ENCODED_DIM


def test_feature_names_unique():
    """No duplicate feature names — a dup would mean two slots collide in
    any name-indexed logic (e.g., terminal zeroing)."""
    names = feature_names()
    assert len(set(names)) == len(names)


def test_all_finite_on_setup():
    for seed in range(5):
        vec = encode_state(setup(seed), 0)
        assert np.all(np.isfinite(vec))


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_deterministic():
    s = setup(7)
    a = encode_state(s, 0)
    b = encode_state(s, 0)
    assert np.array_equal(a, b)


# ---------------------------------------------------------------------------
# Player perspective
# ---------------------------------------------------------------------------


def test_perspective_swaps_own_opp_blocks():
    """Encoding the same state from player 0 vs player 1 should swap the
    own and opponent blocks. Give the two players distinct resources and
    check the blocks swap."""
    s = setup(0)
    s = with_resources(s, 0, wood=5, clay=0)
    s = with_resources(s, 1, wood=0, clay=7)

    v0 = encode_state(s, 0)
    v1 = encode_state(s, 1)

    own_wood = _idx("own_wood")
    opp_wood = _idx("opp_wood")
    own_clay = _idx("own_clay")
    opp_clay = _idx("opp_clay")

    # From player 0's view: own=player0 (wood 5), opp=player1 (clay 7).
    assert v0[own_wood] == 5.0 and v0[opp_clay] == 7.0
    # From player 1's view: own=player1 (clay 7), opp=player0 (wood 5).
    assert v1[own_clay] == 7.0 and v1[opp_wood] == 5.0


# ---------------------------------------------------------------------------
# Golden feature checks
# ---------------------------------------------------------------------------


def test_resources_encoded():
    s = setup(0)
    s = with_resources(s, 0, wood=3, clay=2, reed=1, stone=4, food=9)
    v = encode_state(s, 0)
    assert v[_idx("own_wood")] == 3.0
    assert v[_idx("own_clay")] == 2.0
    assert v[_idx("own_reed")] == 1.0
    assert v[_idx("own_stone")] == 4.0
    assert v[_idx("own_food")] == 9.0


def test_rooms_split_by_material():
    """Room split puts the count in exactly the material's slot."""
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.CLAY)
    v = encode_state(s, 0)
    # Setup gives 2 starting rooms.
    assert v[_idx("own_clay_rooms")] == 2.0
    assert v[_idx("own_wood_rooms")] == 0.0
    assert v[_idx("own_stone_rooms")] == 0.0


def test_animals_encoded():
    s = setup(0)
    s = with_animals(s, 0, sheep=3, boar=1, cattle=2)
    v = encode_state(s, 0)
    assert v[_idx("own_sheep")] == 3.0
    assert v[_idx("own_boar")] == 1.0
    assert v[_idx("own_cattle")] == 2.0


def test_majors_owned():
    s = setup(0)
    s = with_majors(s, owner_by_idx={4: 0, 7: 1})  # Well to P0, Joinery to P1
    v = encode_state(s, 0)
    assert v[_idx("own_major_4")] == 1.0   # P0 owns Well
    assert v[_idx("opp_major_7")] == 1.0   # P1 owns Joinery
    assert v[_idx("own_major_7")] == 0.0
    assert v[_idx("own_major_0")] == 0.0


def test_starting_player():
    s = setup(0)
    sp = s.starting_player
    v = encode_state(s, sp)
    assert v[_idx("own_is_starting_player")] == 1.0
    v_other = encode_state(s, 1 - sp)
    assert v_other[_idx("own_is_starting_player")] == 0.0


def test_granular_crops():
    """A grain field with 3 and a veg field with 2 register in the right
    crop-count slots."""
    s = setup(0)
    # with_sown_fields: grain_fields get 3 grain, veg_fields get 2 veg.
    s = with_sown_fields(s, 0, grain_fields=[(0, 2)], veg_fields=[(0, 3)])
    v = encode_state(s, 0)
    assert v[_idx("own_grain_fields_3")] == 1.0
    assert v[_idx("own_veg_fields_2")] == 1.0
    assert v[_idx("own_grain_fields_2")] == 0.0


# ---------------------------------------------------------------------------
# food_owed
# ---------------------------------------------------------------------------


def test_food_owed_non_harvest_round():
    """Off a harvest round: 2 * people_total, no newborn discount."""
    s = setup(0)  # round 1, not a harvest round
    # setup: 2 people each.
    v = encode_state(s, 0)
    assert v[_idx("own_food_owed")] == 4.0  # 2 * 2


def test_food_owed_harvest_round_with_newborn():
    """On a harvest round, newborns cost 1 instead of 2: 2*total - newborns."""
    from tests.factories import with_people
    s = setup(0)
    s = with_round(s, 4)  # round 4 is a harvest round
    s = with_people(s, 0, total=3, home=3, newborns=1)
    v = encode_state(s, 0)
    # 2*3 - 1 = 5
    assert v[_idx("own_food_owed")] == 5.0


# ---------------------------------------------------------------------------
# Independent breeding-pair logic
# ---------------------------------------------------------------------------


def test_breeding_pair_independent():
    """Independent semantics: each type with >=2 and room for its own
    newborn flags 1, even if joint capacity couldn't fit all newborns.

    Setup farm has no pastures, so capacity is just the flexible slots
    (house pet + standalone stables). With no stables, flex=1 (house pet).
    Give 2 of each animal; each type independently needs room for 3, which
    a flex=1 farm cannot provide — so all should be 0 here. Then give a
    big pasture and recheck."""
    s = setup(0)
    s = with_animals(s, 0, sheep=2, boar=2, cattle=2)
    v = encode_state(s, 0)
    # flex=1 only (house pet); can't hold 3 of any type → all 0.
    assert v[_idx("own_breed_sheep")] == 0.0
    assert v[_idx("own_breed_boar")] == 0.0
    assert v[_idx("own_breed_cattle")] == 0.0


def test_breeding_pair_needs_two():
    """A type with only 1 animal never flags, regardless of capacity."""
    s = setup(0)
    s = with_animals(s, 0, sheep=1, boar=0, cattle=0)
    v = encode_state(s, 0)
    assert v[_idx("own_breed_sheep")] == 0.0


# ---------------------------------------------------------------------------
# Mid-action subaction_available
# ---------------------------------------------------------------------------


def test_subaction_available_empty_stack():
    """No action in progress → all subaction bits zero."""
    s = setup(0)
    v = encode_state(s, 0)
    for cat in ("build_rooms", "build_stables", "plow", "bake_bread",
                "sow", "build_fences", "build_major"):
        assert v[_idx(f"subaction_avail_{cat}")] == 0.0


def test_subaction_available_fresh_cultivation():
    """Mid-Cultivation, nothing chosen yet → both plow and sow available."""
    s = setup(0)
    frame = PendingCultivation(player_idx=0, initiated_by_id="space:cultivation")
    s = with_pending_stack(s, [frame])
    v = encode_state(s, 0)
    assert v[_idx("subaction_avail_plow")] == 1.0
    assert v[_idx("subaction_avail_sow")] == 1.0
    assert v[_idx("subaction_avail_bake_bread")] == 0.0


def test_subaction_available_or_across_stack():
    """Mid-Cultivation with plow chosen, mid-resolving a Sow on top:
    sow available (mid-resolving) AND plow already chosen (not available).
    The OR-across-stack should give sow=1, plow=0."""
    s = setup(0)
    parent = PendingCultivation(
        player_idx=0, initiated_by_id="space:cultivation",
        plow_chosen=True, sow_chosen=True,
    )
    sub = PendingSow(player_idx=0, initiated_by_id="cultivation")
    s = with_pending_stack(s, [parent, sub])
    v = encode_state(s, 0)
    # sow is mid-resolving (PendingSow on top) → available.
    assert v[_idx("subaction_avail_sow")] == 1.0
    # plow already chosen on the parent → not available.
    assert v[_idx("subaction_avail_plow")] == 0.0


def test_subaction_available_farm_expansion_partial():
    """Mid-Farm-Expansion with rooms chosen but stables not → only
    build_stables available from the parent."""
    s = setup(0)
    frame = PendingFarmExpansion(
        player_idx=0, initiated_by_id="space:farm_expansion",
        room_chosen=True, stable_chosen=False,
    )
    s = with_pending_stack(s, [frame])
    v = encode_state(s, 0)
    assert v[_idx("subaction_avail_build_rooms")] == 0.0
    assert v[_idx("subaction_avail_build_stables")] == 1.0


# ---------------------------------------------------------------------------
# Terminal-state zeroing
# ---------------------------------------------------------------------------


def test_current_player_is_own_uses_decider_during_harvest():
    """Regression for the v1→v2 encoder bug: during harvest sub-phases the
    decider is the top pending frame's `player_idx`, NOT `state.current_player`
    (which is stale from the last WORK action). `current_player_is_own` must
    reflect the decider per the project's `decider_of(state)` contract.

    Setup: round 4 (a harvest round), phase HARVEST_FEED, with a stale
    `current_player=0` from end of WORK and a PendingHarvestFeed for P1
    on top. The decider is P1.

    Expected:
    - encode(state, 0)[current_player_is_own] == 0  (P0 is NOT the decider)
    - encode(state, 1)[current_player_is_own] == 1  (P1 IS the decider)

    The v1 encoder would have used state.current_player (= 0), giving the
    flipped (wrong) values: 1 and 0 respectively.
    """
    s = setup(0)
    s = with_round(s, 4)
    s = with_phase(s, Phase.HARVEST_FEED)
    # current_player stale from WORK — explicitly set to 0 (opposite of decider).
    s = replace(s, current_player=0)
    # Push P1's harvest-feed pending on top.
    s = with_pending_stack(s, (
        PendingHarvestFeed(player_idx=1, initiated_by_id="phase:harvest_feed"),
    ))

    v_p0 = encode_state(s, 0)
    v_p1 = encode_state(s, 1)

    assert v_p0[_idx("current_player_is_own")] == 0.0, (
        "From P0's perspective, decider is P1, so current_player_is_own should be 0."
    )
    assert v_p1[_idx("current_player_is_own")] == 1.0, (
        "From P1's perspective, decider is P1 (top of stack), so "
        "current_player_is_own should be 1 — even though state.current_player == 0."
    )


def test_current_player_is_own_uses_decider_during_breed():
    """Same regression check for HARVEST_BREED (the other phase where
    `_initiate_harvest_breed` pushes pendings without updating
    `state.current_player`)."""
    s = setup(0)
    s = with_round(s, 4)
    s = with_phase(s, Phase.HARVEST_BREED)
    s = replace(s, current_player=1)
    # Push P0's harvest-breed pending on top.
    s = with_pending_stack(s, (
        PendingHarvestBreed(player_idx=0, initiated_by_id="phase:harvest_breed"),
    ))

    v_p0 = encode_state(s, 0)
    v_p1 = encode_state(s, 1)

    assert v_p0[_idx("current_player_is_own")] == 1.0
    assert v_p1[_idx("current_player_is_own")] == 0.0


def test_current_player_is_own_empty_stack_uses_current_player():
    """When the stack is empty, `decider_of` falls back to
    `state.current_player`. Confirms the v2 fix doesn't regress the
    empty-stack case (the only case where v1 was correct)."""
    s = setup(0)
    s = replace(s, current_player=1)
    # Stack is empty by default.
    assert s.pending_stack == ()

    v_p0 = encode_state(s, 0)
    v_p1 = encode_state(s, 1)

    assert v_p0[_idx("current_player_is_own")] == 0.0
    assert v_p1[_idx("current_player_is_own")] == 1.0


def test_terminal_zeroing():
    """At BEFORE_SCORING: game_end_indicator=1, and the §4.5 next-decision
    features are forced to zero, while scoring-relevant features survive."""
    s = setup(0)
    s = with_resources(s, 0, wood=5, food=9)  # survives
    s = with_animals(s, 0, sheep=4)           # survives
    terminal = with_phase(s, Phase.BEFORE_SCORING)
    v = encode_state(terminal, 0)

    # Indicator on.
    assert v[_idx("game_end_indicator")] == 1.0
    # Next-decision features zeroed.
    assert v[_idx("own_food_owed")] == 0.0
    assert v[_idx("own_family_left")] == 0.0
    assert v[_idx("own_has_fed")] == 0.0
    assert v[_idx("own_future_food")] == 0.0
    assert v[_idx("current_player_is_own")] == 0.0
    assert v[_idx("in_harvest")] == 0.0
    assert v[_idx("rounds_until_next_harvest")] == 0.0
    for cat in ("plow", "sow", "build_rooms"):
        assert v[_idx(f"subaction_avail_{cat}")] == 0.0
    # Scoring-relevant features survive.
    assert v[_idx("own_wood")] == 5.0
    assert v[_idx("own_food")] == 9.0
    assert v[_idx("own_sheep")] == 4.0


# ---------------------------------------------------------------------------
# rounds_until_next_harvest
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("round_number,expected", [
    (1, 3), (3, 1), (4, 0), (5, 2), (7, 0), (8, 1), (14, 0),
])
def test_rounds_until_next_harvest(round_number, expected):
    s = with_round(setup(0), round_number)
    v = encode_state(s, 0)
    assert v[_idx("rounds_until_next_harvest")] == float(expected)
