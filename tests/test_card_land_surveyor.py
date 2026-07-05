"""Tests for Land Surveyor (occupation, E107; Ephipparius; field-phase window auto).

Card text (verbatim): "In the field phase of each harvest, if you have at least
2/4/6/7 fields, you get 1/2/3/4 food."

A single graduated income keyed on the count of FIELD tiles on the owner's
farmyard grid (crop-agnostic), read in the harvest field phase:
  >= 7 fields -> 4 food
  >= 6 fields -> 3 food
  >= 4 fields -> 2 food
  >= 2 fields -> 1 food
  <  2 fields -> nothing.

The income is a during-window flat state-reader on the "field_phase" harvest
window (it reads the owner's standing field tiles, not what the take harvested):
`engine._field_phase_step` fires the "field_phase" automatic effects for each
owner BEFORE the mechanical crop take. Tests drive `_resolve_harvest_field` (the
compat alias into the harvest-window walk at HARVEST_FIELD) directly, plus one
full-walk harvest to confirm the food actually lands and the effect does NOT
re-fire outside the field phase.
"""
from __future__ import annotations

import agricola.cards.land_surveyor  # noqa: F401  (registers the card)

from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS, owns_window_card
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, _resolve_harvest_field, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import with_fields, with_phase, with_resources


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id="land_surveyor"):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _field_state(seed=0):
    """A HARVEST_FIELD-phase state (no card owned yet)."""
    return with_phase(setup(seed), Phase.HARVEST_FIELD)


# Distinct empty cells to plow into fields (avoid the two ROOM cells at (1,0)/(2,0)).
_CELLS = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4),
          (1, 1), (1, 2), (1, 3), (1, 4), (2, 1)]


def _with_n_fields(state, idx, n):
    """Plow `n` empty field tiles for player `idx` (crop-agnostic empties)."""
    return with_fields(state, idx, _CELLS[:n])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_land_surveyor_registered():
    assert "land_surveyor" in OCCUPATIONS
    assert "land_surveyor" in HARVEST_WINDOW_CARDS["field_phase"]
    # Occupation: not a minor (no cost/prereq/vps/passing entry).
    from agricola.cards.specs import MINORS
    assert "land_surveyor" not in MINORS


def test_on_play_is_noop():
    state = setup(0)
    before = state
    after = OCCUPATIONS["land_surveyor"].on_play(state, 0)
    assert after == before


# ---------------------------------------------------------------------------
# owns_window_card("field_phase") — the per-player ownership gate
# ---------------------------------------------------------------------------

def test_not_owned_without_card():
    assert owns_window_card(setup(0).players[0], "field_phase") is False


def test_owned_when_played():
    state = _own_occ(setup(0), 0)
    assert owns_window_card(state.players[0], "field_phase") is True


def test_not_owned_when_only_in_hand():
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {"land_surveyor"})
    state = fast_replace(state, players=(p, state.players[1]))
    assert owns_window_card(state.players[0], "field_phase") is False


# ---------------------------------------------------------------------------
# The income table — each threshold boundary
# ---------------------------------------------------------------------------

def _gain_at(n_fields):
    state = _with_n_fields(_own_occ(_field_state(), 0), 0, n_fields)
    f0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    return after.players[0].resources.food - f0


def test_zero_fields_grants_nothing():
    assert _gain_at(0) == 0


def test_one_field_grants_nothing():
    assert _gain_at(1) == 0


def test_two_fields_grants_one():
    assert _gain_at(2) == 1


def test_three_fields_grants_one():
    # Still below the 4-field tier -> stays at 1.
    assert _gain_at(3) == 1


def test_four_fields_grants_two():
    assert _gain_at(4) == 2


def test_five_fields_grants_two():
    assert _gain_at(5) == 2


def test_six_fields_grants_three():
    assert _gain_at(6) == 3


def test_seven_fields_grants_four():
    assert _gain_at(7) == 4


def test_eight_fields_still_four():
    # No tier above 7 -> caps at 4 food.
    assert _gain_at(8) == 4


# ---------------------------------------------------------------------------
# Owner-gating: fires only for the owner
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_occ(_field_state(), 0)
    state = _with_n_fields(state, 0, 4)   # owner has 4 fields
    state = _with_n_fields(state, 1, 7)   # non-owner has 7 fields (should get nothing)
    f0 = state.players[0].resources.food
    f1 = state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 2   # owner gains its tier
    assert after.players[1].resources.food == f1       # non-owner unchanged


def test_both_owners_each_paid_own_tier():
    state = setup(0)
    state = _own_occ(state, 0)
    state = _own_occ(state, 1)
    state = with_phase(state, Phase.HARVEST_FIELD)
    state = _with_n_fields(state, 0, 2)   # tier 1 -> 1 food
    state = _with_n_fields(state, 1, 6)   # tier 3 -> 3 food
    f0 = state.players[0].resources.food
    f1 = state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 1
    assert after.players[1].resources.food == f1 + 3


# ---------------------------------------------------------------------------
# Full-harvest walk: the food lands, and NOT twice (only in the field phase)
# ---------------------------------------------------------------------------

def _drive_harvest_to_completion(state):
    """Drive a HARVEST_FIELD state through the whole harvest (first legal action
    at every decision) and return the state after the harvest phases exit."""
    state = _advance_until_decision(state)
    guard = 0
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        acts = legal_actions(state)
        if not acts:
            break
        state = step(state, acts[0])
        state = _advance_until_decision(state)
        guard += 1
        assert guard < 200, "harvest walk did not terminate"
    return state


def test_full_harvest_walk_pays_exactly_once():
    """Drive a real harvest to completion twice — identical except for card
    ownership — and assert the owner's food differs by EXACTLY the tier payout.
    That pins the income to a single firing (the field phase) and rules out a
    re-fire during feeding/breeding."""
    base = setup(0)
    # 4 fields -> tier 2 (2 food); plenty of food so feeding is painless and
    # both runs pay feeding identically (pure-food payment dominates).
    base = with_resources(base, 0, food=10)
    base = with_resources(base, 1, food=10)
    base = with_phase(base, Phase.HARVEST_FIELD)
    base = _with_n_fields(base, 0, 4)

    end_without = _drive_harvest_to_completion(base)
    end_with = _drive_harvest_to_completion(_own_occ(base, 0))

    assert (end_with.players[0].resources.food
            == end_without.players[0].resources.food + 2)
    # Opponent untouched by the card in both runs.
    assert (end_with.players[1].resources.food
            == end_without.players[1].resources.food)
