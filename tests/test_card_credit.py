"""Tests for Credit (minor improvement, A54; Artifex Expansion).

Card text: "When you play this card, you immediately get 5 food. At the end of
each round that does not end with a harvest, you must pay 1 food, or else take
a begging marker."

Free, prereq "At Most 3 Occupations" (max_occupations=3), no VPs, kept. The
on-play grants +5 food. The recurring debt is an AUTO on the round-end ladder's
`end_of_round` rung (ruling 49, 2026-07-12) — mandatory and choice-free
(ruling 21, 2026-07-05): pay 1 food when able, else take a begging marker —
suppressed by the bearer's own condition on the harvest rounds (4/7/9/11/13/14,
whose round end is followed by a harvest).

The round-end tests drive the real walk (`_advance_until_decision` on a drained
WORK state — the tests/test_round_end_ladder.py idiom) so the fire-at-
end_of_round timing is exercised end-to-end, not by calling the effect fns
directly.
"""
from __future__ import annotations

import agricola.cards.credit  # noqa: F401  (registers the card)

import pytest

from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import setup

CARD_ID = "credit"


# ---------------------------------------------------------------------------
# Helpers (the test_round_end_ladder.py idioms)
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    """Put the (played) minor in player `idx`'s tableau."""
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {card_id})


def _set_food(state, idx, food):
    p = state.players[idx]
    return _edit_player(state, idx,
                        resources=fast_replace(p.resources, food=food))


def _drained_work_state(seed=0, round_number=1):
    """A WORK state with every person placed (people_home=0), so the walk runs
    the round-end ladder (WORK segment -> RETURN_HOME segment) to the round
    transition."""
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()            # free card
    assert spec.alt_costs == ()
    assert spec.cost_fn is None
    assert spec.min_occupations == 0
    assert spec.max_occupations == 3      # "At Most 3 Occupations"
    assert spec.prereq is None
    assert spec.passing_left is False
    assert spec.vps == 0


def test_auto_registered_on_end_of_round():
    entries = [e for e in AUTO_EFFECTS.get("end_of_round", ())
               if e.card_id == CARD_ID]
    assert len(entries) == 1
    # Own-window firing: the ladder loop passes each player in turn, so
    # any_player must be False (True would double-fire per owner).
    assert entries[0].any_player is False


# ---------------------------------------------------------------------------
# On-play: +5 food
# ---------------------------------------------------------------------------

def test_on_play_grants_five_food():
    state = setup(0)
    f0 = state.players[0].resources.food
    after = MINORS[CARD_ID].on_play(state, 0)
    assert after.players[0].resources.food == f0 + 5
    # Only the playing player changes.
    assert after.players[1].resources == state.players[1].resources


# ---------------------------------------------------------------------------
# The end-of-round debt, through the real walk (non-harvest round)
# ---------------------------------------------------------------------------

def test_pays_one_food_at_non_harvest_round_end():
    state = _own_minor(_drained_work_state(round_number=1), 0, CARD_ID)
    state = _set_food(state, 0, 4)
    other_food = state.players[1].resources.food
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION      # round 1: no harvest
    assert out.players[0].resources.food == 3  # paid 1 food
    assert out.players[0].begging_markers == 0
    # The non-owner is untouched.
    assert out.players[1].resources.food == other_food
    assert out.players[1].begging_markers == 0


def test_begging_marker_when_no_food():
    state = _own_minor(_drained_work_state(round_number=1), 0, CARD_ID)
    state = _set_food(state, 0, 0)
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION
    assert out.players[0].resources.food == 0       # nothing to pay with
    assert out.players[0].begging_markers == 1      # ...so a begging marker


def test_exactly_one_food_pays_it_no_begging():
    """The pay/beg boundary: at exactly 1 food the payment is made (down to 0),
    never the marker."""
    state = _own_minor(_drained_work_state(round_number=1), 0, CARD_ID)
    state = _set_food(state, 0, 1)
    out = _advance_until_decision(state)
    assert out.players[0].resources.food == 0
    assert out.players[0].begging_markers == 0


# ---------------------------------------------------------------------------
# Harvest rounds: the bearer's own condition suppresses the debt
# ---------------------------------------------------------------------------

def test_not_fired_on_harvest_round_end():
    """Round 4 ends with a harvest: the walk runs the round-end ladder (the
    end_of_round window still opens — ruling 49) and then enters the harvest,
    but Credit's own "does not end with a harvest" condition suppresses the
    debt: no food paid, no begging marker, at the harvest pause (feeding is
    deferred — the FEED frames are pending, nothing debited yet)."""
    state = _own_minor(_drained_work_state(round_number=4), 0, CARD_ID)
    state = _set_food(state, 0, 4)
    out = _advance_until_decision(state)
    # The ladder completed and the harvest began (no fields -> the walk pauses
    # at the FEED decision frames).
    assert out.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)
    assert out.players[0].resources.food == 4
    assert out.players[0].begging_markers == 0


def test_no_begging_marker_on_harvest_round_even_at_zero_food():
    state = _own_minor(_drained_work_state(round_number=4), 0, CARD_ID)
    state = _set_food(state, 0, 0)
    out = _advance_until_decision(state)
    assert out.players[0].begging_markers == 0


# ---------------------------------------------------------------------------
# Ownership gating
# ---------------------------------------------------------------------------

def test_unowned_no_effect():
    state = _drained_work_state(round_number=1)   # nobody owns Credit
    foods = tuple(p.resources.food for p in state.players)
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION
    assert tuple(p.resources.food for p in out.players) == foods
    assert all(p.begging_markers == 0 for p in out.players)


def test_both_players_owning_each_pay_their_own():
    state = _drained_work_state(round_number=1)
    state = _own_minor(state, 0, CARD_ID)
    state = _own_minor(state, 1, CARD_ID)
    state = _set_food(state, 0, 3)
    state = _set_food(state, 1, 0)
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION
    # P0 pays from their own stock; P1 (foodless) takes their own marker.
    assert out.players[0].resources.food == 2
    assert out.players[0].begging_markers == 0
    assert out.players[1].resources.food == 0
    assert out.players[1].begging_markers == 1


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
