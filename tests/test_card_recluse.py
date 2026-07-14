"""Tests for Recluse (occupation, E111; Ephipparius Expansion).

Card text: "As long as you have no minor improvements in front of you, you get 1
food at the start of each round and 1 wood at the start of each harvest."

TWO choice-free automatic effects sharing one standing condition ("no minor
improvements in front of you" = the PLAYED minor tableau is empty):
  1. `start_of_round`  — +1 food each round (the preparation ladder's
     start_of_round window, ruling 54, 2026-07-14 — fired frame-lessly, driven
     through the real `_complete_preparation` boundary).
  2. `start_of_harvest` — +1 wood each harvest (harvest window #2, driven through
     the real harvest walk).
Both are gated by the same `_eligible` predicate; playing any minor improvement
turns both off. Majors / occupations "in front of you" do NOT disqualify — the
text names only minor improvements.
"""
from __future__ import annotations

import agricola.cards.recluse  # noqa: F401  (registers the card)

import pytest

from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, _complete_preparation, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_majors, with_phase

CARD_ID = "recluse"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _add_minor(state, idx, minor_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {minor_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _enter_round(state, idx, *, from_round: int):
    """Set round_number=from_round and run the real `_complete_preparation` to
    enter round from_round+1, firing the player's start_of_round autos."""
    state = fast_replace(state, round_number=from_round, phase=Phase.PREPARATION)
    return _complete_preparation(state)


def _harvest_state(seed=0, food=10):
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i],
                         resources=fast_replace(state.players[i].resources, food=food))
            if i == idx else state.players[i] for i in range(2)))
    return state


def _run_harvest(state, pick=lambda acts: acts[0]):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation():
    assert CARD_ID in OCCUPATIONS
    # No on-play effect.
    s = setup(0)
    before = s.players[0].resources
    s2 = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert s2.players[0].resources == before


def test_registered_on_both_windows():
    # start_of_round auto (the preparation ladder's window — autos fire
    # frame-lessly, so no separate hosting registration exists).
    round_autos = {e.card_id for e in AUTO_EFFECTS.get("start_of_round", ())}
    assert CARD_ID in round_autos
    # start_of_harvest auto + hook.
    harvest_autos = {e.card_id for e in AUTO_EFFECTS.get("start_of_harvest", ())}
    assert CARD_ID in harvest_autos
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("start_of_harvest", set())
    # Both are mandatory autos, not declinable triggers.
    assert CARD_ID not in {e.card_id for e in TRIGGERS.get("start_of_round", ())}
    assert CARD_ID not in {e.card_id for e in TRIGGERS.get("start_of_harvest", ())}


# ---------------------------------------------------------------------------
# Clause 1 — +1 food at the start of each round
# ---------------------------------------------------------------------------

def test_start_of_round_grants_one_food():
    s = _own_occ(setup(0), 0)
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=2)
    assert out.round_number == 3
    assert out.players[0].resources - before == Resources(food=1)


def test_start_of_round_gated_off_by_a_minor():
    """A played minor improvement turns the food income off."""
    s = _own_occ(setup(0), 0)
    s = _add_minor(s, 0, "some_minor")
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=2)
    assert out.players[0].resources == before  # nothing gained


def test_start_of_round_major_does_not_disqualify():
    """A played MAJOR improvement does NOT disqualify (text names only minors).
    Majors live on the board (`major_improvement_owners`), not the minor tableau,
    so ownership of one leaves `minor_improvements` empty and eligibility intact."""
    s = _own_occ(setup(0), 0)
    s = with_majors(s, owner_by_idx={0: 0})  # P0 owns major-improvement index 0
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=2)
    assert out.players[0].resources - before == Resources(food=1)


# ---------------------------------------------------------------------------
# Clause 2 — +1 wood at the start of each harvest
# ---------------------------------------------------------------------------

def test_start_of_harvest_grants_one_wood():
    base = _harvest_state()
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_occ(base, 0))
    assert owned.players[0].resources.wood == baseline.players[0].resources.wood + 1


def test_start_of_harvest_gated_off_by_a_minor():
    base = _own_occ(_harvest_state(), 0)
    baseline = _run_harvest(_harvest_state())
    with_minor = _run_harvest(_add_minor(base, 0, "some_minor"))
    # Owning Recluse but with a played minor -> no wood over the plain baseline.
    assert with_minor.players[0].resources.wood == baseline.players[0].resources.wood


# ---------------------------------------------------------------------------
# Both clauses fire on a harvest round (food during prep, wood at harvest)
# ---------------------------------------------------------------------------

def test_both_fire_on_a_harvest_round():
    """Round 4 is a harvest round: the start-of-round food lands in preparation,
    then the start-of-harvest wood lands when the harvest opens."""
    s = _own_occ(setup(0), 0)
    food_before = s.players[0].resources.food
    # Enter round 4 (harvest round) -> +1 food from the start-of-round clause.
    out = _enter_round(s, 0, from_round=3)
    assert out.round_number == 4
    assert out.players[0].resources.food == food_before + 1
    # Now drive the harvest itself (from a fresh harvest state, same ownership)
    # -> +1 wood from the start-of-harvest clause.
    base = _harvest_state()
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_occ(base, 0))
    assert owned.players[0].resources.wood == baseline.players[0].resources.wood + 1


# ---------------------------------------------------------------------------
# Owner-gating
# ---------------------------------------------------------------------------

def test_start_of_round_only_owner_gains():
    s = _own_occ(setup(0), 0)   # only P0 owns
    p1_before = s.players[1].resources
    out = _enter_round(s, 0, from_round=2)
    assert out.players[0].resources.food == s.players[0].resources.food + 1
    assert out.players[1].resources == p1_before


def test_start_of_harvest_only_owner_gains():
    base = _harvest_state()
    baseline = _run_harvest(base)
    owned = _run_harvest(_own_occ(base, 0))   # only P0 owns
    assert owned.players[0].resources.wood == baseline.players[0].resources.wood + 1
    assert owned.players[1].resources.wood == baseline.players[1].resources.wood


# ---------------------------------------------------------------------------
# Direct effect-fn unit checks
# ---------------------------------------------------------------------------

def test_eligible_predicate():
    s = setup(0)
    # Empty played-minor tableau -> eligible.
    assert agricola.cards.recluse._eligible(s, 0) is True
    s2 = _add_minor(s, 0, "some_minor")
    assert agricola.cards.recluse._eligible(s2, 0) is False


def test_apply_food_and_wood_isolated():
    s = setup(0)
    f0 = s.players[0].resources.food
    w0 = s.players[0].resources.wood
    after_food = agricola.cards.recluse._apply_food(s, 0)
    assert after_food.players[0].resources.food == f0 + 1
    assert after_food.players[0].resources.wood == w0  # food clause is food only
    after_wood = agricola.cards.recluse._apply_wood(s, 0)
    assert after_wood.players[0].resources.wood == w0 + 1
    assert after_wood.players[0].resources.food == f0  # wood clause is wood only


# ---------------------------------------------------------------------------
# Family fast path — no income without the card
# ---------------------------------------------------------------------------

def test_family_no_income_without_card():
    base = _harvest_state(seed=3)
    final = _run_harvest(base)
    assert final.phase == Phase.PREPARATION
    assert all(type(f).__name__ != "PendingHarvestWindow"
               for f in final.pending_stack)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
