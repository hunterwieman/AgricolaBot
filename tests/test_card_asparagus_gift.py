"""Tests for Asparagus Gift (minor A68; Artifex).

"Each time you build a number of fences equal to or greater than the current
round, you immediately get 1 vegetable." Prerequisite: 1 Unplanted Field.

The card is a before/after pair of automatic effects on the build_fences host:
`before_build_fences` snapshots the fence-piece count, `after_build_fences`
grants 1 veg iff the number of fence pieces placed in that action is >= the
current round number. Tests drive the REAL fencing flow (Fencing space and
Farm Redevelopment), per CARD_AUTHORING_GUIDE §5.

A 2x2 corner pasture costs exactly 8 fence pieces (probed against the engine),
so it qualifies at round <= 8 and does NOT at round 9.
"""
import agricola.cards.asparagus_gift  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.asparagus_gift import CARD_ID, _one_unplanted_field
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from tests.factories import (
    with_fields,
    with_house,
    with_resources,
    with_round,
    with_sown_fields,
    with_space,
)
from tests.test_fencing import _fencing_setup
from tests.test_utils import sole_renovate

# A top-right 2x2 (4 cells, 8 fence pieces) — in the default RESTRICTED universe.
_2x2_TR = frozenset({(0, 3), (0, 4), (1, 3), (1, 4)})
# A second disjoint 2x2 (also 8 pieces) for the multi-action / two-pasture cases.
_2x2_2 = frozenset({(0, 1), (0, 2), (1, 1), (1, 2)})


def _own(state, idx=0, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _enter_build_fences(state):
    state = step(state, PlaceWorker(space="fencing"))
    state = step(state, ChooseSubAction(name="build_fences"))
    return state


def _finish(state):
    """Proceed (flip PBF to after — fires the grant) then drain the two Stops."""
    state = step(state, Proceed())   # flips PendingBuildFences -> after (grant fires)
    state = step(state, Stop())      # pop PendingBuildFences
    state = step(state, Stop())      # pop PendingSubActionSpace
    return state


def _veg(state, idx=0):
    return state.players[idx].resources.veg


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()  # free: no resources, no animals
    assert spec.cost.resources == Resources() and spec.cost.animals == Animals()
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.prereq is _one_unplanted_field


# ---------------------------------------------------------------------------
# Prerequisite: 1 Unplanted Field
# ---------------------------------------------------------------------------

def test_prereq_requires_an_unplanted_field():
    spec = MINORS[CARD_ID]
    # Fresh farm: no fields at all -> prereq NOT met.
    state = _fencing_setup(wood=12)
    assert not prereq_met(spec, state, 0)
    # An unplanted (empty) field -> prereq met.
    state2 = with_fields(state, 0, [(0, 0)])
    assert prereq_met(spec, state2, 0)


def test_prereq_planted_field_does_not_count():
    spec = MINORS[CARD_ID]
    state = _fencing_setup(wood=12)
    # Only sown fields (grain / veg) present -> not "unplanted" -> prereq NOT met.
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)], veg_fields=[(1, 0)])
    assert not prereq_met(spec, state, 0)
    # Add one unplanted field -> now met.
    state = with_fields(state, 0, [(2, 0)])
    assert prereq_met(spec, state, 0)


def test_prereq_met_via_empty_card_field():
    """Ruling 45 (2026-07-12): a card-field is a field, so an owned, EMPTY
    card-field is an unplanted field — it alone satisfies "1 Unplanted Field"
    (the old grid-only read failed this). Once planted it is no longer
    unplanted and stops satisfying it."""
    from agricola.cards.card_fields import stacks_to_store
    spec = MINORS[CARD_ID]
    state = _fencing_setup(wood=12)          # fresh farm: no grid fields
    assert not prereq_met(spec, state, 0)
    # An owned, never-sown Beanfield (no CardStore entry = all-empty) -> met.
    owned = _own(state, 0, "beanfield")
    assert prereq_met(spec, owned, 0)
    # Plant it (2 veg) -> the card-field is planted and no grid field is
    # unplanted -> prereq NOT met.
    p = owned.players[0]
    p = fast_replace(
        p, card_state=stacks_to_store(p.card_state, "beanfield", ((0, 2, 0, 0),)))
    planted = fast_replace(owned, players=tuple(
        p if i == 0 else owned.players[i] for i in range(2)))
    assert not prereq_met(spec, planted, 0)
    # An unplanted grid field alongside the planted card-field -> met again.
    assert prereq_met(spec, with_fields(planted, 0, [(2, 0)]), 0)


# ---------------------------------------------------------------------------
# The grant — threshold delta >= round_number
# ---------------------------------------------------------------------------

def test_grant_when_fences_meet_threshold():
    # Round 1, build 8 fence pieces (2x2): 8 >= 1 -> +1 veg.
    state = _own(_fencing_setup(wood=12))
    assert _veg(state) == 0
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = _finish(state)
    assert _veg(state) == 1
    # Snapshot reset to canonical 0 (path-independence).
    assert state.players[0].card_state.get(CARD_ID) == 0


def test_grant_is_fixed_one_veg_not_per_fence():
    # Two 2x2 pastures in one action = 16 fence pieces, but the grant is a FIXED
    # 1 veg per qualifying ACTION, not 1 per fence over the threshold.
    state = _own(_fencing_setup(wood=24))
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, CommitBuildPasture(cells=_2x2_2))
    state = _finish(state)
    assert _veg(state) == 1


def test_no_grant_when_below_threshold():
    # Round 9, build 8 fence pieces (2x2): 8 < 9 -> no veg.
    state = _own(_fencing_setup(wood=12))
    state = with_round(state, 9)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = _finish(state)
    assert _veg(state) == 0


def test_boundary_equal_to_round_grants():
    # "equal to or greater than": at round 8 exactly, 8 fence pieces -> +1 veg.
    state = _own(_fencing_setup(wood=12))
    state = with_round(state, 8)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = _finish(state)
    assert _veg(state) == 1


def test_no_grant_without_card():
    # Same flow but the card is NOT owned -> nothing happens.
    state = _fencing_setup(wood=12)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = _finish(state)
    assert _veg(state) == 0


def test_per_action_fixed_grant_across_two_actions():
    # The grant is per build-fences ACTION: two separate qualifying actions each
    # grant 1 veg (here, two worker placements would be needed, so we instead
    # verify the snapshot resets to 0 so a SECOND action re-measures from scratch
    # rather than accumulating).
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = _finish(state)
    assert _veg(state) == 1
    assert state.players[0].card_state.get(CARD_ID) == 0


# ---------------------------------------------------------------------------
# Other entry point: Farm Redevelopment ("Overhaul")
# ---------------------------------------------------------------------------

def test_via_farm_redevelopment():
    state = _fencing_setup(wood=12)
    state = with_house(state, 0, material=HouseMaterial.WOOD)
    state = with_resources(state, 0, wood=12, clay=4, reed=2)
    state = _own(state)
    state = with_space(state, "farm_redevelopment", revealed=True)
    state = step(state, PlaceWorker(space="farm_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    state = step(state, sole_renovate(state))
    state = step(state, Stop())                                  # pop PendingRenovate
    state = step(state, ChooseSubAction(name="build_fences"))
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, Proceed())                              # flip PBF -> after (grant)
    state = step(state, Stop())                                 # pop PBF
    state = step(state, Proceed())                              # flip FarmRedev -> after
    state = step(state, Stop())                                 # pop FarmRedev
    assert _veg(state) == 1
