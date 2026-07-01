"""Tests for Portmonger (occupation A103).

Card text: "Each time you take 1/2/3+ food from a food accumulation space, you also
get 1 vegetable/grain/reed." Banded / single-tier: take 1 → 1 veg, 2 → 1 grain,
3+ → 1 reed.

Implemented as a before_action_space automatic effect on the card-game food
accumulation space (fishing only — Meeting Place pays no food in the card game),
hosted via register_action_space_hook. Mirrors tests/test_cards_action_space_hook.py.
"""
import agricola.cards.portmonger  # noqa: F401  (registers the card; not yet in cards/__init__)

import pytest

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, occupations=(), minors=()):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations),
                     minor_improvements=state.players[idx].minor_improvements | set(minors))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_food(state, space_id, amount):
    sp = get_space(state.board, space_id)
    return fast_replace(state, board=with_space(state.board, space_id,
                                                fast_replace(sp, accumulated_amount=amount)))


def _play_hosted_space(state, space_id):
    """Drive the full hosted lifecycle for an automatic-only (no-trigger) card."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    from agricola.cards.specs import OCCUPATIONS
    assert "portmonger" in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "portmonger" in auto_ids
    assert "portmonger" in OWN_ACTION_HOOK_CARDS["fishing"]
    # meeting_place is NOT hooked: card-mode Meeting Place pays no food, so Portmonger
    # can never fire there. Hooking it would make the engine host the space (should_host_space
    # reads registrations, not eligibility), colliding with Meeting Place's pushing handler.
    assert "portmonger" not in OWN_ACTION_HOOK_CARDS.get("meeting_place", set())


# ---------------------------------------------------------------------------
# The banded reward via a real Fishing placement
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("amount,field,delta", [
    (1, "veg",   1),   # take 1 food → 1 vegetable
    (2, "grain", 1),   # take 2 food → 1 grain
    (3, "reed",  1),   # take 3 food → 1 reed
    (4, "reed",  1),   # take 4 food → still 1 reed (3+ band)
    (7, "reed",  1),   # deep 3+ band → 1 reed
])
def test_banded_reward_on_fishing(amount, field, delta):
    s = _own(_card_state(), 0, occupations=("portmonger",))
    s = fast_replace(s, current_player=0)
    s = _set_food(s, "fishing", amount)

    before_food = s.players[0].resources.food
    before_reward = getattr(s.players[0].resources, field)
    out = _play_hosted_space(s, "fishing")

    # Primary effect: all the food on the space was taken.
    assert out.players[0].resources.food == before_food + amount
    # Banded card reward in the correct good.
    assert getattr(out.players[0].resources, field) == before_reward + delta


def test_only_the_band_good_is_granted():
    """Band 2 grants grain ONLY — not veg, not reed (single-tier, not cumulative)."""
    s = _own(_card_state(), 0, occupations=("portmonger",))
    s = fast_replace(s, current_player=0)
    s = _set_food(s, "fishing", 2)
    before = s.players[0].resources
    out = _play_hosted_space(s, "fishing")
    assert out.players[0].resources.grain == before.grain + 1
    assert out.players[0].resources.veg == before.veg          # band 1 not also granted
    assert out.players[0].resources.reed == before.reed        # band 3+ not also granted


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_no_reward_when_space_empty():
    """accumulated_amount == 0 → nothing taken → no banded good (>= 1 guard)."""
    s = _own(_card_state(), 0, occupations=("portmonger",))
    s = fast_replace(s, current_player=0)
    s = _set_food(s, "fishing", 0)
    before = s.players[0].resources
    out = _play_hosted_space(s, "fishing")
    assert out.players[0].resources.veg == before.veg
    assert out.players[0].resources.grain == before.grain
    assert out.players[0].resources.reed == before.reed
    assert out.players[0].resources.food == before.food        # 0 food taken


def test_does_not_fire_on_non_food_space():
    """Portmonger hooks only the food spaces; a clay space stays atomic, no reward."""
    s = _own(_card_state(), 0, occupations=("portmonger",))
    s = fast_replace(s, current_player=0)
    before = s.players[0].resources
    accumulated_clay = get_space(s.board, "clay_pit").accumulated.clay
    out = step(s, PlaceWorker(space="clay_pit"))
    # clay_pit not hooked by portmonger → atomic fast path, no host frame.
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.veg == before.veg
    assert out.players[0].resources.grain == before.grain
    assert out.players[0].resources.reed == before.reed
    assert out.players[0].resources.clay == before.clay + accumulated_clay


def test_meeting_place_pays_no_food_in_cards_mode():
    """CARDS-mode Meeting Place never accumulates food → Portmonger grants nothing
    there, and a Portmonger owner can use Meeting Place and decline without soft-locking.

    Regression guard for the meeting-place double-host cycle: a Portmonger owner placing
    on Meeting Place must NOT host it (Portmonger no longer hooks the space), so following
    the LEGAL action at each step terminates the turn — under the old bug (Portmonger
    hooking meeting_place → should_host_space True) the legal path was an infinite
    Proceed↔Stop cycle. We drive `legal_actions` (not a forced Stop) so the cycle would
    fail this test rather than pass it."""
    s = _own(_card_state(), 0, occupations=("portmonger",))
    s = fast_replace(s, current_player=0)
    assert get_space(s.board, "meeting_place").accumulated_amount == 0
    before = s.players[0].resources

    s = step(s, PlaceWorker(space="meeting_place"))
    # Follow the legal path, always declining (prefer Proceed/Stop), bounded so a
    # regression of the cycle fails loudly instead of hanging.
    for _ in range(12):
        if not s.pending_stack:
            break
        legal = legal_actions(s)
        decline = next((a for a in legal if isinstance(a, (Proceed, Stop))), None)
        assert decline is not None, f"no decline action available: {legal}"
        s = step(s, decline)
    else:
        pytest.fail("Meeting Place did not terminate — soft-lock cycle regressed")
    # No banded good (the >= 1 guard fails at an empty food space).
    assert s.players[0].resources.veg == before.veg
    assert s.players[0].resources.grain == before.grain
    assert s.players[0].resources.reed == before.reed


def test_does_not_fire_for_non_owner():
    """An opponent who does NOT own Portmonger gets no banded good at Fishing."""
    s = _own(_card_state(), 0, occupations=("portmonger",))  # P0 owns it
    s = fast_replace(s, current_player=1)                    # P1 acts, owns nothing
    s = _set_food(s, "fishing", 1)
    before1 = s.players[1].resources
    # P1's placement is atomic (P1 owns no hook on fishing) → no host frame.
    out = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[1].resources.veg == before1.veg
    assert out.players[1].resources.food == before1.food + 1   # P1 still took the food


def test_family_fishing_unaffected():
    """No card ownership in Family mode → fishing is the atomic fast path."""
    s = setup(0)
    s = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
