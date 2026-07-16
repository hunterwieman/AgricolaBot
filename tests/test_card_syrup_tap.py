import agricola.cards.syrup_tap  # noqa: F401

"""Syrup Tap (minor, E47): "Each time you get at least 1 wood from an action
space, place 1 food on the next round space. At the start of that round, you get
the food." 1 VP.

User ruling (2026-07-15): the action space ITSELF must supply the wood (like
Kindling Gatherer detecting food supplied by the space). Implemented as an
after-window automatic on the wood-bearing accumulation spaces, eligible only when
the acting player's take (the host frame's `taken`) held wood >= 1; on a qualifying
use it schedules a flat 1 food on the next round space, collected at that round's start.
"""
from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD = "syrup_tap"

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


def _set_accumulated(state, space_id, resources):
    sp = get_space(state.board, space_id)
    return fast_replace(state, board=with_space(
        state.board, space_id, fast_replace(sp, accumulated=resources)))


def _play_hosted_space(state, space_id):
    """Drive the full hosted lifecycle: place, Proceed (primary effect), Stop."""
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

def test_registered():
    assert CARD in MINORS
    assert MINORS[CARD].cost == Cost(resources=Resources(wood=1, stone=1))
    assert MINORS[CARD].vps == 1
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("after_action_space", ())}
    assert CARD in auto_ids
    # Hooks Forest + every other wood-capable accumulation space (subset checks).
    for sp in ("forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry"):
        assert CARD in OWN_ACTION_HOOK_CARDS[sp], sp


def test_hosting_decision():
    s = _own(_card_state(), 0, minors=(CARD,))
    assert should_host_space(s, "forest", 0)
    assert should_host_space(s, "clay_pit", 0)
    assert not should_host_space(s, "day_laborer", 0)
    assert not should_host_space(s, "forest", 1)          # opponent doesn't own it


# ---------------------------------------------------------------------------
# The effect, through the real engine flow
# ---------------------------------------------------------------------------

def test_forest_schedules_food_on_next_round_space():
    s = _own(_card_state(), 0, minors=(CARD,))
    s = fast_replace(s, current_player=0)
    assert get_space(s.board, "forest").accumulated.wood >= 1   # round-1 refill
    slot = s.round_number                                       # next round's 0-index slot
    before_slot = s.players[0].future_resources[slot]
    out = _play_hosted_space(s, "forest")
    assert out.players[0].future_resources[slot] == before_slot + Resources(food=1)


def test_no_schedule_when_space_has_no_wood():
    # Clay Pit is hooked (it hosts) but holds only clay -> auto ineligible.
    s = _own(_card_state(), 0, minors=(CARD,))
    s = fast_replace(s, current_player=0)
    assert get_space(s.board, "clay_pit").accumulated.wood == 0
    slot = s.round_number
    before_slot = s.players[0].future_resources[slot]
    out = _play_hosted_space(s, "clay_pit")
    assert out.players[0].future_resources[slot] == before_slot   # nothing scheduled


def test_wood_deposited_on_non_forest_space_triggers():
    # A card could deposit wood onto Clay Pit; once it is ON the space, using
    # Clay Pit qualifies (the ruling's "the space itself supplies the wood").
    s = _own(_card_state(), 0, minors=(CARD,))
    s = fast_replace(s, current_player=0)
    s = _set_accumulated(s, "clay_pit", Resources(clay=1, wood=1))
    slot = s.round_number
    before_slot = s.players[0].future_resources[slot]
    out = _play_hosted_space(s, "clay_pit")
    assert out.players[0].future_resources[slot] == before_slot + Resources(food=1)


def test_food_collected_at_next_round_start():
    s = _own(_card_state(), 0, minors=(CARD,))
    s = fast_replace(s, current_player=0)
    s = _play_hosted_space(s, "forest")          # schedule food on round 2's slot
    food0 = s.players[0].resources.food
    slot = s.round_number                         # == 1; round 2's slot
    assert s.players[0].future_resources[slot] == Resources(food=1)
    s = _complete_preparation(s)                  # enter round 2
    assert s.players[0].resources.food == food0 + 1
    assert s.players[0].future_resources[slot] == Resources()   # slot consumed


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------

def test_opponent_use_schedules_nothing():
    # Player 0 owns the card; player 1 uses Forest -> atomic path, no schedule.
    s = _own(_card_state(), 0, minors=(CARD,))
    s = fast_replace(s, current_player=1)
    slot = s.round_number
    p0_before = s.players[0].future_resources[slot]
    p1_before = s.players[1].future_resources[slot]
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].future_resources[slot] == p0_before
    assert out.players[1].future_resources[slot] == p1_before


def test_hand_only_card_is_inert():
    s = _card_state()
    p = fast_replace(s.players[0], hand_minors=s.players[0].hand_minors | {CARD})
    s = fast_replace(s, players=(p, s.players[1]), current_player=0)
    assert not should_host_space(s, "forest", 0)
    slot = s.round_number
    before_slot = s.players[0].future_resources[slot]
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].future_resources[slot] == before_slot
