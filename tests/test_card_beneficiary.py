"""Tests for Beneficiary (occupation, E #97) — the conditional occ-and/or-minor grant.

Card text: "If this is your 3rd occupation, you can immediately play another occupation
for an occupation cost of 1 food and/or play 1 minor improvement by paying its cost."

User design (2026-07-14, deep not wide): play the card, then offer the occ/minor/proceed
option, then offer cards of the relevant type, then offer the occ/minor/proceed option
(with either occ or minor no longer available), then end.

The tests drive the real engine flow: a `PendingPlayOccupation` host (as Lessons pushes it)
is seeded on the stack, Beneficiary is played through `CommitPlayOccupation`, and the granted
multi-category `PendingGrantedSubAction` wrapper is exercised — both orders, at most one of
each, decline, per-branch dead cases, and the not-pushed cases. Synthetic no-op filler cards
are registered test-scoped (the try/finally pattern from test_card_host_enforce_first.py) so
the granted plays have controlled targets: two no-op occupations and a 1-clay minor (clay is
NOT liquidatable to food, so the minor's affordability never bleeds into the occupation
branch's food gate).
"""
import agricola.cards.beneficiary  # noqa: F401

from contextlib import contextmanager

from agricola.actions import ChooseSubAction, CommitPlayOccupation, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingGrantedSubAction,
    PendingPlayMinor,
    PendingPlayOccupation,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

_OCC_A = "test_bene_occ_a"
_OCC_B = "test_bene_occ_b"
_MINOR = "test_bene_minor"          # cost 1 clay (clay never liquidates to food)

_CHOOSE_OCC = ChooseSubAction(name="play_occupation")
_CHOOSE_MINOR = ChooseSubAction(name="play_minor")

_POOL = CardPool(
    occupations=("beneficiary",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


@contextmanager
def _filler_cards():
    """Test-scoped no-op targets for the granted plays: two occupations and a
    1-clay minor (registered here, removed on exit)."""
    from agricola.cards.specs import MINORS, register_minor, register_occupation

    register_occupation(_OCC_A, lambda state, idx: state)
    register_occupation(_OCC_B, lambda state, idx: state)
    register_minor(_MINOR, cost=Cost(resources=Resources(clay=1)))
    try:
        yield
    finally:
        OCCUPATIONS.pop(_OCC_A, None)
        OCCUPATIONS.pop(_OCC_B, None)
        MINORS.pop(_MINOR, None)


def _state(*, prior_occs=2, hand_occs=("beneficiary", _OCC_A),
           hand_minors=(_MINOR,), res=Resources(food=2, clay=1)):
    """A 2-player card-mode state at a PendingPlayOccupation host (as Lessons pushes
    it — Beneficiary's play costs 1 food, the 2nd+ occupation rate) with `prior_occs`
    occupations already in the tableau and the given hand + resources."""
    cs, _env = setup_env(7, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        occupations=frozenset(f"prior{i}" for i in range(prior_occs)),
        hand_occupations=frozenset(hand_occs),
        hand_minors=frozenset(hand_minors),
        resources=res,
    )
    opp = fast_replace(cs.players[1 - cp],
                       hand_occupations=frozenset(), hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(cs, (PendingPlayOccupation(
        player_idx=cp, initiated_by_id="space:lessons", cost=Resources(food=1)),))
    return cs, cp


def _play_beneficiary(cs):
    commit = CommitPlayOccupation(card_id="beneficiary")
    assert commit in legal_actions(cs)
    return step(cs, commit)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_beneficiary_registered():
    assert "beneficiary" in OCCUPATIONS


# ---------------------------------------------------------------------------
# The 3rd-occupation condition — no frame when played 2nd or 4th
# ---------------------------------------------------------------------------

def test_no_frame_when_played_second():
    with _filler_cards():
        cs, cp = _state(prior_occs=1)
        cs = _play_beneficiary(cs)
        assert "beneficiary" in cs.players[cp].occupations
        assert not any(isinstance(f, PendingGrantedSubAction) for f in cs.pending_stack)
        # No grant pushed -> the play host has flipped straight to its after-phase.
        assert cs.pending_stack[-1].PENDING_ID == "play_occupation"
        assert cs.pending_stack[-1].phase == "after"


def test_no_frame_when_played_fourth():
    with _filler_cards():
        cs, cp = _state(prior_occs=3)
        cs = _play_beneficiary(cs)
        assert not any(isinstance(f, PendingGrantedSubAction) for f in cs.pending_stack)


# ---------------------------------------------------------------------------
# 3rd occupation, both branches live: the wrapper and its offers
# ---------------------------------------------------------------------------

def test_third_occupation_pushes_wrapper_offering_both():
    with _filler_cards():
        cs, cp = _state()
        cs = _play_beneficiary(cs)
        top = cs.pending_stack[-1]
        assert isinstance(top, PendingGrantedSubAction)
        assert top.initiated_by_id == "card:beneficiary"
        assert top.subactions == ("play_occupation", "play_minor")
        assert top.occ_cost == Resources(food=1)
        # Deferred after-flip (ruling 60): the play host beneath is still before-phase.
        host = cs.pending_stack[-2]
        assert host.PENDING_ID == "play_occupation" and host.phase == "before"
        la = legal_actions(cs)
        assert _CHOOSE_OCC in la
        assert _CHOOSE_MINOR in la
        assert Stop() in la


def test_occ_then_minor_end_to_end():
    with _filler_cards():
        # food=2: 1 pays Beneficiary's own play, 1 pays the granted occupation.
        cs, cp = _state()
        cs = _play_beneficiary(cs)
        assert cs.players[cp].resources.food == 1     # Beneficiary's play cost paid
        # Take the occupation branch: the pushed host carries the 1-food grant cost.
        cs = step(cs, _CHOOSE_OCC)
        inner = cs.pending_stack[-1]
        assert isinstance(inner, PendingPlayOccupation)
        assert inner.initiated_by_id == "card:beneficiary"
        assert inner.cost == Resources(food=1)
        cs = step(cs, CommitPlayOccupation(card_id=_OCC_A))
        assert cs.players[cp].resources.food == 0     # exactly 1 food charged
        assert _OCC_A in cs.players[cp].occupations
        cs = step(cs, Stop())                          # pop the inner host's after-phase
        # Back at the wrapper: occupation spent, minor still offered.
        top = cs.pending_stack[-1]
        assert isinstance(top, PendingGrantedSubAction)
        assert top.chosen == frozenset({"play_occupation"})
        la = legal_actions(cs)
        assert _CHOOSE_OCC not in la
        assert _CHOOSE_MINOR in la
        # Take the minor branch: pays its printed cost (1 clay).
        cs = step(cs, _CHOOSE_MINOR)
        assert isinstance(cs.pending_stack[-1], PendingPlayMinor)
        cs = step(cs, sole_play_minor(cs, _MINOR))
        assert cs.players[cp].resources.clay == 0     # printed cost paid
        assert _MINOR in cs.players[cp].minor_improvements
        cs = step(cs, Stop())                          # pop the minor host's after-phase
        # Both taken: only Stop remains.
        top = cs.pending_stack[-1]
        assert isinstance(top, PendingGrantedSubAction)
        assert top.chosen == frozenset({"play_occupation", "play_minor"})
        assert legal_actions(cs) == [Stop()]
        cs = step(cs, Stop())                          # pop the wrapper
        # Deferred after-flip: the whole granted chain resolved -> host flips.
        host = cs.pending_stack[-1]
        assert host.PENDING_ID == "play_occupation" and host.phase == "after"
        cs = step(cs, Stop())                          # pop the play host
        assert not any(isinstance(f, PendingGrantedSubAction) for f in cs.pending_stack)


def test_minor_then_occ_other_order():
    with _filler_cards():
        cs, cp = _state()
        cs = _play_beneficiary(cs)
        cs = step(cs, _CHOOSE_MINOR)
        # Beneficiary lets you PLAY a minor; it is NOT the named "Minor Improvement"
        # action, so the pushed frame carries the flag False (must not chain Merchant
        # / enable Blueprint). User ruling 2026-07-15.
        assert cs.pending_stack[-1].minor_improvement_action is False
        cs = step(cs, sole_play_minor(cs, _MINOR))
        cs = step(cs, Stop())
        top = cs.pending_stack[-1]
        assert isinstance(top, PendingGrantedSubAction)
        assert top.chosen == frozenset({"play_minor"})
        la = legal_actions(cs)
        assert _CHOOSE_MINOR not in la     # at most one minor
        assert _CHOOSE_OCC in la           # the occupation is still available
        cs = step(cs, _CHOOSE_OCC)
        cs = step(cs, CommitPlayOccupation(card_id=_OCC_A))
        cs = step(cs, Stop())
        assert _OCC_A in cs.players[cp].occupations
        assert _MINOR in cs.players[cp].minor_improvements
        assert legal_actions(cs) == [Stop()]


def test_at_most_one_occupation_even_with_more_in_hand():
    with _filler_cards():
        # Two playable filler occupations in hand + plenty of food: after ONE granted
        # occupation play, play_occupation is spent — not re-offered for the second.
        cs, cp = _state(hand_occs=("beneficiary", _OCC_A, _OCC_B),
                        res=Resources(food=5, clay=1))
        cs = _play_beneficiary(cs)
        cs = step(cs, _CHOOSE_OCC)
        cs = step(cs, CommitPlayOccupation(card_id=_OCC_A))
        cs = step(cs, Stop())
        la = legal_actions(cs)
        assert _CHOOSE_OCC not in la
        assert _CHOOSE_MINOR in la
        assert Stop() in la


# ---------------------------------------------------------------------------
# Optionality — immediate decline takes nothing
# ---------------------------------------------------------------------------

def test_immediate_decline_takes_nothing():
    with _filler_cards():
        cs, cp = _state()
        cs = _play_beneficiary(cs)
        food0 = cs.players[cp].resources.food
        clay0 = cs.players[cp].resources.clay
        cs = step(cs, Stop())              # decline the whole grant
        assert cs.players[cp].resources.food == food0
        assert cs.players[cp].resources.clay == clay0
        assert _OCC_A not in cs.players[cp].occupations
        assert _MINOR not in cs.players[cp].minor_improvements
        assert _MINOR in cs.players[cp].hand_minors
        # The wrapper popped; the play host flips and Stop ends the turn cleanly.
        host = cs.pending_stack[-1]
        assert host.PENDING_ID == "play_occupation" and host.phase == "after"


# ---------------------------------------------------------------------------
# Per-branch dead cases — only the live branch is offered
# ---------------------------------------------------------------------------

def test_occ_branch_dead_without_food():
    with _filler_cards():
        # food=1 exactly pays Beneficiary's own play; nothing liquidatable remains,
        # so the granted occupation's 1 food is unpayable -> only the minor offered.
        cs, cp = _state(res=Resources(food=1, clay=1))
        cs = _play_beneficiary(cs)
        assert cs.players[cp].resources.food == 0
        assert isinstance(cs.pending_stack[-1], PendingGrantedSubAction)
        la = legal_actions(cs)
        assert _CHOOSE_OCC not in la
        assert _CHOOSE_MINOR in la
        assert Stop() in la


def test_occ_branch_dead_without_hand_occupation():
    with _filler_cards():
        # Food is there but the hand has no other occupation -> only the minor offered.
        cs, cp = _state(hand_occs=("beneficiary",))
        cs = _play_beneficiary(cs)
        assert isinstance(cs.pending_stack[-1], PendingGrantedSubAction)
        la = legal_actions(cs)
        assert _CHOOSE_OCC not in la
        assert _CHOOSE_MINOR in la


def test_minor_branch_dead_without_playable_minor():
    with _filler_cards():
        # No clay -> the 1-clay minor is unaffordable -> only the occupation offered.
        cs, cp = _state(res=Resources(food=2))
        cs = _play_beneficiary(cs)
        assert isinstance(cs.pending_stack[-1], PendingGrantedSubAction)
        la = legal_actions(cs)
        assert _CHOOSE_OCC in la
        assert _CHOOSE_MINOR not in la


def test_frame_not_pushed_when_neither_branch_live():
    with _filler_cards():
        # 3rd occupation, but: no food left after the play (occ branch dead) and no
        # affordable minor (no clay) -> the wrapper is not pushed at all.
        cs, cp = _state(res=Resources(food=1))
        cs = _play_beneficiary(cs)
        assert "beneficiary" in cs.players[cp].occupations
        assert not any(isinstance(f, PendingGrantedSubAction) for f in cs.pending_stack)
        assert cs.pending_stack[-1].PENDING_ID == "play_occupation"
        assert cs.pending_stack[-1].phase == "after"
