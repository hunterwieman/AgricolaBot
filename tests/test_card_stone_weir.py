import agricola.cards.stone_weir  # noqa: F401

"""Stone Weir (minor, E55): "Each time you use the 'Fishing' accumulation space,
if there are 0/1/2/3 food on the space, you get an additional 4/3/2/1 food from
the general supply." Prereq: 2 occupations. 1 VP.

Fires as a before-window automatic on the atomic Fishing space (hosted via
register_action_space_hook). Bonus = max(0, 4 - food on Fishing), read at the
host push before Fishing is swept; the player also collects the Fishing food.
"""
import pytest

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD = "stone_weir"

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


def _set_fishing(state, amount):
    sp = get_space(state.board, "fishing")
    return fast_replace(state, board=with_space(
        state.board, "fishing", fast_replace(sp, accumulated_amount=amount)))


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
# Registration & prerequisite
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD in MINORS
    assert MINORS[CARD].cost == Cost(resources=Resources(stone=1))
    assert MINORS[CARD].vps == 1
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD in auto_ids
    assert CARD in OWN_ACTION_HOOK_CARDS["fishing"]        # subset check


def test_prereq_two_occupations():
    s = _card_state()
    assert not prereq_met(MINORS[CARD], _own(s, 0, occupations=()), 0)
    assert not prereq_met(MINORS[CARD], _own(s, 0, occupations=("o0",)), 0)
    assert prereq_met(MINORS[CARD], _own(s, 0, occupations=("o0", "o1")), 0)
    assert prereq_met(MINORS[CARD], _own(s, 0, occupations=("o0", "o1", "o2")), 0)


def test_hosting_decision():
    s = _own(_card_state(), 0, minors=(CARD,))
    assert should_host_space(s, "fishing", 0)
    assert not should_host_space(s, "day_laborer", 0)
    assert not should_host_space(s, "fishing", 1)          # opponent doesn't own it


# ---------------------------------------------------------------------------
# The effect, through the real engine flow
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("food_on_space,bonus", [
    (0, 4), (1, 3), (2, 2), (3, 1), (4, 0), (5, 0), (6, 0),
])
def test_bonus_by_fishing_food(food_on_space, bonus):
    s = _own(_card_state(), 0, minors=(CARD,))
    s = fast_replace(s, current_player=0)
    s = _set_fishing(s, food_on_space)
    before = s.players[0].resources.food
    out = _play_hosted_space(s, "fishing")
    # Collect the Fishing food itself + the Stone Weir top-up.
    assert out.players[0].resources.food == before + food_on_space + bonus


def test_opponent_use_pays_nothing():
    s = _own(_card_state(), 0, minors=(CARD,))
    s = fast_replace(s, current_player=1)
    s = _set_fishing(s, 0)
    p0_food = s.players[0].resources.food
    out = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == p0_food


def test_hand_only_card_is_inert():
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_minors=s.players[0].hand_minors | {CARD})
    s = fast_replace(s, players=(p, s.players[1]), current_player=0)
    s = _set_fishing(s, 0)
    assert not should_host_space(s, "fishing", 0)
    before = s.players[0].resources.food
    out = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before          # empty fishing, no top-up
