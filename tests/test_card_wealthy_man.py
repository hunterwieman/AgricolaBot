"""Tests for Wealthy Man (occupation D153).

Card text: "At the start of each of the 1st/2nd/3rd/4th/5th/6th harvest, if you have
at least 1/2/3/4/5/6 grain fields, you get 1 bonus point."

A `start_of_harvest` automatic effect: at harvest N (rounds 4/7/9/11/13/14) the owner
banks 1 point if they have at least N grain fields, accumulating across the game.
Tests drive real harvests (the dentist harvest-walk idiom) at specific rounds and
cover the rising threshold per ordinal, accumulation, round-keying, owner-gating, the
ordinal mapping, and scoring readback.
"""
import dataclasses

import agricola.cards.wealthy_man  # noqa: F401  (registers the card)

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.wealthy_man import CARD_ID, _HARVEST_ORDINAL
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup

from tests.factories import with_phase, with_round, with_sown_fields


def _own(state, idx):
    return fast_replace(state, players=tuple(
        fast_replace(state.players[i], occupations=state.players[i].occupations | {CARD_ID})
        if i == idx else state.players[i] for i in range(2)))


def _harvest_state(round_number, food=10):
    """A HARVEST_FIELD-phase state at a specific (harvest) round, feeding painless."""
    state = with_round(with_phase(setup(0), Phase.HARVEST_FIELD), round_number)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i], resources=fast_replace(
                state.players[i].resources, food=food))
            if i == idx else state.players[i] for i in range(2)))
    return state


def _run_harvest(state):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        state = step(state, legal_actions(state)[0])
    return state


def _banked(state, idx):
    return state.players[idx].card_state.get(CARD_ID, (0, 0))[1]


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration + the ordinal mapping -------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("start_of_harvest", ())}
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("start_of_harvest", set())
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_on_play_is_noop():
    s = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) == s


def test_ordinal_mapping():
    # The 1st..6th harvests fall on rounds 4/7/9/11/13/14.
    assert _HARVEST_ORDINAL == {4: 1, 7: 2, 9: 3, 11: 4, 13: 5, 14: 6}


# --- The rising threshold per harvest ordinal -------------------------------

def test_first_harvest_one_grain_field_banks():
    s = _own(_harvest_state(4), 0)
    s = with_sown_fields(s, 0, grain_fields=[(0, 0)])       # 1 grain field, needs 1
    out = _run_harvest(s)
    assert _banked(out, 0) == 1


def test_first_harvest_no_grain_field_no_bank():
    s = _own(_harvest_state(4), 0)                          # 0 grain fields
    out = _run_harvest(s)
    assert _banked(out, 0) == 0


def test_second_harvest_needs_two_grain_fields():
    # Round 7 = 2nd harvest -> threshold 2.
    s = _own(_harvest_state(7), 0)
    s = with_sown_fields(s, 0, grain_fields=[(0, 0)])       # only 1 -> no bank
    assert _banked(_run_harvest(s), 0) == 0

    s = _own(_harvest_state(7), 0)
    s = with_sown_fields(s, 0, grain_fields=[(0, 0), (0, 1)])   # 2 -> bank
    assert _banked(_run_harvest(s), 0) == 1


def test_veg_fields_do_not_count():
    """Only GRAIN fields count toward the threshold."""
    s = _own(_harvest_state(4), 0)
    s = with_sown_fields(s, 0, veg_fields=[(0, 0), (0, 1)])   # veg, not grain
    assert _banked(_run_harvest(s), 0) == 0


# --- Accumulation + round-keying --------------------------------------------

def test_accumulates_across_harvests():
    s = _own(_harvest_state(4), 0)
    s = with_sown_fields(s, 0, grain_fields=[(0, 0)])
    s = _run_harvest(s)
    assert _banked(s, 0) == 1
    # Re-enter a later harvest (round 7) with 2 grain fields -> +1 more.
    s = dataclasses.replace(s, pending_stack=())
    s = with_round(with_phase(s, Phase.HARVEST_FIELD), 7)
    s = with_sown_fields(s, 0, grain_fields=[(0, 0), (0, 1)])
    s = _run_harvest(s)
    assert _banked(s, 0) == 2


def test_round_keying_no_double_count():
    """The auto banks once per harvest round even if re-fired."""
    from agricola.cards.wealthy_man import _apply, _eligible
    s = _own(_harvest_state(4), 0)
    s = with_sown_fields(s, 0, grain_fields=[(0, 0)])
    assert _eligible(s, 0)
    s = _apply(s, 0)
    assert _banked(s, 0) == 1
    assert not _eligible(s, 0)        # same round -> no longer eligible


def test_only_owner_banks():
    s = _own(_harvest_state(4), 0)
    s = with_sown_fields(s, 0, grain_fields=[(0, 0)])
    s = with_sown_fields(s, 1, grain_fields=[(0, 0)])   # P1 has a grain field but no card
    out = _run_harvest(s)
    assert _banked(out, 0) == 1
    assert out.players[1].card_state.get(CARD_ID, (0, 0))[1] == 0


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    score = _score_fn()
    s = setup(0)
    assert score(s, 0) == 0
    p = fast_replace(s.players[0], card_state=s.players[0].card_state.set(CARD_ID, (14, 4)))
    s = fast_replace(s, players=(p, s.players[1]))
    assert score(s, 0) == 4
