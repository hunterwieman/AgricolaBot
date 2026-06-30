"""Tests for Private Teacher (occupation, C131) — the "each time you use Grain
Seeds while Lessons is occupied, you can also play an occupation for 1 food" grant.

Private Teacher is a Category-4 action-space-hook card on the (atomic) Grain Seeds
space: an OPTIONAL `before_action_space` trigger that, when fired, pushes the
standard `PendingPlayOccupation(cost=1 food)` play-card primitive. The grant is live
only when SOME worker sits on a Lessons space (a cross-space board read — in 2p the
firing player is on Grain Seeds, so it is the opponent's worker on Lessons) and the
owner has a playable, payable hand occupation. Decline = the host's Proceed; the
host's `triggers_resolved` gives once-per-placement semantics. On-play is a no-op.
"""
from __future__ import annotations

import agricola.cards.private_teacher  # noqa: F401  (fires register_* at import)

from agricola.actions import (
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    OWN_ACTION_HOOK_CARDS,
    TRIGGERS,
    should_host_space,
)
from agricola.constants import GameMode
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space

CARD_ID = "private_teacher"

_POOL = CardPool(
    occupations=("consultant", "private_teacher") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, occupations=(), hand=(), food=None):
    p = state.players[idx]
    changes = {
        "occupations": p.occupations | set(occupations),
        "hand_occupations": frozenset(hand),
    }
    if food is not None:
        changes["resources"] = fast_replace(p.resources, food=food)
    p = fast_replace(p, **changes)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _occupy_lessons(state, player=1):
    """Put `player`'s worker on the Lessons space."""
    sp = get_space(state.board, "lessons")
    workers = tuple(1 if i == player else 0 for i in range(2))
    return fast_replace(state, board=with_space(
        state.board, "lessons", fast_replace(sp, workers=workers)))


def _at_grain_seeds(seed=5, *, ap=0, hand=("consultant",), food=1, lessons=True):
    """Own Private Teacher (+ a hand occupation + food), occupy Lessons with the
    opponent, then place `ap` on Grain Seeds (its host)."""
    s = fast_replace(_card_state(seed), current_player=ap)
    s = _own(s, ap, occupations=(CARD_ID,), hand=hand, food=food)
    if lessons:
        s = _occupy_lessons(s, player=1 - ap)
    s = step(s, PlaceWorker(space="grain_seeds"))
    return s, ap


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_private_teacher_registered():
    assert CARD_ID in OCCUPATIONS
    bas = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert CARD_ID in bas
    # Hooks the (atomic) Grain Seeds space so a host frame is pushed there.
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("grain_seeds", set())


def test_on_play_is_noop():
    # Playing the occupation has no immediate effect (it only grants a trigger).
    s = _card_state()
    s = _own(s, 0, occupations=(CARD_ID,))
    spec = OCCUPATIONS[CARD_ID]
    res0 = s.players[0].resources
    out = spec.on_play(s, 0)
    assert out.players[0].resources == res0


# ---------------------------------------------------------------------------
# Hosting — Grain Seeds is hosted only for an owner
# ---------------------------------------------------------------------------

def test_grain_seeds_hosted_only_for_owner():
    s = _card_state()
    # No owner → atomic fast path (no host).
    assert not should_host_space(s, "grain_seeds", 0)
    s = _own(s, 0, occupations=(CARD_ID,))
    assert should_host_space(s, "grain_seeds", 0)
    # The opponent (who doesn't own it) still gets no host on their own use.
    assert not should_host_space(s, "grain_seeds", 1)


def test_placing_on_grain_seeds_pushes_host_frame():
    s, ap = _at_grain_seeds()
    top = s.pending_stack[-1]
    assert isinstance(top, PendingActionSpace)
    assert top.space_id == "grain_seeds" and top.phase == "before"


# ---------------------------------------------------------------------------
# The grant is surfaced and works
# ---------------------------------------------------------------------------

def test_grant_surfaced_when_lessons_occupied():
    s, ap = _at_grain_seeds()
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la            # optional → decline is the host's Proceed


def test_fire_pushes_play_occupation_with_one_food_cost():
    s, ap = _at_grain_seeds()
    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)
    assert top.player_idx == ap
    assert top.cost == Resources(food=1)
    assert legal_actions(s) == [CommitPlayOccupation(card_id="consultant")]


def test_full_flow_plays_occupation_and_debits_food():
    s, ap = _at_grain_seeds(food=1)
    grain0 = s.players[ap].resources.grain
    assert s.players[ap].resources.clay == 0

    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitPlayOccupation(card_id="consultant"))
    p = s.players[ap]
    assert "consultant" in p.occupations             # moved to tableau
    assert "consultant" not in p.hand_occupations     # removed from hand
    assert p.resources.clay == 3                       # consultant's 2p on-play
    assert p.resources.food == 0                       # 1-food occupation cost debited

    # Finish: pop the play-occupation after-phase, then run out the grain_seeds host.
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    # Grain Seeds still pays out its grain (the grant fired BEFORE the space effect).
    assert s.players[ap].resources.grain == grain0 + 1


def test_grain_seeds_still_pays_after_decline():
    s, ap = _at_grain_seeds()
    grain0 = s.players[ap].resources.grain
    food0 = s.players[ap].resources.food
    s = step(s, Proceed())   # decline the grant; applies Grain Seeds
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    assert s.players[ap].resources.grain == grain0 + 1
    assert "consultant" not in s.players[ap].occupations  # nothing played
    assert s.players[ap].resources.food == food0           # no food spent


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_when_lessons_unoccupied():
    s, ap = _at_grain_seeds(lessons=False)
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert la == [Proceed()]          # host still pushed (owner), only Proceed


def test_not_offered_with_empty_hand():
    s, ap = _at_grain_seeds(hand=())
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert la == [Proceed()]


def test_not_offered_with_only_unregistered_hand_occupation():
    # An as-yet-unimplemented occupation in hand is not playable → grant withheld.
    s, ap = _at_grain_seeds(hand=("o3",))
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert la == [Proceed()]


def test_not_offered_when_cannot_pay_food():
    # No food and nothing to liquidate → the flat 1-food cost is unpayable.
    s, ap = _at_grain_seeds(food=0)
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert la == [Proceed()]


# ---------------------------------------------------------------------------
# Once-per-placement scoping
# ---------------------------------------------------------------------------

def test_grant_not_reoffered_after_firing():
    s, ap = _at_grain_seeds()
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitPlayOccupation(card_id="consultant"))
    s = step(s, Stop())   # pop the play-occupation after-phase → back at grain_seeds host
    # Once per placement: the grant is no longer offered (triggers_resolved).
    la = legal_actions(s)
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID for a in la)
    assert Proceed() in la


# ---------------------------------------------------------------------------
# Family game untouched
# ---------------------------------------------------------------------------

def test_family_game_grain_seeds_stays_atomic():
    s = setup(5)
    assert s.mode is GameMode.FAMILY
    # No card is owned in Family → Grain Seeds is never hosted (byte-identical path).
    assert not should_host_space(s, "grain_seeds", 0)
    s = fast_replace(s, current_player=0)
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert s.pending_stack == ()      # atomic: resolved with no host frame
