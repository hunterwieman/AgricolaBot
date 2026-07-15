import agricola.cards.comb_and_cutter  # noqa: F401

"""Comb and Cutter (minor, E59): "Each time you use the 'Day Laborer' action
space, you get 1 additional food for each sheep on the 'Sheep Market'
accumulation space, up to a maximum of 4 additional food."

Fires as a before-window automatic on the atomic Day Laborer space (hosted via
register_action_space_hook). Bonus = min(sheep on Sheep Market, 4) food, read at
the host push before Day Laborer's own 2-food effect runs.
"""
import pytest

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
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

CARD = "comb_and_cutter"

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


def _set_sheep(state, amount):
    sp = get_space(state.board, "sheep_market")
    return fast_replace(state, board=with_space(
        state.board, "sheep_market", fast_replace(sp, accumulated_amount=amount)))


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
    assert MINORS[CARD].cost == Cost(resources=Resources(wood=1))
    assert MINORS[CARD].vps == 0
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD in auto_ids
    assert CARD in OWN_ACTION_HOOK_CARDS["day_laborer"]   # subset check


def test_hosting_decision():
    s = _own(_card_state(), 0, minors=(CARD,))
    assert should_host_space(s, "day_laborer", 0)
    assert not should_host_space(s, "fishing", 0)
    assert not should_host_space(s, "day_laborer", 1)   # opponent doesn't own it


# ---------------------------------------------------------------------------
# The effect, through the real engine flow
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("sheep,bonus", [(0, 0), (1, 1), (3, 3), (4, 4), (5, 4), (8, 4)])
def test_food_scales_with_sheep_capped_at_four(sheep, bonus):
    s = _own(_card_state(), 0, minors=(CARD,))
    s = fast_replace(s, current_player=0)
    s = _set_sheep(s, sheep)
    before = s.players[0].resources.food
    out = _play_hosted_space(s, "day_laborer")
    # Day Laborer's own 2 food + the comb bonus.
    assert out.players[0].resources.food == before + 2 + bonus


def test_opponent_use_pays_nothing():
    # Player 0 owns the card; player 1 uses Day Laborer -> atomic path, no bonus.
    s = _own(_card_state(), 0, minors=(CARD,))
    s = fast_replace(s, current_player=1)
    s = _set_sheep(s, 3)
    p0_food = s.players[0].resources.food
    out = step(s, PlaceWorker(space="day_laborer"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == p0_food          # owner unaffected


def test_hand_only_card_is_inert():
    # In hand (not played) -> no hosting, no bonus.
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_minors=s.players[0].hand_minors | {CARD})
    s = fast_replace(s, players=(p, s.players[1]), current_player=0)
    s = _set_sheep(s, 3)
    assert not should_host_space(s, "day_laborer", 0)
    before = s.players[0].resources.food
    out = step(s, PlaceWorker(space="day_laborer"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before + 2       # only Day Laborer's food
