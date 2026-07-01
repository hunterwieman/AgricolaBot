"""Tests for Truffle Slicer (minor improvement, D39; Consul Dirigens Expansion).

Card text: "Each time you use a wood accumulation space, if you have at least 1
wild boar, you can pay 1 food for 1 bonus point."
Cost: 1 wood. Prereq: "Play in Round 8 or Later". VPs: 0 (the bonus point is
banked, not printed). Not passing.

Shape: an OPTIONAL `before_action_space` FireTrigger on the atomic-hosted Forest
(the only wood accumulation space on the 2-player board). Owning the card gives
Forest a PendingActionSpace host; in the host's before-phase the trigger is
surfaced (alongside Proceed) iff the player has >=1 wild boar and >=1 food. Firing
pays 1 food for 1 BANKED bonus point (stored in the per-card CardStore, emitted by
register_scoring at end-game). Declining is not firing — Proceed exits the
before-phase, picks up the +3 wood, then Stop pops. Tests drive the REAL engine
flow through the Forest placement, per CARD_AUTHORING_GUIDE §5.
"""
from __future__ import annotations

import agricola.cards.truffle_slicer  # noqa: F401  (registers the card)

from agricola.actions import (
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS, OCCUPATIONS, prereq_met
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.cards.truffle_slicer import CARD_ID, _eligible, _score
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_animals, with_resources, with_round

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


def _setup(*, boar=1, food=1, idx=0, seed=5):
    """Own the card, set wild boar + food, P0 to move."""
    s, cp = _card_state(seed)
    assert cp == idx
    s = _own_minor(s, idx)
    s = with_animals(s, idx, boar=boar)
    s = with_resources(s, idx, food=food)
    return s, idx


def _place_forest_before(state):
    """Place P0 at Forest; the host frame should be in its before-phase (where a
    before-trigger is surfaced). Returns the before-phase state."""
    state = step(state, PlaceWorker(space="forest"))
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
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.cost.animals == Animals()
    assert spec.vps == 0                            # bonus point is banked, not printed
    assert spec.passing_left is False
    # Optional before_action_space trigger + an atomic Forest host.
    before = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert CARD_ID in before
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("forest", set())


def test_prereq_round_8_or_later():
    s, cp = _card_state()
    spec = MINORS[CARD_ID]
    assert not prereq_met(spec, with_round(s, 7), cp)   # round 7 → too early
    assert prereq_met(spec, with_round(s, 8), cp)       # round 8 → exactly meets
    assert prereq_met(spec, with_round(s, 12), cp)      # later → still meets


# ---------------------------------------------------------------------------
# The effect via the real engine flow
# ---------------------------------------------------------------------------

def test_fire_pays_food_for_banked_point():
    s, cp = _setup(boar=1, food=3)
    s = _place_forest_before(s)
    assert _has_fire(s)
    food_before = s.players[cp].resources.food
    assert s.players[cp].card_state.get(CARD_ID, 0) == 0

    s = step(s, FireTrigger(card_id=CARD_ID))

    assert s.players[cp].resources.food == food_before - 1     # paid 1 food
    assert s.players[cp].card_state.get(CARD_ID) == 1          # 1 point banked
    assert _score(s, cp) == 1

    # Firing pushes no sub-decision; the host is back at its before-phase with the
    # trigger resolved, so the only exit is Proceed.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.pending_stack[-1].phase == "before"
    assert not _has_fire(s)
    assert Proceed() in legal_actions(s)

    # Proceed picks up Forest's +3 wood and flips to after; then Stop pops.
    wood_before = s.players[cp].resources.wood
    s = step(s, Proceed())
    assert s.players[cp].resources.wood == wood_before + 3     # the space's own pickup
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())
    assert not s.pending_stack                                  # Forest use complete


def test_score_accumulates_across_multiple_forest_uses():
    # Two SEPARATE Forest uses (the trigger fires at most once per use, but again on
    # a fresh use) accumulate the bank.
    s, cp = _setup(boar=1, food=5)
    # First use.
    s = _place_forest_before(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, Proceed())
    s = step(s, Stop())
    assert _score(s, cp) == 1
    # Manually re-open Forest (clear the worker so it's placeable again) and re-use.
    sp = fast_replace(get_space(s.board, "forest"), workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "forest", sp), current_player=cp)
    s = _place_forest_before(s)
    assert _has_fire(s)                              # offered again on the new use
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert _score(s, cp) == 2                        # banked again


# ---------------------------------------------------------------------------
# Once-per-use scoping
# ---------------------------------------------------------------------------

def test_fires_once_per_use():
    s, cp = _setup(boar=1, food=5)
    s = _place_forest_before(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    # Already fired this host-visit → not re-offered even with boar + food remaining.
    assert s.players[cp].animals.boar >= 1
    assert s.players[cp].resources.food >= 1
    assert not _has_fire(s)
    assert _score(s, cp) == 1


# ---------------------------------------------------------------------------
# Optionality — declining = not firing
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_proceed():
    s, cp = _setup(boar=1, food=3)
    s = _place_forest_before(s)
    la = legal_actions(s)
    # Both firing AND the host's Proceed (decline) are available — optionality lives
    # at the FireTrigger.
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la
    food_before = s.players[cp].resources.food
    s = step(s, Proceed())                          # decline → +3 wood, flip to after
    assert s.players[cp].resources.food == food_before          # no food spent
    assert _score(s, cp) == 0                                   # no point banked
    s = step(s, Stop())
    assert not s.pending_stack


# ---------------------------------------------------------------------------
# Eligibility boundaries (never a dead-end)
# ---------------------------------------------------------------------------

def test_not_offered_without_boar():
    # No wild boar → the card text's condition fails → not offered.
    s, cp = _setup(boar=0, food=3)
    s = _place_forest_before(s)
    assert s.players[cp].animals.boar == 0
    assert not _has_fire(s)


def test_not_offered_without_food():
    # Boar present but 0 food to pay → not offered (no dead-end).
    s, cp = _setup(boar=1, food=0)
    s = _place_forest_before(s)
    assert s.players[cp].resources.food == 0
    assert not _has_fire(s)


def test_not_offered_without_card():
    # Without the card, Forest is NOT hosted (atomic fast path): placing resolves
    # immediately, no host frame, no trigger.
    s, cp = _card_state()
    s = with_animals(s, cp, boar=1)
    s = with_resources(s, cp, food=3)
    s = step(s, PlaceWorker(space="forest"))
    assert not s.pending_stack                      # resolved atomically
    assert s.players[cp].resources.food == 3        # untouched


def test_eligible_predicate_direct():
    # Direct unit checks of _eligible across the boundaries, at a Forest host.
    s, cp = _setup(boar=1, food=3)
    s = _place_forest_before(s)
    triggers_resolved = s.pending_stack[-1].triggers_resolved
    assert _eligible(s, cp, triggers_resolved)                  # boar + food + fresh
    assert not _eligible(s, cp, frozenset({CARD_ID}))           # already fired this use
    # No boar → not eligible.
    s_noboar = with_animals(s, cp, boar=0)
    assert not _eligible(s_noboar, cp, triggers_resolved)
    # No food → not eligible.
    s_nofood = with_resources(s, cp, food=0)
    assert not _eligible(s_nofood, cp, triggers_resolved)


# ---------------------------------------------------------------------------
# Wrong space does not fire
# ---------------------------------------------------------------------------

def test_clay_pit_does_not_fire():
    # Clay Pit accumulates CLAY (not wood) — Truffle Slicer is not hooked on it, so
    # it stays atomic (no host) and nothing fires.
    s, cp = _setup(boar=1, food=3)
    sp = fast_replace(get_space(s.board, "clay_pit"), revealed=True, workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "clay_pit", sp))
    s = step(s, PlaceWorker(space="clay_pit"))
    assert not s.pending_stack                      # not hosted → resolves atomically
    assert _score(s, cp) == 0
