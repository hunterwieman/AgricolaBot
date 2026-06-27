"""Tests for Shepherd's Crook (minor A83).

"Each time you fence a new pasture covering at least 4 farmyard spaces, you
immediately get 2 sheep on this pasture."

The card is a before/after pair of automatic effects on the build_fences host:
`before_build_fences` snapshots the enclosed cells, `after_build_fences` grants 2
sheep per pasture in the after-decomposition that lies entirely on newly-enclosed
cells and spans >= 4 spaces. Tests drive the REAL fencing flow (Fencing space and
Farm Redevelopment), per CARD_AUTHORING_GUIDE §5.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    CommitRenovate,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.shepherds_crook import CARD_ID
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from tests.factories import with_house, with_resources
from tests.test_fencing import _fencing_setup, _with_initial_pasture

from agricola.constants import HouseMaterial

# Shapes known to be in the default RESTRICTED universe (from test_restricted_actions
# fencing rules): a top-right 2x2 (4 cells) and 2x3 (6 cells), each enclosable on
# the standard farm (rooms sit in column 0).
_2x2_TR = frozenset({(0, 3), (0, 4), (1, 3), (1, 4)})
_2x3_TR = frozenset({(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)})
_TOP_1x2 = frozenset({(0, 3), (0, 4)})           # lex-smaller half of the 2x3 split


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


def _sheep(state, idx=0):
    return state.players[idx].animals.sheep


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# The grant
# ---------------------------------------------------------------------------

def test_new_2x2_grants_2_sheep():
    state = _own(_fencing_setup(wood=12))
    assert _sheep(state) == 0
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = _finish(state)
    assert _sheep(state) == 2
    # Snapshot reset to a canonical empty value (path-independence).
    assert state.players[0].card_state.get(CARD_ID) == frozenset()


def test_new_2x3_grants_2_sheep_one_pasture():
    # A single 6-space pasture is one qualifying pasture -> 2 sheep (not 3).
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x3_TR))
    state = _finish(state)
    assert _sheep(state) == 2


def test_two_new_pastures_grant_4_sheep():
    # "Building 2 such pastures at once gives you 4 sheep" — two disjoint new
    # >=4 pastures in one fencing action, each granting 2.
    second_2x2 = frozenset({(0, 1), (0, 2), (1, 1), (1, 2)})
    state = _own(_fencing_setup(wood=24))
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, CommitBuildPasture(cells=second_2x2))
    state = _finish(state)
    assert _sheep(state) == 4


def test_no_grant_without_card():
    state = _fencing_setup(wood=12)            # does NOT own the card
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = _finish(state)
    assert _sheep(state) == 0


def test_small_pasture_no_grant():
    # A 1x1 (in RESTRICTED at high wood) is < 4 spaces -> no sheep.
    state = _own(_fencing_setup(wood=12))
    state = _enter_build_fences(state)
    legal = legal_actions(state)
    small = next(
        a for a in legal
        if isinstance(a, CommitBuildPasture) and len(a.cells) < 4
    )
    state = step(state, small)
    state = _finish(state)
    assert _sheep(state) == 0


def test_build_then_subdivide_grants_for_4_piece():
    # The maintainer-confirmed ruling AND the reason the grant is computed at the
    # end: build a NEW 6-space area, split it into a 4 and a 2 in the same action.
    # The undivided 4-space piece grants; the 2 does not -> 2 sheep total.
    state = _own(_fencing_setup(wood=14))
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x3_TR))      # new 6-space region
    # Subdivide off the top 1x2, leaving a bottom 2x2 (4 cells).
    state = step(state, CommitBuildPasture(cells=_TOP_1x2))
    state = _finish(state)
    assert _sheep(state) == 2


def test_extend_existing_pasture_no_grant():
    # Pre-existing 1x2 at the top; fence-extend it to a 2x2. The resulting >=4
    # pasture is NOT entirely on new cells (2 of its 4 were already enclosed) -> 0.
    state = _own(_fencing_setup(wood=12))
    state = _with_initial_pasture(state, 0, [(0, 3), (0, 4)])
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=frozenset({(1, 3), (1, 4)})))
    state = _finish(state)
    # The decomposition is now a single 2x2, but it sits on old+new cells.
    assert _sheep(state) == 0


def test_subdivide_existing_pasture_no_grant():
    # Pre-existing 2x3 (already >=4); subdivide it. No NEW cells are enclosed, so
    # nothing qualifies -> 0 sheep.
    state = _own(_fencing_setup(wood=12))
    state = _with_initial_pasture(state, 0, [(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)])
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2))     # subdivision
    state = _finish(state)
    assert _sheep(state) == 0


def test_via_farm_redevelopment():
    # The other entry point: Farm Redevelopment ("Overhaul") also pushes
    # PendingBuildFences, so the hook fires there too.
    state = _fencing_setup(wood=12)
    state = with_house(state, 0, material=HouseMaterial.WOOD)
    state = with_resources(state, 0, wood=12, clay=4, reed=2)
    state = _own(state)
    state = with_resources(
        state, 0, wood=12, clay=4, reed=2,
    )
    # Make farm_redevelopment available.
    from tests.factories import with_space
    state = with_space(state, "farm_redevelopment", revealed=True)
    state = step(state, PlaceWorker(space="farm_redevelopment"))
    state = step(state, ChooseSubAction(name="renovate"))
    state = step(state, CommitRenovate())
    state = step(state, Stop())                                  # pop PendingRenovate
    state = step(state, ChooseSubAction(name="build_fences"))
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, Proceed())                              # flip PBF -> after (grant)
    state = step(state, Stop())                                 # pop PBF
    state = step(state, Proceed())                              # flip FarmRedev -> after
    state = step(state, Stop())                                 # pop FarmRedev
    assert _sheep(state) == 2
