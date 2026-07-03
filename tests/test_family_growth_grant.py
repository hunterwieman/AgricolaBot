"""Tests for the card-granted family growth path (Group A1):
PendingFamilyGrowth.place_on_space=False.

User ruling (CARD_DEFERRED_PLANS.md Group A1): a card-granted "Family Growth"
places the newborn on NO action space — unlike the wish spaces, where the newborn
meeple visibly joins the parent's space. The primitive's card-grant path
increments people_total/newborns for the frame's owner and leaves the board
untouched; the room gate is the caller's eligibility concern. Unlocks Autumn
Mother (C92) and Bed in the Grain Field (C24).
"""
from agricola.actions import CommitFamilyGrowth, Stop
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingFamilyGrowth
from agricola.setup import setup

from tests.factories import with_pending_stack, with_phase


def _grant_state(idx=1, seed=0):
    """A WORK state with a card-granted growth frame for player `idx` on top."""
    state = with_phase(setup(seed), Phase.WORK)
    frame = PendingFamilyGrowth(
        player_idx=idx,
        initiated_by_id="card:_test_growth_grant",
        place_on_space=False,
    )
    return with_pending_stack(state, [frame])


def test_grant_growth_increments_without_board_placement():
    state = _grant_state(idx=1)
    before_p = state.players[1]
    before_workers = tuple(sp.workers for sp in state.board.action_spaces)

    assert legal_actions(state) == [CommitFamilyGrowth()]
    state = step(state, CommitFamilyGrowth())

    after_p = state.players[1]
    assert after_p.people_total == before_p.people_total + 1
    assert after_p.newborns == before_p.newborns + 1
    assert after_p.people_home == before_p.people_home  # newborn is not "home help"
    # No meeple landed anywhere.
    assert tuple(sp.workers
                 for sp in state.board.action_spaces) == before_workers


def test_grant_growth_credits_the_frame_owner_not_current_player():
    # The frame belongs to player 1 while current_player is forced to 0 —
    # the decider rule: the frame's owner, not the active player, is credited.
    from agricola.replace import fast_replace
    state = fast_replace(_grant_state(idx=1), current_player=0)
    p0_before = state.players[0].people_total
    state = step(state, CommitFamilyGrowth())
    assert state.players[0].people_total == p0_before
    assert state.players[1].newborns == 1


def test_grant_growth_flips_to_after_then_stop_pops():
    state = step(_grant_state(idx=0), CommitFamilyGrowth())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFamilyGrowth) and top.phase == "after"
    assert Stop() in legal_actions(state)
    state = step(state, Stop())
    assert not any(isinstance(f, PendingFamilyGrowth) for f in state.pending_stack)


def test_default_space_path_unchanged():
    """The wish-space default (place_on_space=True) still places the newborn on
    the named space — the pre-A1 behavior, exercised via the frame directly."""
    state = with_phase(setup(0), Phase.WORK)
    frame = PendingFamilyGrowth(
        player_idx=state.current_player,
        initiated_by_id="basic_wish_for_children",
    )
    state = with_pending_stack(state, [frame])
    from agricola.state import get_space
    before = get_space(state.board, "basic_wish_for_children").workers
    state = step(state, CommitFamilyGrowth())
    after = get_space(state.board, "basic_wish_for_children").workers
    assert sum(after) == sum(before) + 1
