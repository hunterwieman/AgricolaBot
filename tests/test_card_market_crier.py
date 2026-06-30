"""Tests for Market Crier (occupation, C142; Consul Dirigens Expansion).

Card text: "Each time you use the 'Grain Seeds' action space, you can get an
additional 1 grain and 1 vegetable. If you do, each other player gets 1 grain
from the general supply."

An OPTIONAL `before_action_space` trigger on the atomic Grain Seeds space (hosted
via register_action_space_hook). The fire surfaces as a declinable FireTrigger;
firing grants the owner +1 grain +1 veg AND the opponent +1 grain, coupled in a
single apply ("if you do, each other player gets..."). Mirrors
tests/test_card_brewing_water.py (the optional-FireTrigger / atomic-host shape) +
the Milk Jug "other = 1 - idx" two-sided grant.
"""
from __future__ import annotations

import agricola.cards.market_crier  # noqa: F401  (registers the card; not in cards/__init__)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    OWN_ACTION_HOOK_CARDS,
    TRIGGERS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env

CARD_ID = "market_crier"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, occupations=()):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _ready(seed=5, *, idx=0):
    """Player `idx` owns Market Crier and is the active player."""
    s = _own(_card_state(seed), idx, occupations=(CARD_ID,))
    return fast_replace(s, current_player=idx)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

def test_registered_as_occupation():
    assert CARD_ID in OCCUPATIONS


def test_on_play_is_a_noop():
    # The occupation's effect is the hook; on-play does nothing.
    s = _card_state()
    spec = OCCUPATIONS[CARD_ID]
    out = spec.on_play(s, 0)
    assert out == s


def test_registered_as_optional_trigger_and_hook():
    # Optional → it lives in TRIGGERS (the FireTrigger registry), not AUTO_EFFECTS.
    trig_ids = {e.card_id for e in TRIGGERS.get("before_action_space", ())}
    assert CARD_ID in trig_ids
    entry = next(e for e in TRIGGERS["before_action_space"] if e.card_id == CARD_ID)
    assert entry.mandatory is False        # declinable, not mandatory-with-choice
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["grain_seeds"]


def test_hosts_only_grain_seeds_when_owned():
    s = _own(_card_state(), 0, occupations=(CARD_ID,))
    assert should_host_space(s, "grain_seeds", 0)
    assert not should_host_space(s, "forest", 0)
    assert not should_host_space(s, "vegetable_seeds", 0)


# --------------------------------------------------------------------------- #
# The effect via a real engine flow
# --------------------------------------------------------------------------- #

def test_before_phase_offers_fire_or_decline():
    s = _ready()
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.pending_stack[-1].phase == "before"
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la   # optional fire surfaced
    assert Proceed() in la                       # declinable


def test_fire_grants_self_and_opponent():
    # Grain Seeds is a fixed-income space — its primary effect is a flat +1 grain
    # (collected at Proceed), not a fill-up accumulation slot.
    s = _ready()
    own_grain0 = s.players[0].resources.grain
    own_veg0 = s.players[0].resources.veg
    opp_grain0 = s.players[1].resources.grain
    opp_veg0 = s.players[1].resources.veg

    s = step(s, PlaceWorker(space="grain_seeds"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    # The fire records on the host but does not advance it; still the before phase,
    # exited only by Proceed (the trigger won't be re-offered). Then Stop.
    assert s.pending_stack[-1].phase == "before"
    s = step(s, Proceed())
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())
    assert not s.pending_stack

    p0, p1 = s.players[0], s.players[1]
    # Owner: +1 grain +1 veg from the fire, PLUS the space's own primary +1 grain
    # (before-phase fire, not instead-of — Proceed still collects the primary grain).
    assert p0.resources.grain == own_grain0 + 1 + 1
    assert p0.resources.veg == own_veg0 + 1
    # Opponent: +1 grain (from the general supply, not the owner), no veg.
    assert p1.resources.grain == opp_grain0 + 1
    assert p1.resources.veg == opp_veg0


def test_decline_grants_nothing_extra():
    s = _ready()
    own_grain0 = s.players[0].resources.grain
    own_veg0 = s.players[0].resources.veg
    opp_grain0 = s.players[1].resources.grain

    s = step(s, PlaceWorker(space="grain_seeds"))
    s = step(s, Proceed())                       # decline the fire
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())
    assert not s.pending_stack

    p0, p1 = s.players[0], s.players[1]
    # Owner gets only the space's primary +1 grain (no bonus grain, no veg).
    assert p0.resources.grain == own_grain0 + 1
    assert p0.resources.veg == own_veg0
    # Opponent gets nothing — the coupled grant did not fire.
    assert p1.resources.grain == opp_grain0


# --------------------------------------------------------------------------- #
# Eligibility boundaries
# --------------------------------------------------------------------------- #

def test_fire_offered_with_zero_grain():
    # No resource gate: the grant is a pure gain (the opponent's grain comes from
    # the general supply), so the fire is offered regardless of the owner's goods.
    s = _ready()
    p = fast_replace(s.players[0],
                     resources=fast_replace(s.players[0].resources, grain=0, veg=0))
    s = fast_replace(s, players=(p, s.players[1]))
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_once_per_use():
    # After firing once, the trigger is not re-offered within the same placement.
    s = _ready()
    s = step(s, PlaceWorker(space="grain_seeds"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert legal_actions(s) == [Proceed()]


def test_does_not_fire_on_other_space():
    # Vegetable Seeds is not hooked by Market Crier → atomic fast path, no host frame.
    s = _ready()
    assert not should_host_space(s, "vegetable_seeds", 0)
    out = step(s, PlaceWorker(space="vegetable_seeds"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)


def test_unowned_player_not_hosted():
    # Player 1 owns the card; player 0 (acting) does not → atomic grain_seeds, no host.
    s = _own(_card_state(), 1, occupations=(CARD_ID,))
    s = fast_replace(s, current_player=0)
    assert not should_host_space(s, "grain_seeds", 0)
    out = step(s, PlaceWorker(space="grain_seeds"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)


def test_hand_card_does_not_host():
    # A card in HAND (not played) must not host — only played occupations fire.
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_occupations=s.players[0].hand_occupations | {CARD_ID})
    s = fast_replace(s, players=(p, s.players[1]))
    assert not should_host_space(s, "grain_seeds", 0)


def test_family_grain_seeds_unaffected():
    # The cardless Family game never owns the card → atomic fast path, byte-identical.
    s = setup(0)
    s = step(s, PlaceWorker(space="grain_seeds"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
