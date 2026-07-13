"""Trellis (minor improvement, C15; Corbarius Expansion).

Card text: "Each time before you use the 'Pig Market' accumulation space, you can take a
'Build Fences' action. (You must pay wood for the fences as usual.)"
Prerequisite: 2 Occupations. No cost; no VPs; kept (not passing).

An OPTIONAL, declinable `before_action_space` trigger on the NON-ATOMIC Pig Market space
(always hosted by PendingPigMarket — no register_action_space_hook needed) that grants a
literal Build Fences action via the PendingGrantedSubAction choose-or-decline wrapper, paid
at the normal wood cost (no discount registered). Mirrors tests/test_card_brewing_water.py
(the optional market FireTrigger / decline / once-per-use flow) crossed with
tests/test_cards_field_fences.py (the granted-Build-Fences wrapper + build).

NOTE: distinct from "Trellises" [trellises] (Artifex A #47) — a different, already-implemented
card. This module exercises deck C #15 [trellis].
"""
from __future__ import annotations

import agricola.cards.trellis  # noqa: F401  (registers the card; not in cards/__init__)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildPasture,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import TRIGGERS
from agricola.cards.trellis import CARD_ID, FRAME_ID
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBuildFences,
    PendingGrantedSubAction,
    PendingPigMarket,
)
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import setup

from tests.factories import with_space
from tests.test_fencing import _fencing_setup

_1x1_03 = frozenset({(0, 3)})   # a fresh corner 1x1: 4 new edges -> costs 4 wood (no discount)


def _own(state, idx=0):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _market_state(*, wood=20, accumulated=1, own=True, current_player=0):
    """CARDS-mode state: Pig Market revealed + `accumulated` boar; P0 owns Trellis + has wood."""
    state = fast_replace(_fencing_setup(wood=wood, current_player=current_player),
                         mode=GameMode.CARDS)
    state = with_space(state, "pig_market", revealed=True, accumulated_amount=accumulated)
    if own:
        state = _own(state, current_player)
    return state


def _wood(state, idx=0):
    return state.players[idx].resources.wood


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

def test_registered_as_free_prereq_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()             # no resource cost
    assert spec.min_occupations == 2       # prerequisite: 2 occupations
    assert spec.vps == 0
    assert spec.passing_left is False


def test_registered_as_optional_before_trigger():
    # Optional → lives in TRIGGERS (the FireTrigger registry), not AUTO_EFFECTS.
    entry = next((e for e in TRIGGERS.get("before_action_space", ())
                  if e.card_id == CARD_ID), None)
    assert entry is not None
    assert entry.mandatory is False        # declinable, not mandatory-with-choice


def test_no_action_space_hook_registered():
    # Pig Market is NON-ATOMIC (always hosted), so Trellis registers NO action-space hook
    # (that index only conditionally hosts ATOMIC spaces).
    from agricola.cards.triggers import ANY_PLAYER_HOOK_CARDS, OWN_ACTION_HOOK_CARDS
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("pig_market", set())
    assert CARD_ID not in ANY_PLAYER_HOOK_CARDS.get("pig_market", set())


# --------------------------------------------------------------------------- #
# The before-phase offer
# --------------------------------------------------------------------------- #

def test_before_phase_offers_fire():
    s = _market_state(wood=20)
    s = step(s, PlaceWorker(space="pig_market"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPigMarket) and top.phase == "before"
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


# --------------------------------------------------------------------------- #
# Firing grants a Build Fences action (normal wood cost), BEFORE the pigs
# --------------------------------------------------------------------------- #

def test_fire_grants_optional_build_fences_wrapper():
    s = _market_state(wood=20)
    s = step(s, PlaceWorker(space="pig_market"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    # The OPTIONAL grant wrapper lands on top of the (still-before-phase) market host.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrantedSubAction) and top.initiated_by_id == FRAME_ID
    assert top.subaction == "build_fences"
    assert isinstance(s.pending_stack[-2], PendingPigMarket)
    # It offers both opt-in and decline.
    la = legal_actions(s)
    assert any(isinstance(a, ChooseSubAction) and a.name == "build_fences" for a in la)
    assert any(isinstance(a, Stop) for a in la)


def test_build_pays_normal_wood_and_completes_before_pigs():
    s = _market_state(wood=20, accumulated=1)
    assert s.players[0].animals.boar == 0
    s = step(s, PlaceWorker(space="pig_market"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, ChooseSubAction(name="build_fences"))
    inner = s.pending_stack[-1]
    assert isinstance(inner, PendingBuildFences) and inner.initiated_by_id == FRAME_ID
    # A fresh corner 1x1 has 4 new edges; Trellis registers NO discount -> 4 wood accrued.
    s = step(s, CommitBuildPasture(cells=_1x1_03))
    assert s.pending_stack[-1].accrued_cost.wood == 4
    s = step(s, Proceed())                 # settle the build -> pays 4 wood
    assert _wood(s) == 16
    s = step(s, Stop())                    # pop the build host
    s = step(s, Stop())                    # pop the wrapper -> back to the market before-phase
    assert isinstance(s.pending_stack[-1], PendingPigMarket)
    # The boar is taken only NOW (a before-phase fire): a pasture exists before the pigs.
    assert s.players[0].farmyard.pastures, "the granted pasture was built"
    # Resolve the pig market to completion (single boar -> accommodate then exit).
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    assert s.players[0].animals.boar == 1   # the boar still arrives
    assert _wood(s) == 16                    # only the fence wood was spent


# --------------------------------------------------------------------------- #
# Optionality — the grant can be declined even when a build is possible
# --------------------------------------------------------------------------- #

def test_fire_then_decline_builds_nothing():
    s = _market_state(wood=20)
    s = step(s, PlaceWorker(space="pig_market"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert isinstance(s.pending_stack[-1], PendingGrantedSubAction)
    s = step(s, Stop())                    # decline the wrapper
    assert isinstance(s.pending_stack[-1], PendingPigMarket)
    assert not any(isinstance(f, (PendingGrantedSubAction, PendingBuildFences))
                   for f in s.pending_stack)
    assert _wood(s) == 20                   # nothing built, no wood spent
    assert not s.players[0].farmyard.pastures


def test_not_firing_is_declining():
    # The optionality IS the FireTrigger: not firing it (Proceed/accommodate the market) is
    # the decline — no build, full wood retained, the boar still arrives.
    s = _market_state(wood=20, accumulated=1)
    s = step(s, PlaceWorker(space="pig_market"))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    # Just resolve the market without firing.
    while s.pending_stack:
        la = legal_actions(s)
        a = next((x for x in la if not isinstance(x, FireTrigger)), la[0])
        s = step(s, a)
    assert _wood(s) == 20
    assert s.players[0].animals.boar == 1
    assert not s.players[0].farmyard.pastures


# --------------------------------------------------------------------------- #
# Once per use
# --------------------------------------------------------------------------- #

def test_once_per_use():
    # After firing once (and resolving the grant), the trigger is not re-offered within the
    # same Pig Market placement.
    s = _market_state(wood=20)
    s = step(s, PlaceWorker(space="pig_market"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, Stop())                    # decline the wrapper, back to the market
    assert isinstance(s.pending_stack[-1], PendingPigMarket)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# --------------------------------------------------------------------------- #
# Eligibility boundaries
# --------------------------------------------------------------------------- #

def test_no_fire_when_no_pasture_buildable():
    # 0 wood, fresh farmyard, no free fences -> nothing is buildable -> no dead-end FireTrigger.
    s = _market_state(wood=0)
    s = step(s, PlaceWorker(space="pig_market"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_unowned_player_gets_no_fire():
    # Pig Market still hosts (non-atomic), but the acting player doesn't own Trellis -> no fire.
    s = _market_state(wood=20, own=False)
    s = step(s, PlaceWorker(space="pig_market"))
    assert isinstance(s.pending_stack[-1], PendingPigMarket)   # always hosted
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_hand_card_does_not_fire():
    # A card in HAND (not played) cannot fire — only played cards do.
    s = _market_state(wood=20, own=False)
    p = fast_replace(s.players[0], hand_minors=s.players[0].hand_minors | {CARD_ID})
    s = fast_replace(s, players=(p, s.players[1]))
    s = step(s, PlaceWorker(space="pig_market"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_does_not_fire_on_other_market():
    # Trellis is scoped to Pig Market: it must not fire on Sheep Market.
    s = fast_replace(_fencing_setup(wood=20), mode=GameMode.CARDS)
    s = with_space(s, "sheep_market", revealed=True, accumulated_amount=1)
    s = _own(s, 0)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# --------------------------------------------------------------------------- #
# Family game is unaffected
# --------------------------------------------------------------------------- #

def test_family_pig_market_unaffected():
    # The cardless Family game never owns Trellis -> no host frame, byte-identical pig market.
    s = setup(0)
    s = with_space(s, "pig_market", revealed=True, accumulated_amount=1)
    s = step(s, PlaceWorker(space="pig_market"))
    assert not any(isinstance(f, PendingGrantedSubAction) for f in s.pending_stack)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
