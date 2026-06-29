"""Tests for the Cards deferred-tally build-fence cost path + Hedge Keeper
(occupation A88) — COST_MODIFIER_DESIGN.md §9.2 / increment 2b.

In CARDS mode a Build Fences action does NOT debit wood per pasture commit: each
commit accrues its (post-free) wood onto the `PendingBuildFences` frame, and the
whole-action bill is settled once at the Proceed flip (engine `_settle_build_fences`),
before the after-grants fire. Hedge Keeper seeds a per-action `free_fence_budget`
of 3 (a `before_build_fences` automatic effect) on a LITERAL Build Fences action, so
the first 3 paid edges of the action cost no wood.

These tests drive the REAL fencing flow (the Fencing space), per CARD_AUTHORING_GUIDE
§5, in an explicit CARDS-mode state with Hedge Keeper owned and ample wood (so wood
legality is never the binding constraint — see the KNOWN GAP below).

KNOWN GAP (documented, not fixed here): the during-building legality stays 2a's gross
`can_pay` check — a player whose *gross* wood < edges cannot yet build even when the
free budget would cover the gap. Free-fence-aware legality (the budget *enabling* a
marginal tight-wood build, not merely *discounting* a gross-affordable one) is a
separate follow-up (§9.2 shared-affordability + placement-anticipation). So these
tests give the player ample wood; Hedge Keeper discounts the bill, it doesn't unlock
otherwise-illegal builds.
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.hedge_keeper import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import GameMode
from agricola.engine import step
from agricola.pending import PendingBuildFences
from agricola.replace import fast_replace

from tests.test_fencing import _fencing_setup, _with_initial_pasture


# Top-right pasture shapes (in the default RESTRICTED universe on a fresh farm).
_TOP_1x2_34 = frozenset({(0, 3), (0, 4)})           # new pasture, adjacent to (0,2)
_PRE_1x1 = [(0, 2)]                                  # pre-existing single pasture
_2x3_TR = frozenset({(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)})
_TOP_1x2_subdiv = frozenset({(0, 3), (0, 4)})       # 2-edge subdivision of the 2x3


def _cards_setup(*, wood, own_card=True, pre_pasture=None):
    """A CARDS-mode fencing state: Fencing revealed, ample wood, optionally owning
    Hedge Keeper (in `occupations`, the played tableau — only a played card fires)
    and optionally with a pre-existing pasture."""
    state = _fencing_setup(wood=wood)
    state = fast_replace(state, mode=GameMode.CARDS)
    if pre_pasture is not None:
        state = _with_initial_pasture(state, 0, pre_pasture)
    if own_card:
        p = state.players[0]
        p = fast_replace(p, occupations=p.occupations | {CARD_ID})
        state = fast_replace(
            state, players=tuple(p if i == 0 else state.players[i] for i in range(2))
        )
    return state


def _enter_build_fences(state):
    state = step(state, PlaceWorker(space="fencing"))
    state = step(state, ChooseSubAction(name="build_fences"))
    return state


def _finish(state):
    """Proceed (flips PBF -> after; the CARDS settle pays the accrued bill, then
    the after-autos fire) then drain the two Stops."""
    state = step(state, Proceed())
    state = step(state, Stop())      # pop PendingBuildFences
    state = step(state, Stop())      # pop PendingSubActionSpace
    return state


def _wood(state, idx=0):
    return state.players[idx].resources.wood


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    # No on-play effect (passive cost-discount occupation).
    s = _fencing_setup(wood=1)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


# ---------------------------------------------------------------------------
# The budget is seeded on a literal Build Fences action
# ---------------------------------------------------------------------------

def test_budget_seeded_on_literal_build_fences():
    state = _cards_setup(wood=20)
    state = _enter_build_fences(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildFences)
    assert top.build_fences_action is True
    assert top.free_fence_budget == 3        # Hedge Keeper seeded +3


def test_no_budget_without_card():
    state = _cards_setup(wood=20, own_card=False)
    state = _enter_build_fences(state)
    assert state.pending_stack[-1].free_fence_budget == 0


# ---------------------------------------------------------------------------
# The discount — the spec's worked example: a 5-edge build costs 2 wood (5 - 3)
# ---------------------------------------------------------------------------

def test_five_edge_build_costs_two_wood():
    # Pre-existing 1x1 at (0,2); a new adjacent top 1x2 at (0,3),(0,4) encloses
    # exactly 5 new fence edges. With Hedge Keeper's 3 free, the player pays 2 wood.
    state = _cards_setup(wood=20, pre_pasture=_PRE_1x1)
    assert _wood(state) == 20
    state = _enter_build_fences(state)
    # Mid-action: no debit yet (deferred); the accrued bill is 5 - 3 = 2.
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    top = state.pending_stack[-1]
    assert _wood(state) == 20                 # nothing debited per-commit in CARDS
    assert top.accrued_cost.wood == 2         # 5 edges - 3 free
    assert top.free_fence_budget == 0         # budget consumed
    # Settle at Proceed pays the 2 wood.
    state = _finish(state)
    assert _wood(state) == 18                 # 20 - 2


def test_five_edge_build_full_price_without_card():
    # Same geometry, no Hedge Keeper: the full 5 wood is paid at settle.
    state = _cards_setup(wood=20, own_card=False, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))
    assert state.pending_stack[-1].accrued_cost.wood == 5
    state = _finish(state)
    assert _wood(state) == 15                 # 20 - 5


# ---------------------------------------------------------------------------
# A <=3-edge build is fully covered by the budget — 0 wood
# ---------------------------------------------------------------------------

def test_small_build_costs_zero_wood():
    # Pre-existing 2x3; subdividing off the top 1x2 adds only 2 new edges (<= 3),
    # fully covered by the budget -> 0 wood paid.
    state = _cards_setup(wood=20, pre_pasture=[(0, 3), (0, 4), (1, 3), (1, 4), (2, 3), (2, 4)])
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_subdiv))
    top = state.pending_stack[-1]
    assert top.accrued_cost.wood == 0         # 2 edges, all free
    assert top.free_fence_budget == 1         # 3 - 2
    state = _finish(state)
    assert _wood(state) == 20                 # nothing paid


# ---------------------------------------------------------------------------
# The budget is per-ACTION, applied across multiple commits within one action
# ---------------------------------------------------------------------------

def test_budget_spans_multiple_commits_in_one_action():
    # First commit: a fresh top-right 1x1 ... actually use two adjacent pastures so
    # the budget is consumed across commits. Pre-existing (0,2); commit a top 1x2
    # (5 edges) then a subdivision below is not adjacent; instead build the 1x2 then
    # subdivide it. First commit 5 edges -> 3 free, 2 accrued, budget 0; the second
    # (subdivision, 2 edges) is then fully paid (budget exhausted).
    state = _cards_setup(wood=20, pre_pasture=_PRE_1x1)
    state = _enter_build_fences(state)
    state = step(state, CommitBuildPasture(cells=_TOP_1x2_34))   # 5 edges
    assert state.pending_stack[-1].accrued_cost.wood == 2
    assert state.pending_stack[-1].free_fence_budget == 0
    # A subdivision of the just-built 1x2 (split into two 1x1s) adds new edges, now
    # at full price since the budget is exhausted.
    state = step(state, CommitBuildPasture(cells=frozenset({(0, 3)})))
    top = state.pending_stack[-1]
    sub_edges = top.fences_built - 5
    assert top.accrued_cost.wood == 2 + sub_edges   # 2 (discounted) + full-price subdiv
    state = _finish(state)
    assert _wood(state) == 20 - (2 + sub_edges)
