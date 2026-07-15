"""Tests for Nutrition Expert (occupation, B135; Bubulcus Expansion; players 3+).

Card text: "At the start of each round, you can exchange a set comprised of 1
animal of any type, 1 grain, and 1 vegetable for 5 food and 2 bonus points."

A start-of-round play-variant trigger (the Acquirer shape): one FireTrigger per
animal type held (given the grain + veg the set needs), the reward is +5 food and
2 banked bonus points read back by a scoring term. Once per round via the window.
"""
import agricola.cards.nutrition_expert  # noqa: F401  (registers the card)

import dataclasses

from agricola.actions import FireTrigger, Proceed
from agricola.cards.nutrition_expert import CARD_ID, _legal_variants, _score
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup


def _edit(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx=0):
    return _edit(state, idx, occupations=state.players[idx].occupations | {CARD_ID})


def _enter_round(state, *, from_round=1):
    """Run the real preparation walk into round from_round+1 (Acquirer idiom)."""
    state = dataclasses.replace(state, round_number=from_round, phase=Phase.PREPARATION)
    return _complete_preparation(state)


def _ready(*, animals=Animals(), grain=1, veg=1):
    s = _own(setup(seed=0), 0)
    return _edit(s, 0, animals=animals,
                 resources=Resources(grain=grain, veg=veg))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("start_of_round", [])}
    assert CARD_ID in {cid for cid, _fn in SCORING_TERMS}


# ---------------------------------------------------------------------------
# The set gate: needs an animal AND grain AND veg
# ---------------------------------------------------------------------------

def test_routes_are_the_animal_types_held():
    s = _ready(animals=Animals(sheep=1, cattle=2))
    assert sorted(_legal_variants(s, 0)) == ["cattle", "sheep"]


def test_no_route_without_grain_or_veg():
    assert _legal_variants(_ready(animals=Animals(sheep=1), grain=0), 0) == []
    assert _legal_variants(_ready(animals=Animals(sheep=1), veg=0), 0) == []


def test_no_route_without_any_animal():
    assert _legal_variants(_ready(animals=Animals()), 0) == []


def test_surfaced_at_start_of_round_with_decline():
    s = _enter_round(_ready(animals=Animals(boar=1)))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == "start_of_round"
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID, variant="boar") in la
    assert Proceed() in la                       # optional


# ---------------------------------------------------------------------------
# The exchange + banked points
# ---------------------------------------------------------------------------

def test_exchange_debits_set_grants_food_and_banks_points():
    s = _enter_round(_ready(animals=Animals(sheep=2), grain=3, veg=2))
    s2 = step(s, FireTrigger(card_id=CARD_ID, variant="sheep"))
    p = s2.players[0]
    assert p.animals == Animals(sheep=1)         # gave up 1 sheep
    assert p.resources.grain == 2                # -1
    assert p.resources.veg == 1                  # -1
    assert p.resources.food == 5                 # +5
    assert p.card_state.get(CARD_ID, 0) == 2     # 2 bonus points banked
    assert _score(s2, 0) == 2


def test_only_once_per_round():
    s = _enter_round(_ready(animals=Animals(sheep=3), grain=3, veg=3))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="sheep"))
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(s))


def test_decline_changes_nothing():
    s = _enter_round(_ready(animals=Animals(sheep=1)))
    s2 = step(s, Proceed())
    p = s2.players[0]
    assert p.animals == Animals(sheep=1)
    assert p.resources == Resources(grain=1, veg=1)
    assert p.card_state.get(CARD_ID, 0) == 0


def test_points_accumulate_across_rounds():
    # Bank in round 2, then again in round 3 -> 4 total.
    s = _enter_round(_ready(animals=Animals(cattle=2), grain=2, veg=2))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="cattle"))
    assert _score(s, 0) == 2
    s = _enter_round(s, from_round=2)
    s = step(s, FireTrigger(card_id=CARD_ID, variant="cattle"))
    assert _score(s, 0) == 4


def test_unowned_never_offered():
    s = _enter_round(_edit(setup(seed=0), 0,
                           animals=Animals(sheep=1),
                           resources=Resources(grain=1, veg=1)))
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(s))
