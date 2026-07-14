"""Tests for Cob (minor improvement, A76; Artifex Expansion).

Card text: "At the start of each work phase, if you have at least 1 clay in your
supply, you can exchange exactly 1 grain for 2 clay and 1 food."

"At the start of each work phase" is the preparation ladder's `start_of_work`
window (ruling 54, 2026-07-14) — the ladder's last rung, after replenishment and
distinct from `start_of_round`. Cob is an OPTIONAL exchange there: when the owner
has >= 1 clay AND >= 1 grain, the walk pushes a `PendingHarvestWindow` choice
frame (window_id="start_of_work") surfacing a FireTrigger that swaps 1 grain for
2 clay + 1 food; the frame's Proceed is the decline path, and resolving it resumes
the walk into WORK. When the trigger is not eligible, NO frame is pushed at all —
the ladder completes straight into WORK. A `used_this_round` latch makes it fire
at most once per round; the per-round used-set is cleared at round entry, so the
option re-arms each round.

These tests drive the real round boundary: they own the minor, run
`_complete_preparation` (the whole ladder), and step real engine actions
(FireTrigger / Proceed).
"""
from __future__ import annotations

import agricola.cards.cob  # noqa: F401  (registers the card — not yet in cards/__init__.py)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup


CARD_ID = "cob"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_resources(state, idx, **kw):
    p = state.players[idx]
    p = fast_replace(p, resources=fast_replace(p.resources, **kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _host_state(idx=0, *, clay=1, grain=1, food=0):
    """Run the real preparation ladder into round 2 with player `idx` owning Cob
    and the given clay/grain/food. When Cob's trigger is eligible the returned
    state is paused at the `start_of_work` window — a PendingHarvestWindow frame
    for the owner, phase still PREPARATION; otherwise the ladder has completed
    into WORK with an empty stack."""
    state = _own_minor(setup(0), idx)
    state = _set_resources(state, idx, clay=clay, grain=grain, food=food)
    state = fast_replace(state, round_number=1, phase=Phase.PREPARATION)
    return _complete_preparation(state)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.prereq is None


def test_registered_on_start_of_work_window():
    # "At the start of each work phase" → an OPTIONAL trigger on the ladder's
    # start_of_work window (not the start_of_round window, and not a forced auto).
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("start_of_work", ())}
    assert CARD_ID not in {e.card_id for e in AUTO_EFFECTS.get("start_of_work", ())}
    assert CARD_ID not in {e.card_id for e in TRIGGERS.get("start_of_round", ())}


def test_eligible_owner_gets_window_frame():
    # An eligible owner pauses the preparation walk at the start_of_work window.
    state = _host_state(0, clay=1, grain=1, food=0)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "start_of_work" and top.player_idx == 0
    assert state.phase == Phase.PREPARATION   # the frame is up mid-ladder


# ---------------------------------------------------------------------------
# The effect via a real engine flow
# ---------------------------------------------------------------------------

def test_fire_performs_the_exchange():
    state = _host_state(0, clay=2, grain=3, food=0)
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la  # optional

    before = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID))
    after = state.players[0].resources
    # −1 grain, +2 clay, +1 food.
    assert after.grain == before.grain - 1
    assert after.clay == before.clay + 2
    assert after.food == before.food + 1


def test_fire_latches_used_this_round_once():
    state = _host_state(0, clay=1, grain=2, food=0)
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert CARD_ID in state.players[0].used_this_round
    # Even though the player still has clay+grain, the trigger is no longer offered.
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in la
    # The window frame can now be resolved onward (declined).
    assert Proceed() in la


def test_proceed_declines_without_changing_resources():
    state = _host_state(0, clay=1, grain=1, food=0)
    before = state.players[0].resources
    state = step(state, Proceed())
    # No exchange applied; the window frame popped and the ladder completed.
    assert state.players[0].resources == before
    assert state.pending_stack == ()
    assert state.phase == Phase.WORK


# ---------------------------------------------------------------------------
# Eligibility boundaries — an ineligible trigger pushes NO frame at all
# ---------------------------------------------------------------------------

def test_not_offered_without_clay():
    # The verbatim "at least 1 clay" gate — even though the swap GIVES clay.
    # No eligible trigger → no window frame; the ladder completes into WORK.
    state = _host_state(0, clay=0, grain=3, food=0)
    assert state.pending_stack == ()
    assert state.phase == Phase.WORK
    assert state.players[0].resources.grain == 3   # no exchange happened


def test_not_offered_without_grain():
    # Must have at least 1 grain to spend.
    state = _host_state(0, clay=2, grain=0, food=0)
    assert state.pending_stack == ()
    assert state.phase == Phase.WORK
    assert state.players[0].resources.clay == 2    # no exchange happened


def test_offered_at_exact_minimum():
    state = _host_state(0, clay=1, grain=1, food=0)
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in la


def test_not_offered_for_non_owner():
    # Player 1 does NOT own Cob: an eligible-looking supply gets them no frame —
    # only the owner's (player 0's) frame surfaces the trigger.
    state = _own_minor(setup(0), 0)
    state = _set_resources(state, 0, clay=1, grain=1, food=0)
    state = _set_resources(state, 1, clay=2, grain=2, food=0)
    state = fast_replace(state, round_number=1, phase=Phase.PREPARATION)
    state = _complete_preparation(state)
    assert [f.player_idx for f in state.pending_stack
            if isinstance(f, PendingHarvestWindow)] == [0]
    # Resolving the owner's frame ends the ladder — P1 is never offered anything.
    state = step(state, Proceed())
    assert state.pending_stack == ()
    assert state.phase == Phase.WORK
