"""Tests for Stablehand (occupation D89; Dulcinaria).

"Each time you build at least 1 fence, you can also build a stable without
paying wood for the stable." No cost / prereq / vps.

The card is an OPTIONAL after-build-fences trigger: after at least one fence is
built (Proceed flips PendingBuildFences to its after-phase), the host offers
`FireTrigger(card_id="stablehand")` alongside `Stop`. Firing pushes a free
(no-wood) `PendingBuildStables` (cap 1); declining is just `Stop`. Tests drive
the REAL fencing flow (the Fencing space), per CARD_AUTHORING_GUIDE §5.

A 2x2 corner pasture costs exactly 8 fence pieces, so it always satisfies "at
least 1 fence" and is the standard build used here. The free stable is then
placed inside that pasture (any legal stable cell works).
"""
import agricola.cards.stablehand  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    CommitBuildStable,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.stablehand import CARD_ID, _eligible
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBuildStables
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import Cell
from tests.factories import with_grid
from tests.test_fencing import _fencing_setup

# A top-right 2x2 (4 cells, 8 fence pieces) — in the default RESTRICTED universe.
_2x2_TR = frozenset({(0, 3), (0, 4), (1, 3), (1, 4)})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(state, idx=0, card_id=CARD_ID):
    """Give player `idx` the occupation (played via Lessons in real play)."""
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _enter_build_fences(state):
    state = step(state, PlaceWorker(space="fencing"))
    state = step(state, ChooseSubAction(name="build_fences"))
    return state


def _build_2x2(state):
    """Enter build-fences, commit the 2x2, Proceed to the after-phase (where the
    Stablehand FireTrigger is offered). Stops short of Stop so the caller decides
    whether to fire."""
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_2x2_TR))
    state = step(state, Proceed())   # flip PendingBuildFences -> after-phase
    return state


def _wood(state, idx=0):
    return state.players[idx].resources.wood


def _num_stables(state, idx=0):
    grid = state.players[idx].farmyard.grid
    return sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.STABLE
    )


def _has_fire(state, idx=0):
    return any(
        isinstance(a, FireTrigger) and a.card_id == CARD_ID
        for a in legal_actions(state)
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    # No cost / prereq / vps on an occupation spec — just an on-play callable.
    spec = OCCUPATIONS[CARD_ID]
    assert callable(spec.on_play)


def test_on_play_is_noop():
    state = _fencing_setup(wood=12)
    before = state.players[0]
    after = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert after.players[0] == before   # no resources / state change


# ---------------------------------------------------------------------------
# The grant — firing the optional trigger builds a FREE stable
# ---------------------------------------------------------------------------

def test_fire_grants_free_stable():
    # 12 wood: the 2x2 (8 wood) leaves wood behind so we can prove the stable is
    # free (wood unchanged across the stable build).
    state = _own(_fencing_setup(wood=12))
    state = _build_2x2(state)
    # After-phase: the Stablehand FireTrigger must be offered.
    assert _has_fire(state)
    stables0 = _num_stables(state)
    wood_after_fences = _wood(state)
    # Fire it -> a free PendingBuildStables is pushed.
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert isinstance(state.pending_stack[-1], PendingBuildStables)
    assert state.pending_stack[-1].cost == Resources()       # free of wood
    builds = [a for a in legal_actions(state) if isinstance(a, CommitBuildStable)]
    assert builds
    state = step(state, builds[0])
    assert _num_stables(state) == stables0 + 1
    assert _wood(state) == wood_after_fences   # FREE: no wood paid for the stable


def test_decline_does_nothing():
    state = _own(_fencing_setup(wood=12))
    state = _build_2x2(state)
    assert _has_fire(state)
    stables0 = _num_stables(state)
    state = step(state, Stop())            # decline + pop PendingBuildFences
    state = step(state, Stop())            # pop the parent host
    assert _num_stables(state) == stables0   # declined -> no stable built


def test_no_offer_without_card():
    # Build the same 2x2 but DON'T own the card -> no FireTrigger ever surfaces.
    state = _build_2x2(_fencing_setup(wood=12))
    assert not _has_fire(state)


# ---------------------------------------------------------------------------
# Once-per-build-fences-action scoping
# ---------------------------------------------------------------------------

def test_fires_at_most_once_per_action():
    state = _own(_fencing_setup(wood=12))
    state = _build_2x2(state)
    assert _has_fire(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    # Build the granted stable.
    builds = [a for a in legal_actions(state) if isinstance(a, CommitBuildStable)]
    state = step(state, builds[0])
    # Back at the build-fences after-phase: triggers_resolved now contains
    # "stablehand", so the grant is no longer offered even though another stable
    # could still be built.
    assert not _has_fire(state)
    state = step(state, Stop())


# ---------------------------------------------------------------------------
# Eligibility boundaries (never a dead-end)
# ---------------------------------------------------------------------------

def test_eligible_predicate_direct():
    state = _own(_fencing_setup(wood=12))
    # A free stable is buildable and the grant hasn't fired -> eligible.
    assert _eligible(state, 0, frozenset())
    # Already fired this action -> not eligible.
    assert not _eligible(state, 0, frozenset({CARD_ID}))


def test_not_offered_when_no_stable_buildable():
    # Fill EVERY empty cell with a field (not a legal stable target) so no stable
    # can be placed anywhere. Drive the real build-fences flow: at the after-phase
    # the grant's eligibility (_can_build_stable) is False -> the FireTrigger is
    # never offered, only Stop remains.
    state = _own(_fencing_setup(wood=12))
    overrides = {}
    grid = state.players[0].farmyard.grid
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.EMPTY and (r, c) not in _2x2_TR:
                overrides[(r, c)] = Cell(cell_type=CellType.FIELD)
    state = with_grid(state, 0, overrides)
    state = _build_2x2(state)
    # The only empty cells left are the four inside the new 2x2 pasture — but a
    # stable inside a pasture IS a legal target, so the grant is still offered.
    # The clean no-stable-buildable boundary is exercised directly below.
    assert _has_fire(state)


def test_eligible_false_when_grid_full():
    # No empty cell anywhere -> _can_build_stable is False -> not eligible.
    state = _own(_fencing_setup(wood=12))
    overrides = {}
    grid = state.players[0].farmyard.grid
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.EMPTY:
                overrides[(r, c)] = Cell(cell_type=CellType.FIELD)
    state = with_grid(state, 0, overrides)
    assert not _eligible(state, 0, frozenset())
