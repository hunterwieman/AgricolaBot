"""Tests for Harpooner (occupation, A138; Base Revised).

Card text: "Each time you use the 'Fishing' accumulation space you can also pay 1
wood to get 1 food for each person you have, and 1 reed"

An OPTIONAL trigger on the BEFORE window of the Fishing host (the trigger-timing
ruling: "each time you use" → before; the reward is flat). Fishing is atomic, so
register_action_space_hook makes it a host. Firing pays 1 wood and grants
(people_total food + 1 reed); the host's Proceed does the normal Fishing take.
Tests drive the real hosted lifecycle via setup_env (card mode).
"""
from __future__ import annotations

import agricola.cards.harpooner  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD_ID = "harpooner"
_FIRE = FireTrigger(card_id=CARD_ID)

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(*, res=None, food_on_fishing=1, occ=(CARD_ID,), seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "fishing"),
                      workers=(0, 0), accumulated_amount=food_on_fishing)
    cs = fast_replace(cs, board=with_space(cs.board, "fishing", sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     occupations=cs.players[cp].occupations | set(occ),
                     resources=res if res is not None else Resources())
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _place(state):
    state = step(state, PlaceWorker(space="fishing"))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"    # offered BEFORE the take
    return state


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    trig = next(e for e in TRIGGERS.get("before_action_space", ())
                if e.card_id == CARD_ID)
    assert not trig.mandatory                            # "you can also" → optional
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["fishing"]   # atomic space is hosted


# --- The paid grant, before the Fishing take --------------------------------

def test_fire_pays_wood_and_grants_food_per_person_plus_reed():
    cs, cp = _state(res=Resources(wood=1), food_on_fishing=2)
    cs = _place(cs)
    people = cs.players[cp].people_total                 # 2 in a fresh game
    assert _FIRE in legal_actions(cs)
    assert Proceed() in legal_actions(cs)                # declining is available

    cs = step(cs, _FIRE)
    p = cs.players[cp]
    assert p.resources.wood == 0                         # 1 wood paid
    assert p.resources.food == people                    # 1 food per person
    assert p.resources.reed == 1                         # + 1 reed
    # Once per use: not re-offered on the same host visit.
    assert _FIRE not in legal_actions(cs)

    cs = step(cs, Proceed())                             # the Fishing take
    assert cs.players[cp].resources.food == people + 2   # + the 2 accumulated food


def test_no_fire_without_wood():
    cs, cp = _state(res=Resources(wood=0), food_on_fishing=1)
    cs = _place(cs)
    assert _FIRE not in legal_actions(cs)                # can't pay the 1 wood
    assert Proceed() in legal_actions(cs)


def test_decline_via_proceed_spends_nothing():
    cs, cp = _state(res=Resources(wood=1), food_on_fishing=1)
    cs = _place(cs)
    assert _FIRE in legal_actions(cs)
    cs = step(cs, Proceed())                             # decline; take only
    p = cs.players[cp]
    assert p.resources.wood == 1                         # no wood spent
    assert p.resources.reed == 0
    assert p.resources.food == 1                         # only the Fishing take


def test_non_owner_sees_no_trigger():
    cs, _env = setup_env(5, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "fishing"),
                      workers=(0, 0), accumulated_amount=1)
    cs = fast_replace(cs, board=with_space(cs.board, "fishing", sp))
    cp = cs.current_player                               # owns nothing here
    cs = fast_replace(cs, players=tuple(
        fast_replace(cs.players[i], resources=Resources(wood=1)) if i == cp
        else cs.players[i] for i in range(2)))
    cs = step(cs, PlaceWorker(space="fishing"))
    # Fishing is not hosted for a non-owner → atomic resolution, no before-phase
    # trigger. Either way, the Harpooner fire is never offered.
    assert _FIRE not in legal_actions(cs)
