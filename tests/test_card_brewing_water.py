"""Tests for Brewing Water (minor improvement, B60; Bubulcus Expansion).

Card text: "Each time you use the 'Fishing' accumulation space, you can pay 1 grain
to place 1 food on each of the next 6 round spaces. At the start of these rounds,
you get the food."

An OPTIONAL, cost-bearing `before_action_space` trigger on the atomic Fishing space
(hosted via register_action_space_hook). The fire surfaces as a declinable
FireTrigger; firing debits 1 grain and schedules +1 food onto each of the next 6
round spaces (R+1..R+6). Mirrors tests/test_card_drift_net_boat.py (the fishing-hook
shape) + tests/test_card_chain_float.py (the optional FireTrigger / decline flow).
"""
from __future__ import annotations

import agricola.cards.brewing_water  # noqa: F401  (registers the card; not in cards/__init__)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import (
    OWN_ACTION_HOOK_CARDS,
    TRIGGERS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space

CARD_ID = "brewing_water"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, minors=()):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | set(minors))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_resources(state, idx, **kw):
    p = fast_replace(state.players[idx],
                     resources=fast_replace(state.players[idx].resources, **kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _ready(seed=5, *, idx=0, grain=1, round_number=3):
    """P `idx` owns Brewing Water, has `grain` grain, acting in `round_number`."""
    s = _own(_card_state(seed), idx, minors=(CARD_ID,))
    s = fast_replace(s, current_player=idx, round_number=round_number)
    return _set_resources(s, idx, grain=grain)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

def test_registered_as_free_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()             # free build
    assert spec.prereq is None
    assert spec.min_occupations == 0
    assert spec.vps == 0
    assert spec.passing_left is False


def test_registered_as_optional_trigger_and_hook():
    # Optional → it lives in TRIGGERS (the FireTrigger registry), not AUTO_EFFECTS.
    trig_ids = {e.card_id for e in TRIGGERS.get("before_action_space", ())}
    assert CARD_ID in trig_ids
    entry = next(e for e in TRIGGERS["before_action_space"] if e.card_id == CARD_ID)
    assert entry.mandatory is False        # declinable, not mandatory-with-choice
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["fishing"]


def test_hosts_only_fishing_when_owned():
    s = _own(_card_state(), 0, minors=(CARD_ID,))
    assert should_host_space(s, "fishing", 0)
    assert not should_host_space(s, "forest", 0)
    assert not should_host_space(s, "reed_bank", 0)


# --------------------------------------------------------------------------- #
# The effect via a real engine flow
# --------------------------------------------------------------------------- #

def test_before_phase_offers_fire_or_decline():
    s = _ready(round_number=3, grain=1)
    s = step(s, PlaceWorker(space="fishing"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.pending_stack[-1].phase == "before"
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la   # optional fire surfaced
    assert Proceed() in la                       # declinable


def test_fire_debits_grain_and_schedules_six_food():
    s = _ready(round_number=3, grain=2)
    accumulated = get_space(s.board, "fishing").accumulated_amount
    grain_before = s.players[0].resources.grain
    food_before = s.players[0].resources.food
    fr_food_before = [r.food for r in s.players[0].future_resources]

    s = step(s, PlaceWorker(space="fishing"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    # The fire records on the host but does not advance it; still the before phase,
    # now exited only by Proceed (the trigger won't be re-offered). Then Stop.
    assert s.pending_stack[-1].phase == "before"
    s = step(s, Proceed())
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())
    assert not s.pending_stack

    p = s.players[0]
    # 1 grain paid.
    assert p.resources.grain == grain_before - 1
    # Fishing's own accumulated food still collected (before-phase fire, not instead-of).
    assert p.resources.food == food_before + accumulated
    # +1 food scheduled on each of the next 6 round spaces (R+1..R+6 = rounds 4..9).
    fr = [r.food for r in p.future_resources]
    for rnd in range(4, 10):                      # 1-indexed rounds 4..9
        assert fr[rnd - 1] == fr_food_before[rnd - 1] + 1
    # Nothing scheduled outside that window.
    assert fr[2] == fr_food_before[2]             # round 3 (current) untouched
    assert fr[9] == fr_food_before[9]             # round 10 untouched
    assert sum(b - a for a, b in zip(fr_food_before, fr)) == 6


def test_schedule_clamps_past_round_14():
    # Acting in round 11 → next 6 rounds are 12..17; rounds 15/16/17 are past the game
    # and dropped, so only rounds 12/13/14 get the food (3 slots).
    s = _ready(round_number=11, grain=1)
    fr_before = [r.food for r in s.players[0].future_resources]
    s = step(s, PlaceWorker(space="fishing"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, Proceed())                        # exit the before phase
    s = step(s, Stop())
    fr = [r.food for r in s.players[0].future_resources]
    for rnd in (12, 13, 14):
        assert fr[rnd - 1] == fr_before[rnd - 1] + 1
    assert sum(b - a for a, b in zip(fr_before, fr)) == 3


def test_decline_pays_nothing():
    s = _ready(round_number=3, grain=1)
    grain_before = s.players[0].resources.grain
    fr_before = [r.food for r in s.players[0].future_resources]
    s = step(s, PlaceWorker(space="fishing"))
    s = step(s, Proceed())                        # decline the fire
    assert s.pending_stack[-1].phase == "after"
    s = step(s, Stop())
    assert not s.pending_stack
    assert s.players[0].resources.grain == grain_before          # no grain spent
    assert [r.food for r in s.players[0].future_resources] == fr_before  # nothing scheduled


def test_food_arrives_at_round_start():
    """End-to-end: scheduled food is collected when the round is entered."""
    s = _ready(round_number=3, grain=1)
    s = step(s, PlaceWorker(space="fishing"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, Proceed())                        # exit the before phase
    s = step(s, Stop())
    # Round 4 is the first scheduled slot (R+1). Verify the schedule landed there;
    # the engine's _complete_preparation distributes future_resources at round start.
    assert s.players[0].future_resources[3].food >= 1   # slot for round 4


# --------------------------------------------------------------------------- #
# Eligibility boundaries
# --------------------------------------------------------------------------- #

def test_no_fire_without_grain():
    # 0 grain → the pay is unaffordable → no FireTrigger (would be a dead-end).
    s = _ready(round_number=3, grain=0)
    s = step(s, PlaceWorker(space="fishing"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert legal_actions(s) == [Proceed()]        # host still surfaces, only decline


def test_once_per_use():
    # After firing once, the trigger is not re-offered within the same placement.
    s = _ready(round_number=3, grain=5)
    s = step(s, PlaceWorker(space="fishing"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    # The trigger is not re-offered; the before phase is now exited only by Proceed.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert legal_actions(s) == [Proceed()]


def test_no_fire_in_final_round():
    # Round 14 → no future round spaces remain, so a fire would pay grain for 0 food.
    s = _ready(round_number=14, grain=3)
    s = step(s, PlaceWorker(space="fishing"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_does_not_fire_on_other_space():
    s = _ready(round_number=3, grain=3)
    # Reed Bank is not hooked by Brewing Water → atomic fast path, no host frame.
    assert not should_host_space(s, "reed_bank", 0)
    grain_before = s.players[0].resources.grain
    out = step(s, PlaceWorker(space="reed_bank"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.grain == grain_before    # never charged off-space


def test_unowned_player_not_hosted():
    # Player 1 owns the card; player 0 (acting) does not → atomic fishing, no host.
    s = _own(_card_state(), 1, minors=(CARD_ID,))
    s = fast_replace(s, current_player=0)
    assert not should_host_space(s, "fishing", 0)
    out = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)


def test_hand_card_does_not_host():
    # A card in HAND (not played) must not host — only played cards fire.
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_minors=s.players[0].hand_minors | {CARD_ID})
    s = fast_replace(s, players=(p, s.players[1]))
    assert not should_host_space(s, "fishing", 0)


def test_family_fishing_unaffected():
    # The cardless Family game never owns the card → atomic fast path, byte-identical.
    s = setup(0)
    s = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
