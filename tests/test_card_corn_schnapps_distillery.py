"""Tests for Corn Schnapps Distillery (minor improvement, C64; Corbarius Expansion).

Card text: "Once per round, you can pay 1 grain to place 1 food on each of the next 4
round spaces. At the start of these rounds, you get the food."
Cost: 1 Wood, 2 Clay. VPs: 1. Not passing.

An OPTIONAL, once-per-round paid start_of_round grant: at the start of each round (a
PendingPreparation host on the WORK stack) the owner may pay 1 grain to schedule 1 food
onto each of the next 4 round spaces (rounds R+1..R+4), collected at the start of each of
those rounds via `_complete_preparation`'s future_resources distribution. The host's
Proceed is the decline path; a `used_this_round` latch makes it fire at most once per
round (the per-round used-set is cleared each round so it re-arms).

These tests mirror tests/test_card_cob.py (the start_of_round FireTrigger/Proceed flow +
latch + eligibility boundaries) and tests/test_card_trellises.py (the future_resources
slot scheduling + the end-to-end _complete_preparation round-start collection).
"""
from __future__ import annotations

import agricola.cards.corn_schnapps_distillery  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.specs import MINORS
from agricola.cards.triggers import (
    START_OF_ROUND_CARDS,
    TRIGGERS,
    owns_start_of_round_card,
    should_host_preparation,
)
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingPreparation, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup


CARD_ID = "corn_schnapps_distillery"


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


def _host_state(idx=0, *, grain=1, round_number=1):
    """An owner-owns-the-card WORK state with a PendingPreparation host on the stack
    and the owner's grain set, poised for the start_of_round trigger."""
    state = _own_minor(setup(0), idx)
    state = fast_replace(state, round_number=round_number)
    state = _set_resources(state, idx, grain=grain)
    state = fast_replace(state, phase=Phase.WORK)
    return push(state, PendingPreparation(player_idx=idx))


def _food_slots(state, idx):
    return [r.food for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1, clay=2))
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.prereq is None


def test_registered_on_start_of_round_hook():
    assert CARD_ID in START_OF_ROUND_CARDS
    # Registered as an OPTIONAL (declinable) start_of_round trigger, not an automatic.
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("start_of_round", [])}
    entry = next(e for e in TRIGGERS["start_of_round"] if e.card_id == CARD_ID)
    assert entry.mandatory is False
    # A played card (in minor_improvements) makes the player a start-of-round owner.
    state = _own_minor(setup(0), 0)
    assert owns_start_of_round_card(state.players[0]) is True
    assert should_host_preparation(state) is True


# ---------------------------------------------------------------------------
# The effect via a real engine flow
# ---------------------------------------------------------------------------

def test_fire_pays_grain_and_schedules_food():
    state = _host_state(0, grain=2, round_number=1)
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la  # optional

    before_grain = state.players[0].resources.grain
    state = step(state, FireTrigger(card_id=CARD_ID))

    # −1 grain.
    assert state.players[0].resources.grain == before_grain - 1
    # +1 food scheduled onto the NEXT 4 round spaces (rounds 2,3,4,5), not the current.
    f = _food_slots(state, 0)
    assert f[0] == 0                          # round 1 (current) untouched
    assert f[1] == f[2] == f[3] == f[4] == 1  # rounds 2,3,4,5
    assert f[5] == 0                          # round 6 not scheduled
    assert sum(f) == 4


def test_schedule_clamps_past_round_14():
    # Round 12 → next 4 are rounds 13,14 (15,16 dropped by the 1..14 slot clamp).
    state = _host_state(0, grain=1, round_number=12)
    state = step(state, FireTrigger(card_id=CARD_ID))
    f = _food_slots(state, 0)
    assert f[12] == 1 and f[13] == 1          # rounds 13, 14
    assert sum(f) == 2                         # only 2 remaining round spaces


def test_fire_latches_used_this_round_once():
    state = _host_state(0, grain=3, round_number=1)
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert CARD_ID in state.players[0].used_this_round
    # Even with grain remaining, the trigger is no longer offered this round.
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert Proceed() in la                     # the host can now be declined onward


def test_proceed_declines_without_changing_resources():
    state = _host_state(0, grain=2, round_number=1)
    before = state.players[0].resources
    before_slots = _food_slots(state, 0)
    state = step(state, Proceed())
    # No payment, no scheduling; PendingPreparation host popped.
    assert state.players[0].resources == before
    assert _food_slots(state, 0) == before_slots
    assert all(not isinstance(f, PendingPreparation) for f in state.pending_stack)


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_without_grain():
    state = _host_state(0, grain=0, round_number=1)
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in la
    # No mandatory trigger, so Proceed is offered (the host can resolve).
    assert Proceed() in la


def test_offered_at_exact_minimum_grain():
    state = _host_state(0, grain=1, round_number=1)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)


def test_not_offered_for_non_owner():
    # Player 1 does NOT own the card; only player 0's host can fire it.
    state = _own_minor(setup(0), 0)
    state = _set_resources(state, 1, grain=3)
    state = fast_replace(state, phase=Phase.WORK)
    state = push(state, PendingPreparation(player_idx=1))
    la = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in la


# ---------------------------------------------------------------------------
# Latch re-arms next round (scoping)
# ---------------------------------------------------------------------------

def test_latch_resets_next_round():
    # Fire in round 1, then advance: _complete_preparation clears used_this_round
    # before surfacing the start_of_round trigger again.
    state = _host_state(0, grain=2, round_number=1)
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert CARD_ID in state.players[0].used_this_round
    # Resolve the host, then advance into round 2 via _complete_preparation.
    state = step(state, Proceed())
    state = fast_replace(state, round_number=1, phase=Phase.PREPARATION)
    state = _complete_preparation(state)
    assert state.round_number == 2
    # The per-round latch is cleared for the new round.
    assert CARD_ID not in state.players[0].used_this_round


# ---------------------------------------------------------------------------
# End-to-end: the scheduled food is collected at the start of each scheduled round
# ---------------------------------------------------------------------------

def test_scheduled_food_collected_at_round_start():
    state = _host_state(0, grain=1, round_number=1)
    state = step(state, FireTrigger(card_id=CARD_ID))   # schedules food on rounds 2..5
    state = step(state, Proceed())                      # resolve the host

    food_before = state.players[0].resources.food
    prep = fast_replace(state, round_number=1, phase=Phase.PREPARATION)
    prep = _complete_preparation(prep)
    while prep.pending_stack:                            # resolve the reveal nature step
        prep = step(prep, legal_actions(prep)[0])
    assert prep.round_number == 2
    # The round-2 slot pays out 1 food at the start of round 2.
    assert prep.players[0].resources.food == food_before + 1
