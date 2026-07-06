"""Tests for Uncaring Parents (occupation, E99; Ephipparius Expansion).

Card text (verbatim): "At the end of each harvest, if you live in a stone
house, you get 1 bonus point."

A mandatory, choice-free AUTO on harvest window #16, ``end_of_harvest`` (the
last in-harvest moment — after the breeding phase and after-breeding effects,
strictly before the after-harvest window; post-breeding-timeline ruling
2026-07-03). Each fire banks 1 bonus point in the CardStore; the scoring term
reads the bank back at end-game (points are earned, not printed VPs). The
stone-house condition (``PlayerState.house_material == HouseMaterial.STONE``)
is evaluated at each firing, so renovating to stone mid-game earns the point
at every later harvest.

The harvest tests drive the REAL walk (`_advance_until_decision` + `step`,
like tests/test_harvest_windows.py) from Phase.HARVEST_FIELD through the whole
ladder; players are given ample food so feeding is painless. The exact-window
timing is probed by a fake bracket card (id prefixed `_test_up_`, registered
through the real API at module import, ownership-gated so it is inert
everywhere else — the tests/test_harvest_windows.py containment pattern):
its autos at ``after_breeding`` (the window just BEFORE end_of_harvest) and
``after_harvest`` (the window just AFTER) record the bank at those moments,
bracketing the fire to exactly end_of_harvest.
"""
from __future__ import annotations

import json
from pathlib import Path

import agricola.cards.uncaring_parents  # noqa: F401  (registers the card)

import pytest

from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, register_auto
from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.uncaring_parents import CARD_ID, _bank, _eligible
from agricola.constants import HouseMaterial, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup

from tests.factories import with_phase, with_round


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {card_id})


def _with_house(state, idx, material):
    return _edit_player(state, idx, house_material=material)


def _bank_of(state, idx):
    return state.players[idx].card_state.get(CARD_ID, 0)


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state with enough food that feeding is painless."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    state = fast_replace(state, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, resources=fast_replace(
            state.players[idx].resources, food=food))
    return state


def _run_harvest(state, pick=lambda acts: acts[0]):
    """Drive the harvest to completion (into the next round's reveal)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


def _next_harvest(state):
    """Re-enter a fresh harvest after one has completed (the walk is
    round-number-agnostic; the completed harvest left PREPARATION with the
    next round's reveal frame pending — drop it and rewind the phase)."""
    return fast_replace(state, phase=Phase.HARVEST_FIELD, pending_stack=())


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# ---------------------------------------------------------------------------
# The timing-bracket probe (fake card — registered once, ownership-gated)
# ---------------------------------------------------------------------------

PROBE_CARD = "_test_up_bracket"


def _append_probe(state, idx, tag):
    p = state.players[idx]
    seq = p.card_state.get(PROBE_CARD, ())
    return _edit_player(state, idx, card_state=p.card_state.set(
        PROBE_CARD, seq + ((tag, _bank_of(state, idx)),)))


register_auto("after_breeding", PROBE_CARD, lambda s, i: True,
              lambda s, i: _append_probe(s, i, "after_breeding"))
register_auto("after_harvest", PROBE_CARD, lambda s, i: True,
              lambda s, i: _append_probe(s, i, "after_harvest"))
register_harvest_window_hook(PROBE_CARD, "after_breeding")
register_harvest_window_hook(PROBE_CARD, "after_harvest")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    # No on-play effect.
    state = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) is state
    # A choice-free AUTO on the end_of_harvest window, own-owner only.
    entries = [e for e in AUTO_EFFECTS.get("end_of_harvest", ())
               if e.card_id == CARD_ID]
    assert len(entries) == 1
    assert entries[0].any_player is False
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("end_of_harvest", set())
    # The banked points are read back by a scoring term.
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_json_row_matches():
    """The catalog row (revised_occupations.json) matches what the module
    implements and quotes: E99, Occupation, 1+ players, verbatim text."""
    import agricola.cards
    data = json.loads((Path(agricola.cards.__file__).parent / "data"
                       / "revised_occupations.json").read_text())
    row = next(r for r in data if r.get("name") == "Uncaring Parents")
    assert row["type"] == "Occupation"
    assert row["deck"] == "E"
    assert row["number"] == 99
    assert row["players"] == "1+"
    assert row["expansion"] == "Ephipparius Expansion"
    # Verbatim text in the docstring (whitespace-normalized: the quote is
    # line-wrapped there, content-identical).
    doc = " ".join(agricola.cards.uncaring_parents.__doc__.split())
    assert " ".join(row["text"].split()) in doc


# ---------------------------------------------------------------------------
# The core effect: stone house at harvest end -> 1 banked point
# ---------------------------------------------------------------------------

def test_stone_house_owner_banks_one_point_per_harvest():
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = _with_house(state, 0, HouseMaterial.STONE)
    final = _run_harvest(state)
    assert final.phase == Phase.PREPARATION
    assert _bank_of(final, 0) == 1


def test_wood_house_banks_nothing():
    state = _own_occ(_harvest_state(), 0, CARD_ID)   # setup house is wood
    assert state.players[0].house_material == HouseMaterial.WOOD
    final = _run_harvest(state)
    assert _bank_of(final, 0) == 0


def test_clay_house_banks_nothing():
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = _with_house(state, 0, HouseMaterial.CLAY)
    final = _run_harvest(state)
    assert _bank_of(final, 0) == 0


def test_renovating_to_stone_mid_game_banks_later_harvests():
    """A clay-house harvest banks nothing; after renovating to stone (house
    material set directly between harvests), the NEXT harvest banks."""
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = _with_house(state, 0, HouseMaterial.CLAY)
    state = _run_harvest(state)
    assert _bank_of(state, 0) == 0
    state = _with_house(_next_harvest(state), 0, HouseMaterial.STONE)
    state = _run_harvest(state)
    assert _bank_of(state, 0) == 1


def test_fires_each_of_two_consecutive_harvests_banking_two():
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = _with_house(state, 0, HouseMaterial.STONE)
    state = _run_harvest(state)
    assert _bank_of(state, 0) == 1
    state = _run_harvest(_next_harvest(state))
    assert _bank_of(state, 0) == 2


def test_final_harvest_banks_too():
    """The round-14 harvest completes into BEFORE_SCORING — its end_of_harvest
    window still fires (\"each harvest\" includes the last)."""
    state = _own_occ(with_round(_harvest_state(), 14), 0, CARD_ID)
    state = _with_house(state, 0, HouseMaterial.STONE)
    final = _run_harvest(state)
    assert final.phase == Phase.BEFORE_SCORING
    assert _bank_of(final, 0) == 1


# ---------------------------------------------------------------------------
# Timing: the point lands at end_of_harvest — inside the harvest
# ---------------------------------------------------------------------------

def test_point_lands_at_end_of_harvest_before_after_harvest():
    """Bracket the fire with probe autos on the adjacent windows: at
    after_breeding (just BEFORE end_of_harvest) the bank is still 0; at
    after_harvest (just AFTER, outside the harvest) it is already 1 — so the
    increment happened exactly at the end_of_harvest window."""
    state = _own_occ(_own_occ(_harvest_state(), 0, CARD_ID), 0, PROBE_CARD)
    state = _with_house(state, 0, HouseMaterial.STONE)
    final = _run_harvest(state)
    seq = final.players[0].card_state.get(PROBE_CARD, ())
    assert seq == (("after_breeding", 0), ("after_harvest", 1))
    assert _bank_of(final, 0) == 1


def test_choice_free_no_window_frame_from_this_card():
    """The card is an AUTO, never a decision: owning it alone pushes no
    PendingHarvestWindow frame anywhere in the harvest."""
    state = _own_occ(_harvest_state(), 0, CARD_ID)
    state = _with_house(state, 0, HouseMaterial.STONE)
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        assert not any(isinstance(f, PendingHarvestWindow)
                       for f in state.pending_stack)
        state = step(state, legal_actions(state)[0])
    assert _bank_of(state, 0) == 1


# ---------------------------------------------------------------------------
# Owner-gating
# ---------------------------------------------------------------------------

def test_unowned_never_banks():
    state = _harvest_state()
    state = _with_house(state, 0, HouseMaterial.STONE)
    state = _with_house(state, 1, HouseMaterial.STONE)
    final = _run_harvest(state)
    for idx in (0, 1):
        assert _bank_of(final, idx) == 0
        assert final.players[idx].card_state.get(CARD_ID) is None


def test_banks_only_for_the_owner():
    """Both players live in stone houses; only the owner (P1) banks."""
    state = _own_occ(_harvest_state(), 1, CARD_ID)
    state = _with_house(state, 0, HouseMaterial.STONE)
    state = _with_house(state, 1, HouseMaterial.STONE)
    final = _run_harvest(state)
    assert _bank_of(final, 0) == 0
    assert _bank_of(final, 1) == 1


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_scoring_term_returns_banked_total():
    score_fn = _score_fn()
    state = setup(0)
    assert score_fn(state, 0) == 0            # no bank -> 0
    p = state.players[0]
    state = _edit_player(state, 0, card_state=p.card_state.set(CARD_ID, 4))
    assert score_fn(state, 0) == 4
    assert score_fn(state, 1) == 0            # opponent (no bank) scores 0


def test_score_includes_banked_points_end_to_end():
    """score() adds the banked total for the owner: banking 3 points raises
    the total by exactly 3 over the same state with an empty bank."""
    state = _own_occ(setup(0), 0, CARD_ID)
    base_total, _ = score(state, 0)
    p = state.players[0]
    banked = _edit_player(state, 0, card_state=p.card_state.set(CARD_ID, 3))
    total, _ = score(banked, 0)
    assert total == base_total + 3


# ---------------------------------------------------------------------------
# Direct effect-fn unit checks
# ---------------------------------------------------------------------------

def test_eligible_predicate_reads_house_material():
    state = setup(0)
    assert _eligible(state, 0) is False       # wood
    assert _eligible(_with_house(state, 0, HouseMaterial.CLAY), 0) is False
    assert _eligible(_with_house(state, 0, HouseMaterial.STONE), 0) is True


def test_bank_increments_counter_only_for_owner_seat():
    state = setup(0)
    after = _bank(state, 0)
    assert _bank_of(after, 0) == 1
    assert after.players[1] == state.players[1]     # opponent untouched
    assert after.players[0].resources == state.players[0].resources
    again = _bank(after, 0)
    assert _bank_of(again, 0) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
