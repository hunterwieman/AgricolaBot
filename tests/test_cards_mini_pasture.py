"""Mini Pasture (minor B2): a restricted, free, MANDATORY 1×1 new-enclosure grant
(COST_MODIFIER_DESIGN.md §9.8)."""
from __future__ import annotations

from agricola.actions import CommitBuildPasture, Proceed, Stop
from agricola.cards.mini_pasture import CARD_ID
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBuildFences
from agricola.replace import fast_replace
from agricola.resources import Resources

from tests.test_fencing import _fencing_setup, _with_initial_pasture

_2x3 = [(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)]


def _cards(*, supply=None, pre_pasture=None):
    """Cards-mode fencing state with 0 wood (so a build is only possible if free). `supply`
    overrides the fence-supply pile; `pre_pasture` enclosing fences are placed first (which
    sets the supply to 15 - built consistently)."""
    state = fast_replace(_fencing_setup(wood=0), mode=GameMode.CARDS)
    if pre_pasture is not None:
        state = _with_initial_pasture(state, 0, pre_pasture)
    if supply is not None:
        p = fast_replace(state.players[0], fences_in_supply=supply)
        state = fast_replace(state, players=tuple(
            p if i == 0 else state.players[i] for i in range(2)))
    return state


def _supply(s, i=0): return s.players[i].fences_in_supply
def _wood(s, i=0): return s.players[i].resources.wood
def _play(s, i=0): return MINORS[CARD_ID].on_play(s, i)


# ---------------------------------------------------------------------------
# Registration + cost
# ---------------------------------------------------------------------------

def test_registration_cost():
    assert MINORS[CARD_ID].cost.resources == Resources(food=2)


# ---------------------------------------------------------------------------
# Playability prereq (mandatory: unplayable if no free 1×1 can be built)
# ---------------------------------------------------------------------------

def test_prereq_playable_on_fresh_farm():
    assert prereq_met(MINORS[CARD_ID], _cards(), 0)            # a first 1×1 is buildable


def test_prereq_unplayable_with_no_fences_in_supply():
    assert not prereq_met(MINORS[CARD_ID], _cards(supply=0), 0)   # no pieces -> can't fence


def test_prereq_unplayable_with_one_fence_left_but_1x1_needs_more():
    # A fresh 1×1 needs 4 edges; with only 1 fence piece in supply and no existing pasture to
    # share edges with, no 1×1 is buildable -> unplayable.
    assert not prereq_met(MINORS[CARD_ID], _cards(supply=1), 0)


# ---------------------------------------------------------------------------
# The grant: a free 1×1, mandatory, exactly one
# ---------------------------------------------------------------------------

def test_on_play_pushes_restricted_free_grant():
    s = _play(_cards())
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    assert top.build_fences_action is False           # a card effect, not the literal action
    assert top.free_fence_budget == 4                 # the whole 1×1 is free
    assert top.restrictions.exact_size == 1 and top.restrictions.max_pastures == 1


def test_grant_offers_only_1x1_commits():
    s = _play(_cards())
    commits = [a for a in legal_actions(s) if isinstance(a, CommitBuildPasture)]
    assert commits and all(len(a.cells) == 1 for a in commits)   # only 1×1's


def test_build_is_free_and_uses_supply_pieces():
    s = _play(_cards())                                # fresh: supply 15
    s = step(s, CommitBuildPasture(cells=frozenset({(1, 1)})))   # a fresh 1×1 = 4 edges
    top = s.pending_stack[-1]
    assert top.accrued_cost.wood == 0                  # no wood (free)
    assert _supply(s) == 15 - 4                         # 4 fence PIECES drawn from supply
    assert top.pastures_built == 1
    # max_pastures=1 -> no further commits, only Proceed.
    nxt = legal_actions(s)
    assert not any(isinstance(a, CommitBuildPasture) for a in nxt)
    assert any(isinstance(a, Proceed) for a in nxt)
    s = step(s, Proceed())                             # settle 0
    assert _wood(s) == 0                                # nothing paid


def test_only_new_enclosures_never_subdivisions():
    # Pre-existing 2×3 (subdivisions are geometrically possible). Mini Pasture offers only NEW
    # adjacent 1×1 enclosures, never a 1×1 subdivision of the 2×3.
    s = _play(_cards(pre_pasture=_2x3))
    commits = {a.cells for a in legal_actions(s) if isinstance(a, CommitBuildPasture)}
    assert all(len(c) == 1 for c in commits)
    assert frozenset({(0, 3)}) not in commits          # a cell INSIDE the 2×3 -> a subdivision, excluded
    assert frozenset({(0, 2)}) in commits              # a new 1×1 adjacent to the 2×3 -> offered
