"""Tests for Informant (occupation, deck B #117; Bubulcus Expansion).

Card text: "When you play this card, you immediately get 1 wood. After each
work phase, if you have more stone than clay in your supply, you get 1 wood."

The on-play grants +1 wood. The recurring grant is an AUTO on the round-end
ladder's `after_work` rung (user ruling 2026-07-14: "after each work phase" =
ruling 50's separate `after_work` rung, glossed "immediately before the
returning home phase" — confirmed merged for this card), eligible when the
owner's supply holds strictly more stone than clay at that instant.

The round-end tests drive the real walk (`_advance_until_decision` on a
drained WORK state — the tests/test_round_end_ladder.py idiom, as used by
test_card_credit.py) so the fire-at-after_work timing is exercised end-to-end,
not by calling the effect fns directly. The ladder runs unconditioned on
harvest rounds too (the round end precedes the harvest), so the grant fires
there as well — pinned below.
"""
from __future__ import annotations

import agricola.cards.informant  # noqa: F401  (registers the card)

import pytest

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision
from agricola.replace import fast_replace
from agricola.setup import setup

CARD_ID = "informant"


# ---------------------------------------------------------------------------
# Helpers (the test_round_end_ladder.py / test_card_credit.py idioms)
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occupation(state, idx, card_id):
    """Put the (played) occupation in player `idx`'s tableau."""
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {card_id})


def _hand_occupation(state, idx, card_id):
    """Put the occupation in player `idx`'s HAND (unplayed)."""
    p = state.players[idx]
    return _edit_player(state, idx,
                        hand_occupations=p.hand_occupations | {card_id})


def _set_supply(state, idx, *, stone, clay):
    p = state.players[idx]
    return _edit_player(state, idx,
                        resources=fast_replace(p.resources, stone=stone, clay=clay))


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
    assert CARD_ID in OCCUPATIONS


def test_auto_registered_on_after_work():
    entries = [e for e in AUTO_EFFECTS.get("after_work", ())
               if e.card_id == CARD_ID]
    assert len(entries) == 1
    # Own-window firing: the ladder loop passes each player in turn, so
    # any_player must be False (True would double-fire per owner).
    assert entries[0].any_player is False


# ---------------------------------------------------------------------------
# On-play: +1 wood
# ---------------------------------------------------------------------------

def test_on_play_grants_one_wood():
    state = setup(0)
    w0 = state.players[0].resources.wood
    after = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert after.players[0].resources.wood == w0 + 1
    # Only the playing player changes.
    assert after.players[1].resources == state.players[1].resources


# ---------------------------------------------------------------------------
# The after-work grant, through the real walk (non-harvest round)
# ---------------------------------------------------------------------------

def test_gets_wood_when_more_stone_than_clay():
    state = _own_occupation(_drained_work_state(round_number=1), 0, CARD_ID)
    state = _set_supply(state, 0, stone=2, clay=1)
    w0 = state.players[0].resources.wood
    other = state.players[1].resources
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION      # round 1: no harvest
    assert out.players[0].resources.wood == w0 + 1
    # The supply itself is only a HAVE-check — nothing spent.
    assert out.players[0].resources.stone == 2
    assert out.players[0].resources.clay == 1
    # The non-owner is untouched.
    assert out.players[1].resources == other


def test_nothing_when_stone_equals_clay():
    state = _own_occupation(_drained_work_state(round_number=1), 0, CARD_ID)
    state = _set_supply(state, 0, stone=2, clay=2)
    w0 = state.players[0].resources.wood
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION
    assert out.players[0].resources.wood == w0     # equal does not qualify


def test_nothing_when_less_stone_than_clay():
    state = _own_occupation(_drained_work_state(round_number=1), 0, CARD_ID)
    state = _set_supply(state, 0, stone=0, clay=3)
    w0 = state.players[0].resources.wood
    out = _advance_until_decision(state)
    assert out.players[0].resources.wood == w0


def test_one_stone_zero_clay_qualifies():
    """The boundary from below: 1 stone vs 0 clay is strictly more."""
    state = _own_occupation(_drained_work_state(round_number=1), 0, CARD_ID)
    state = _set_supply(state, 0, stone=1, clay=0)
    w0 = state.players[0].resources.wood
    out = _advance_until_decision(state)
    assert out.players[0].resources.wood == w0 + 1


# ---------------------------------------------------------------------------
# Fires each qualifying round — no once-per-game latch
# ---------------------------------------------------------------------------

def test_fires_again_in_a_later_round():
    for rnd in (1, 2):
        state = _own_occupation(_drained_work_state(round_number=rnd), 0, CARD_ID)
        state = _set_supply(state, 0, stone=3, clay=0)
        w0 = state.players[0].resources.wood
        out = _advance_until_decision(state)
        assert out.players[0].resources.wood == w0 + 1


def test_fires_on_harvest_round_too():
    """Round 4 ends with a harvest, but the round-end ladder runs before the
    harvest and Informant's text has no harvest condition — the grant fires."""
    state = _own_occupation(_drained_work_state(round_number=4), 0, CARD_ID)
    state = _set_supply(state, 0, stone=2, clay=0)
    w0 = state.players[0].resources.wood
    out = _advance_until_decision(state)
    # The ladder completed and the harvest began (the walk pauses at the
    # harvest decision frames).
    assert out.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)
    assert out.players[0].resources.wood == w0 + 1


# ---------------------------------------------------------------------------
# Ownership gating
# ---------------------------------------------------------------------------

def test_unowned_no_effect():
    state = _drained_work_state(round_number=1)   # nobody owns Informant
    state = _set_supply(state, 0, stone=5, clay=0)
    woods = tuple(p.resources.wood for p in state.players)
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION
    assert tuple(p.resources.wood for p in out.players) == woods


def test_hand_only_is_inert():
    """A card still in HAND fires nothing, even with a qualifying supply."""
    state = _hand_occupation(_drained_work_state(round_number=1), 0, CARD_ID)
    state = _set_supply(state, 0, stone=5, clay=0)
    w0 = state.players[0].resources.wood
    out = _advance_until_decision(state)
    assert out.players[0].resources.wood == w0


def test_both_players_owning_each_fire_on_own_supply():
    state = _drained_work_state(round_number=1)
    state = _own_occupation(state, 0, CARD_ID)
    state = _own_occupation(state, 1, CARD_ID)
    state = _set_supply(state, 0, stone=2, clay=1)   # qualifies
    state = _set_supply(state, 1, stone=1, clay=1)   # does not
    w0 = state.players[0].resources.wood
    w1 = state.players[1].resources.wood
    out = _advance_until_decision(state)
    assert out.phase == Phase.PREPARATION
    assert out.players[0].resources.wood == w0 + 1
    assert out.players[1].resources.wood == w1


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
