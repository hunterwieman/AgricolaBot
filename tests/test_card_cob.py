"""Tests for Cob (minor improvement, A76; Artifex Expansion).

Card text: "At the start of each work phase, if you have at least 1 clay in your
supply, you can exchange exactly 1 grain for 2 clay and 1 food."

Cob is an OPTIONAL start-of-round exchange: at the start of each round (the WORK
phase), if the owner has >= 1 clay AND >= 1 grain, a FireTrigger is surfaced at the
PendingPreparation host that swaps 1 grain for 2 clay + 1 food. The host's Proceed is
the decline path. A `used_this_round` latch makes it fire at most once per round; the
per-round used-set is cleared each round so the option re-arms.

These tests mirror tests/test_cards_preparation_hook.py: they own the minor, push a
PendingPreparation host, and drive real engine actions (FireTrigger / Proceed).
"""
from __future__ import annotations

import agricola.cards.cob  # noqa: F401  (registers the card — not yet in cards/__init__.py)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.triggers import (
    START_OF_ROUND_CARDS,
    owns_start_of_round_card,
    should_host_preparation,
)
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPreparation, push
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
    """An owner-owns-Cob WORK state with a PendingPreparation host on the stack and
    the owner's clay/grain/food set, poised for the start_of_round trigger."""
    state = _own_minor(setup(0), idx)
    state = _set_resources(state, idx, clay=clay, grain=grain, food=food)
    state = fast_replace(state, phase=Phase.WORK)
    return push(state, PendingPreparation(player_idx=idx))


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


def test_registered_on_start_of_round_hook():
    assert CARD_ID in START_OF_ROUND_CARDS
    # A played Cob (in minor_improvements) makes the player a start-of-round owner.
    state = _own_minor(setup(0), 0)
    assert owns_start_of_round_card(state.players[0]) is True
    assert should_host_preparation(state) is True


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
    # The host can now be proceeded (declined onward).
    assert Proceed() in la


def test_proceed_declines_without_changing_resources():
    state = _host_state(0, clay=1, grain=1, food=0)
    before = state.players[0].resources
    state = step(state, Proceed())
    # No exchange applied; PendingPreparation host popped.
    assert state.players[0].resources == before
    assert all(not isinstance(f, PendingPreparation) for f in state.pending_stack)


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_without_clay():
    # The verbatim "at least 1 clay" gate — even though the swap GIVES clay.
    state = _host_state(0, clay=0, grain=3, food=0)
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in la
    # No mandatory trigger, so Proceed is offered (the host can resolve).
    assert Proceed() in la


def test_not_offered_without_grain():
    # Must have at least 1 grain to spend.
    state = _host_state(0, clay=2, grain=0, food=0)
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert Proceed() in la


def test_offered_at_exact_minimum():
    state = _host_state(0, clay=1, grain=1, food=0)
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in la


def test_not_offered_for_non_owner():
    # Player 1 does NOT own Cob; only player 0's host can fire it.
    state = _own_minor(setup(0), 0)
    state = _set_resources(state, 1, clay=2, grain=2, food=0)
    state = fast_replace(state, phase=Phase.WORK)
    state = push(state, PendingPreparation(player_idx=1))
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in la
