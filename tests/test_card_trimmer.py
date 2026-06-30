"""Tests for Trimmer (occupation B124).

"In each work phase, after you enclose at least one farmyard space, you get 2
stone. (Subdividing an existing pasture does not count.)"

Trimmer is a before/after pair of automatic effects on the build_fences host:
`before_build_fences` snapshots the enclosed cells, `after_build_fences` grants 2
stone if ANY farmyard space became newly enclosed during the action AND the card
hasn't already fired this work phase (the `used_this_round` latch). Tests drive the
REAL fencing flow (Fencing space and Farm Redevelopment), per CARD_AUTHORING_GUIDE
§5.
"""
import agricola.cards.trimmer  # noqa: F401  (registers the card; not yet in cards/__init__)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.trimmer import CARD_ID
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from tests.factories import with_resources, with_space
from tests.test_fencing import _fencing_setup, _with_initial_pasture
from tests.test_utils import sole_renovate

# Shapes known to be in the default RESTRICTED universe (from test_restricted_actions
# fencing rules): a top-right 2x2 (4 cells) and 2x3 (6 cells).
_2x2_TR = frozenset({(0, 3), (0, 4), (1, 3), (1, 4)})
_2x3_TR = frozenset({(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)})
_TOP_1x2 = frozenset({(0, 3), (0, 4)})           # lex-smaller half of the 2x3 split
_SECOND_2x2 = frozenset({(0, 1), (0, 2), (1, 1), (1, 2)})


def _own(state, idx=0, card_id=CARD_ID):
    """Give player `idx` the occupation (Trimmer lives in `occupations`)."""
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
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


def _stone(state, idx=0):
    return state.players[idx].resources.stone


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    # Occupation: no cost / prereq / passing / vps overrides; on-play is a no-op.
    spec = OCCUPATIONS[CARD_ID]
    state = _fencing_setup(wood=0)
    assert spec.on_play(state, 0) is state


# ---------------------------------------------------------------------------
# The grant
# ---------------------------------------------------------------------------

def test_new_2x2_grants_2_stone():
    state = _own(_fencing_setup(wood=12))
    assert _stone(state) == 0
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = _finish(state)
    assert _stone(state) == 2
    assert CARD_ID in state.players[0].used_this_round   # latched
    # Snapshot reset to a canonical empty value (path-independence).
    assert state.players[0].card_state.get(CARD_ID) == frozenset()


def test_small_new_pasture_still_grants():
    # Trimmer has NO size threshold — any newly-enclosed space qualifies, unlike
    # Shepherd's Crook. A 1x1 (in RESTRICTED at high wood) grants the 2 stone.
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    legal = legal_actions(state)
    small = next(
        a for a in legal
        if isinstance(a, CommitBuildPasture) and len(a.cells) < 4
    )
    state = step(state, small)
    state = _finish(state)
    assert _stone(state) == 2


def test_two_new_pastures_one_action_grant_only_2_stone():
    # Two disjoint new pastures in ONE action enclose new space, but the grant is a
    # flat +2 stone for the action (not per pasture).
    state = _own(_fencing_setup(wood=24))
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, CommitBuildPasture(cells=_SECOND_2x2))
    state = _finish(state)
    assert _stone(state) == 2


# ---------------------------------------------------------------------------
# Eligibility boundaries — no grant
# ---------------------------------------------------------------------------

def test_no_grant_without_card():
    state = _fencing_setup(wood=12)            # does NOT own the card
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = _finish(state)
    assert _stone(state) == 0


def test_subdivide_existing_pasture_no_grant():
    # "Subdividing an existing pasture does not count." Pre-existing 2x3; subdivide
    # it. No NEW cells are enclosed -> 0 stone, and the card does NOT latch.
    state = _own(_fencing_setup(wood=12))
    state = _with_initial_pasture(
        state, 0, [(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)]
    )
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2))     # subdivision
    state = _finish(state)
    assert _stone(state) == 0
    assert CARD_ID not in state.players[0].used_this_round


def test_extend_existing_pasture_grants_for_new_cells():
    # Extending a pasture DOES enclose new farmyard spaces (the added cells), so it
    # qualifies — Trimmer only requires "enclose at least one farmyard space", with
    # no whole-pasture-is-new requirement (unlike Shepherd's Crook).
    state = _own(_fencing_setup(wood=12))
    state = _with_initial_pasture(state, 0, [(0, 3), (0, 4)])
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=frozenset({(1, 3), (1, 4)})))
    state = _finish(state)
    assert _stone(state) == 2


# ---------------------------------------------------------------------------
# Once-per-work-phase latch
# ---------------------------------------------------------------------------

def _latch(state, idx=0, card_id=CARD_ID):
    """Pre-set the per-work-phase used-set as if the card already fired this phase."""
    p = state.players[idx]
    p = fast_replace(p, used_this_round=p.used_this_round | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def test_already_fired_this_phase_grants_nothing():
    # "In each work phase ... you get 2 stone" is once per work phase. If the card
    # already fired earlier in this phase (used_this_round latched), a second genuine
    # enclosing action grants nothing — driven through the REAL build_fences flow.
    state = _latch(_own(_fencing_setup(wood=12)))
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))     # genuinely encloses new space
    state = _finish(state)
    assert _stone(state) == 0                                  # suppressed by the latch
    # The snapshot is still reset (path-independence holds regardless of the grant).
    assert state.players[0].card_state.get(CARD_ID) == frozenset()


def test_latch_clears_at_round_start_rearms_grant():
    # After firing, clearing used_this_round (what _complete_preparation does at the
    # start of each round) re-arms the grant. Drive a real build before AND after the
    # clear; each grants +2.
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = _finish(state)
    assert _stone(state) == 2
    assert CARD_ID in state.players[0].used_this_round

    # Simulate the round-start clear of the per-round used-set (a fresh-round state
    # where used_this_round is empty again), then build a genuine new pasture.
    fresh = _own(_fencing_setup(wood=12))
    assert CARD_ID not in fresh.players[0].used_this_round     # latch is clear again
    fresh = _enter_build_fences(fresh)
    fresh = step(fresh, CommitBuildPasture(cells=_2x2_TR))
    fresh = _finish(fresh)
    assert _stone(fresh) == 2                                  # grants again on the cleared latch


# ---------------------------------------------------------------------------
# Other entry point
# ---------------------------------------------------------------------------

def test_via_farm_redevelopment():
    # Farm Redevelopment ("Overhaul") also pushes PendingBuildFences, so the hook
    # fires there too.
    state = _fencing_setup(wood=12)
    from tests.factories import with_house
    state = with_house(state, 0, material=HouseMaterial.WOOD)
    state = with_resources(state, 0, wood=12, clay=4, reed=2)
    state = _own(state)
    state = with_space(state, "farm_redevelopment", revealed=True)
    state = step(state, PlaceWorker(space="farm_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    state = step(state, sole_renovate(state))
    state = step(state, Stop())                                # pop PendingRenovate
    state = step(state, ChooseSubAction(name="build_fences"))
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, Proceed())                             # flip PBF -> after (grant)
    state = step(state, Stop())                                # pop PBF
    state = step(state, Proceed())                             # flip FarmRedev -> after
    state = step(state, Stop())                                # pop FarmRedev
    assert _stone(state) == 2
