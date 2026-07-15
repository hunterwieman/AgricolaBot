"""Tests for Huntsman (occupation, B147; Bubulcus Expansion).

Card text: "Each time after you use a wood accumulation space, you can pay 1 grain
to get 1 wild boar."

An OPTIONAL trigger on the AFTER window of the wood accumulation space (the text
says "after" explicitly). In the 2-player engine that space is Forest, hosted via
register_action_space_hook. Firing pays 1 grain and grants 1 boar through
grant_animals (accommodation barrier handles overflow). Tests drive the real
hosted lifecycle via setup_env (card mode).
"""
from __future__ import annotations

import agricola.cards.huntsman  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD_ID = "huntsman"
_FIRE = FireTrigger(card_id=CARD_ID)

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(*, grain=1, boar=0, occ=(CARD_ID,), seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    sp = fast_replace(get_space(cs.board, "forest"), workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "forest", sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     occupations=cs.players[cp].occupations | set(occ),
                     resources=Resources(grain=grain),
                     animals=Animals(boar=boar))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _use_forest(state):
    """Place at Forest and Proceed to the after window (wood taken, space zeroed)."""
    state = step(state, PlaceWorker(space="forest"))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"      # the "after you use" window
    return state


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    trig = next(e for e in TRIGGERS.get("after_action_space", ())
                if e.card_id == CARD_ID)
    assert not trig.mandatory                            # "you can" → optional
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["forest"]    # atomic space is hosted


# --- The paid grant ---------------------------------------------------------

def test_fire_pays_grain_and_grants_boar():
    cs, cp = _state(grain=1, boar=0)
    cs = _use_forest(cs)
    assert _FIRE in legal_actions(cs)
    assert Stop() in legal_actions(cs)                   # declining is available

    cs = step(cs, _FIRE)
    p = cs.players[cp]
    assert p.resources.grain == 0                        # 1 grain paid
    assert p.animals.boar == 1                           # the boar arrived (fits)
    # 1 boar fits the fresh farm (house pet) — no accommodation frame.
    assert not any(isinstance(f, PendingAccommodate) for f in cs.pending_stack)
    # Once per use: not re-offered on the same host visit.
    assert _FIRE not in legal_actions(cs)


def test_no_fire_without_grain():
    cs, cp = _state(grain=0)
    cs = _use_forest(cs)
    assert _FIRE not in legal_actions(cs)
    assert Stop() in legal_actions(cs)


def test_decline_via_stop_spends_nothing():
    cs, cp = _state(grain=1)
    cs = _use_forest(cs)
    assert _FIRE in legal_actions(cs)
    cs = step(cs, Stop())                                # decline
    p = cs.players[cp]
    assert p.resources.grain == 1                        # grain kept
    assert p.animals.boar == 0


def test_overflow_grant_surfaces_accommodation():
    """3 boar already + house pet only (no pasture): the granted 4th boar lands
    over capacity and the barrier surfaces a PendingAccommodate."""
    cs, cp = _state(grain=1, boar=3)
    cs = _use_forest(cs)
    cs = step(cs, _FIRE)
    assert cs.players[cp].animals.boar == 4              # granted over capacity
    assert isinstance(cs.pending_stack[-1], PendingAccommodate)


def test_non_owner_sees_no_trigger():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = fast_replace(cs, board=with_space(
        cs.board, "forest", fast_replace(get_space(cs.board, "forest"), workers=(0, 0))))
    cp = cs.current_player                               # owns nothing
    cs = fast_replace(cs, players=tuple(
        fast_replace(cs.players[i], resources=Resources(grain=1)) if i == cp
        else cs.players[i] for i in range(2)))
    cs = step(cs, PlaceWorker(space="forest"))
    assert _FIRE not in legal_actions(cs)
