"""Tests for Small Basket (minor improvement, D68; Dulcinaria Expansion; Crop
Provider; prereq 2 Occupations).

Card text: "Each time you use the "Reed Bank" accumulation space, you can pay 1
reed to get 1 vegetable. If you do in a game with 4+ players, place that 1 reed on
the accumulation space."
Cost: none. Prereq: 2 Occupations. VPs: 0. Not passing.

Shape: an OPTIONAL `before_action_space` FireTrigger on the atomic-hosted Reed Bank
accumulation space. Owning the card gives Reed Bank a PendingActionSpace host; in
the host's before-phase the trigger is surfaced (alongside Proceed) iff the player
has >=1 reed to pay. Firing is a direct goods swap (-1 reed, +1 vegetable; no
pending pushed). The "place that 1 reed on the accumulation space" clause is
4+-player-only, so in the 2-player engine the reed is simply spent — no space
reed-return. Declining is not firing — Proceed exits the before-phase, picks up the
+1 reed Reed Bank accumulated, then Stop pops. Tests drive the REAL engine flow
through the Reed Bank placement, per CARD_AUTHORING_GUIDE §5. Mirrors
test_card_truffle_slicer.py (the optional before_action_space conversion shape) and
test_card_brewery_pond.py (the Reed Bank host).
"""
from __future__ import annotations

import agricola.cards.small_basket  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.small_basket import CARD_ID, _eligible
from agricola.cards.specs import MINORS, OCCUPATIONS, prereq_met
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    TRIGGERS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _setup(*, reed=2, idx=0, seed=5):
    """Own the card, set reed on hand, P0 to move."""
    s, cp = _card_state(seed)
    assert cp == idx
    s = _own_minor(s, idx)
    s = with_resources(s, idx, reed=reed)
    return s, idx


def _place_reed_bank_before(state):
    """Place P0 at Reed Bank; the host frame should be in its before-phase (where a
    before-trigger is surfaced). Returns the before-phase state."""
    state = step(state, PlaceWorker(space="reed_bank"))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    return state


def _has_fire(state):
    return FireTrigger(card_id=CARD_ID) in legal_actions(state)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    assert CARD_ID not in OCCUPATIONS               # it is a minor, not an occupation
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                      # no printed cost
    assert spec.cost.animals == Animals()
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.min_occupations == 2                # "2 Occupations" prerequisite
    # Optional (not automatic) before_action_space trigger + an atomic Reed Bank host.
    before = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert CARD_ID in before
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD_ID not in auto_ids                  # optional, NOT register_auto
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("reed_bank", set())


def test_prereq_requires_two_occupations():
    s, cp = _card_state()
    spec = MINORS[CARD_ID]
    # 0 occupations → prereq fails.
    assert not prereq_met(spec, s, cp)
    # exactly 2 → prereq met.
    p = fast_replace(s.players[cp], occupations=s.players[cp].occupations | {"oa", "ob"})
    s2 = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    assert prereq_met(spec, s2, cp)


# ---------------------------------------------------------------------------
# The effect via the real engine flow
# ---------------------------------------------------------------------------

def test_fire_pays_reed_for_vegetable():
    s, cp = _setup(reed=2)
    s = _place_reed_bank_before(s)
    assert _has_fire(s)
    reed_before = s.players[cp].resources.reed
    veg_before = s.players[cp].resources.veg

    s = step(s, FireTrigger(card_id=CARD_ID))

    assert s.players[cp].resources.reed == reed_before - 1      # paid 1 reed
    assert s.players[cp].resources.veg == veg_before + 1        # got 1 vegetable

    # The 4+-player reed-return clause is inert in 2p: Reed Bank's accumulated reed is
    # unchanged by the fire (it is collected later, by Proceed).
    assert get_space(s.board, "reed_bank").accumulated.reed == 1

    # Firing pushes no sub-decision; the host is back at its before-phase with the
    # trigger resolved, so the only exit is Proceed.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.pending_stack[-1].phase == "before"
    assert not _has_fire(s)
    assert Proceed() in legal_actions(s)

    # Proceed picks up Reed Bank's accumulated +1 reed and flips to after; then Stop pops.
    reed_at_proceed = s.players[cp].resources.reed
    s = step(s, Proceed())
    assert s.players[cp].resources.reed == reed_at_proceed + 1  # the space's own pickup
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())
    assert not s.pending_stack                                  # Reed Bank use complete


def test_effect_repeats_across_multiple_reed_bank_uses():
    # Two SEPARATE Reed Bank uses (the trigger fires at most once per use, but again
    # on a fresh use) each convert a reed.
    s, cp = _setup(reed=5)
    # First use: fire, then proceed (picks up +1 reed), stop.
    s = _place_reed_bank_before(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[cp].resources.veg == 1
    s = step(s, Proceed())
    s = step(s, Stop())
    # Manually re-open Reed Bank (clear the worker so it's placeable again) and re-use.
    sp = fast_replace(get_space(s.board, "reed_bank"), workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "reed_bank", sp), current_player=cp)
    s = _place_reed_bank_before(s)
    assert _has_fire(s)                              # offered again on the new use
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[cp].resources.veg == 2          # converted again


# ---------------------------------------------------------------------------
# Once-per-use scoping
# ---------------------------------------------------------------------------

def test_fires_once_per_use():
    s, cp = _setup(reed=5)
    s = _place_reed_bank_before(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    # Already fired this host-visit → not re-offered even with reed remaining.
    assert s.players[cp].resources.reed >= 1
    assert not _has_fire(s)
    assert s.players[cp].resources.veg == 1          # only one conversion this use


# ---------------------------------------------------------------------------
# Optionality — declining = not firing
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_proceed():
    s, cp = _setup(reed=2)
    s = _place_reed_bank_before(s)
    la = legal_actions(s)
    # Both firing AND the host's Proceed (decline) are available — optionality lives
    # at the FireTrigger.
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la
    reed_before = s.players[cp].resources.reed
    veg_before = s.players[cp].resources.veg
    s = step(s, Proceed())                          # decline → +1 reed, flip to after
    assert s.players[cp].resources.reed == reed_before + 1      # only the space's reed
    assert s.players[cp].resources.veg == veg_before           # no vegetable gained
    s = step(s, Stop())
    assert not s.pending_stack


# ---------------------------------------------------------------------------
# Eligibility boundaries (never a dead-end)
# ---------------------------------------------------------------------------

def test_not_offered_without_reed():
    # 0 reed to pay → not offered (no dead-end).
    s, cp = _setup(reed=0)
    s = _place_reed_bank_before(s)
    assert s.players[cp].resources.reed == 0
    assert not _has_fire(s)


def test_not_offered_without_card():
    # Without the card, Reed Bank is NOT hosted (atomic fast path): placing resolves
    # immediately, no host frame, no trigger.
    s, cp = _card_state()
    s = with_resources(s, cp, reed=2)
    reed_before = s.players[cp].resources.reed
    s = step(s, PlaceWorker(space="reed_bank"))
    assert not s.pending_stack                      # resolved atomically
    # Reed Bank's own +1 reed is collected; no conversion happened.
    assert s.players[cp].resources.reed == reed_before + 1
    assert s.players[cp].resources.veg == 0


def test_eligible_predicate_direct():
    # Direct unit checks of _eligible across the boundaries, at a Reed Bank host.
    s, cp = _setup(reed=2)
    s = _place_reed_bank_before(s)
    triggers_resolved = s.pending_stack[-1].triggers_resolved
    assert _eligible(s, cp, triggers_resolved)                  # reed + fresh
    assert not _eligible(s, cp, frozenset({CARD_ID}))           # already fired this use
    # No reed → not eligible.
    s_noreed = with_resources(s, cp, reed=0)
    assert not _eligible(s_noreed, cp, triggers_resolved)


# ---------------------------------------------------------------------------
# Wrong space does not fire
# ---------------------------------------------------------------------------

def test_clay_pit_does_not_fire():
    # Clay Pit accumulates CLAY — Small Basket is not hooked on it, so it stays
    # atomic (no host) and nothing converts.
    s, cp = _setup(reed=2)
    sp = fast_replace(get_space(s.board, "clay_pit"), revealed=True, workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "clay_pit", sp))
    s = step(s, PlaceWorker(space="clay_pit"))
    assert not s.pending_stack                      # not hosted → resolves atomically
    assert s.players[cp].resources.veg == 0


# ---------------------------------------------------------------------------
# Hosting boundaries
# ---------------------------------------------------------------------------

def test_not_hosted_without_card():
    s, _ = _card_state()
    assert not should_host_space(s, "reed_bank", s.current_player)


def test_hosted_when_owned():
    s, cp = _setup(reed=2)
    assert should_host_space(s, "reed_bank", cp)
    assert not should_host_space(s, "forest", cp)   # not a hooked space


def test_hand_card_does_not_host():
    # A card in HAND (not played) must not host — only played cards fire.
    s, cp = _card_state()
    p = fast_replace(s.players[cp], hand_minors=s.players[cp].hand_minors | {CARD_ID})
    s = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    assert not should_host_space(s, "reed_bank", cp)


# ---------------------------------------------------------------------------
# Family game: byte-identical (the card is never owned)
# ---------------------------------------------------------------------------

def test_family_reed_bank_not_hosted():
    s = setup(0)
    s = step(s, PlaceWorker(space="reed_bank"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
