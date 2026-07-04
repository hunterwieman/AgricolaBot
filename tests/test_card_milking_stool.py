"""Tests for Milking Stool (minor improvement, D38; Consul Dirigens).

Card text: "In the field phase of each harvest, if you have at least 1/3/5 cattle,
you get 1/2/3 food. During scoring, you get 1 bonus point for every 2 cattle you
have." Printed VPs: 0. Prerequisite: 2 occupations.

Cattle analog of Loom (sheep) — a during-window flat state-reader on the
"field_phase" harvest window (MANDATORY, choice-free income fired pre-take by
`engine._field_phase_step`) plus a Category-1 scoring term (`cattle // 2`).
Mirrors tests/test_cards_category6.py.
"""
from __future__ import annotations

import agricola.cards.milking_stool  # noqa: F401

from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS, owns_window_card
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import _resolve_harvest_field
from agricola.replace import fast_replace
from agricola.scoring import score
from agricola.setup import setup

from tests.factories import with_animals, with_phase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _field_state(seed=0):
    state = setup(seed)
    return with_phase(state, Phase.HARVEST_FIELD)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_milking_stool_registered():
    assert "milking_stool" in MINORS
    assert "milking_stool" in HARVEST_WINDOW_CARDS["field_phase"]
    spec = MINORS["milking_stool"]
    # Printed VPs = 0 (all VP comes from the cattle scoring term).
    assert spec.vps == 0
    # Prerequisite: 2 occupations (a PREREQ, modeled as min_occupations).
    assert spec.min_occupations == 2
    # Cost is 1 wood.
    assert spec.cost.resources.wood == 1


# ---------------------------------------------------------------------------
# owns_window_card("field_phase") — the per-player ownership gate
# ---------------------------------------------------------------------------

def test_not_owned_without_card():
    assert owns_window_card(setup(0).players[0], "field_phase") is False


def test_owned_when_played():
    state = _own_minor(setup(0), 0, "milking_stool")
    assert owns_window_card(state.players[0], "field_phase") is True
    # Owned by the OTHER player is that player's own field-phase auto.
    state2 = _own_minor(setup(0), 1, "milking_stool")
    assert owns_window_card(state2.players[1], "field_phase") is True


def test_not_owned_when_card_only_in_hand():
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, hand_minors=p.hand_minors | {"milking_stool"})
    state = fast_replace(state, players=(p, state.players[1]))
    assert owns_window_card(state.players[0], "field_phase") is False


# ---------------------------------------------------------------------------
# Field-phase food tiers — 1/2/3 food at >=1/3/5 cattle
# ---------------------------------------------------------------------------

def test_food_tiers():
    # Tier steps at >=1, >=3, >=5 cattle. Note the deliberate boundary cases
    # (2 -> still tier-1, 4 -> still tier-2).
    for cattle, expected in [(0, 0), (1, 1), (2, 1), (3, 2), (4, 2), (5, 3), (8, 3)]:
        state = _own_minor(_field_state(), 0, "milking_stool")
        state = with_animals(state, 0, cattle=cattle)
        food0 = state.players[0].resources.food
        after = _resolve_harvest_field(state)
        assert after.players[0].resources.food == food0 + expected, f"cattle={cattle}"


def test_no_food_with_zero_cattle():
    # Eligibility is always True, but 0 cattle yields 0 food (apply is a no-op).
    state = _own_minor(_field_state(), 0, "milking_stool")
    state = with_animals(state, 0, cattle=0)
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0


def test_fires_only_for_its_owner():
    state = _own_minor(_field_state(), 0, "milking_stool")
    state = with_animals(state, 0, cattle=5)
    state = with_animals(state, 1, cattle=5)   # P1 does NOT own the card
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == f0 + 3   # owner gets tier-3
    assert after.players[1].resources.food == f1       # non-owner unchanged


def test_food_independent_of_other_animals():
    # Only cattle drive the food income (sheep/boar are irrelevant).
    state = _own_minor(_field_state(), 0, "milking_stool")
    state = with_animals(state, 0, cattle=3, sheep=8, boar=8)
    food0 = state.players[0].resources.food
    after = _resolve_harvest_field(state)
    assert after.players[0].resources.food == food0 + 2   # 3 cattle -> tier-2


# ---------------------------------------------------------------------------
# Scoring — 1 bonus point per 2 cattle (separate table from the food tiers)
# ---------------------------------------------------------------------------

def test_scoring_one_bonus_per_two_cattle():
    for cattle, expected in [(0, 0), (1, 0), (2, 1), (3, 1), (4, 2), (6, 3)]:
        state = _own_minor(setup(0), 0, "milking_stool")
        state = with_animals(state, 0, cattle=cattle)
        state = with_phase(state, Phase.BEFORE_SCORING)
        total, _ = score(state, 0)
        base = with_phase(
            with_animals(setup(0), 0, cattle=cattle), Phase.BEFORE_SCORING)
        base_total, _ = score(base, 0)
        # Printed VPs = 0, so the only delta is the cattle // 2 scoring term.
        assert total == base_total + expected, f"cattle={cattle}"


def test_scoring_only_for_owner():
    # The scoring term reads the owner's cattle; the non-owner is unaffected.
    state = _own_minor(setup(0), 0, "milking_stool")
    state = with_animals(state, 0, cattle=6)
    state = with_animals(state, 1, cattle=6)
    state = with_phase(state, Phase.BEFORE_SCORING)
    base = with_phase(
        with_animals(with_animals(setup(0), 0, cattle=6), 1, cattle=6),
        Phase.BEFORE_SCORING)
    t0, _ = score(state, 0)
    t1, _ = score(state, 1)
    b0, _ = score(base, 0)
    b1, _ = score(base, 1)
    assert t0 == b0 + 3   # owner: 6 // 2 = 3 bonus
    assert t1 == b1       # non-owner: no bonus
