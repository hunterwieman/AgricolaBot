"""Tests for Cattle Feeder (occupation, B166; Base Revised).

Card text: "Each time you use the 'Grain Seeds' action space, you can also buy 1
cattle for 1 food."

An OPTIONAL trigger on the BEFORE window of the Grain Seeds host (the
trigger-timing ruling: "each time you use" → before; the reward is flat). Grain
Seeds is atomic, so register_action_space_hook hosts it. The 1 food rides the
shared food-payment path (liquidation-aware), and the cattle is granted via
grant_animals. Tests drive the real hosted lifecycle via setup_env (card mode),
including the liquidation route (cook a sheep to pay) mirroring Sugar Baker.
"""
from __future__ import annotations

import agricola.cards.cattle_feeder  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitFoodPayment,
    FireTrigger,
    PlaceWorker,
    Proceed,
)
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, OCCUPATIONS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingActionSpace, PendingFoodPayment
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_majors

CARD_ID = "cattle_feeder"
_FIRE = FireTrigger(card_id=CARD_ID)

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(*, food=1, cattle=0, sheep=0, occ=(CARD_ID,), seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "grain_seeds"), workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "grain_seeds", sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     occupations=cs.players[cp].occupations | set(occ),
                     resources=Resources(food=food),
                     animals=Animals(cattle=cattle, sheep=sheep))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _place(state):
    state = step(state, PlaceWorker(space="grain_seeds"))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"     # offered BEFORE the take
    return state


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    trig = next(e for e in TRIGGERS.get("before_action_space", ())
                if e.card_id == CARD_ID)
    assert not trig.mandatory                             # "you can also" → optional
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["grain_seeds"]
    assert CARD_ID in FOOD_PAYMENT_RESUMES                # the 1 food is liquidatable


# --- The paid grant, food on hand -------------------------------------------

def test_fire_pays_food_and_grants_cattle():
    cs, cp = _state(food=1, cattle=0)
    cs = _place(cs)
    assert _FIRE in legal_actions(cs)
    assert Proceed() in legal_actions(cs)                 # declining is available

    cs = step(cs, _FIRE)
    p = cs.players[cp]
    assert p.resources.food == 0                          # 1 food paid
    assert p.animals.cattle == 1                          # cattle bought (fits)
    assert _FIRE not in legal_actions(cs)                 # once per use

    cs = step(cs, Proceed())                              # the Grain Seeds take
    assert cs.players[cp].resources.grain == 1


# --- The 1-food price via liquidation (0 food, Fireplace + sheep) ------------

def test_fire_via_liquidation_food_payment_path():
    cs, cp = _state(food=0, sheep=1)
    cs = with_majors(cs, owner_by_idx={0: cp})            # a Fireplace (sheep → 2 food)
    cs = _place(cs)
    assert _FIRE in legal_actions(cs)                     # liquidatable

    cs = step(cs, _FIRE)
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == CARD_ID

    pay = CommitFoodPayment(grain=0, veg=0, sheep=1, boar=0, cattle=0)
    assert pay in legal_actions(cs)
    cs = step(cs, pay)                                    # cook the sheep, resume debits 1
    p = cs.players[cp]
    assert p.resources.food == 1                          # raised 2, paid 1
    assert p.animals.sheep == 0                           # the sheep was cooked
    assert p.animals.cattle == 1                          # the cattle arrived


def test_no_fire_when_unaffordable():
    cs, cp = _state(food=0)                               # no food, no liquidation source
    cs = _place(cs)
    assert _FIRE not in legal_actions(cs)
    assert Proceed() in legal_actions(cs)


def test_decline_via_proceed_spends_nothing():
    cs, cp = _state(food=1)
    cs = _place(cs)
    assert _FIRE in legal_actions(cs)
    cs = step(cs, Proceed())                              # decline; grain take only
    p = cs.players[cp]
    assert p.resources.food == 1                          # no food spent
    assert p.animals.cattle == 0
    assert p.resources.grain == 1


def test_overflow_grant_surfaces_accommodation():
    """3 cattle already + house pet only: the bought 4th lands over capacity and
    the barrier surfaces a PendingAccommodate."""
    cs, cp = _state(food=1, cattle=3)
    cs = _place(cs)
    cs = step(cs, _FIRE)
    assert cs.players[cp].animals.cattle == 4
    assert isinstance(cs.pending_stack[-1], PendingAccommodate)


def test_non_owner_sees_no_trigger():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = fast_replace(cs, board=with_space(
        cs.board, "grain_seeds",
        fast_replace(get_space(cs.board, "grain_seeds"), workers=(0, 0))))
    cp = cs.current_player                                # owns nothing
    cs = fast_replace(cs, players=tuple(
        fast_replace(cs.players[i], resources=Resources(food=1)) if i == cp
        else cs.players[i] for i in range(2)))
    cs = step(cs, PlaceWorker(space="grain_seeds"))
    assert _FIRE not in legal_actions(cs)
