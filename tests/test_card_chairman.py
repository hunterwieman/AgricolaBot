"""Tests for Chairman (D139) — an occupation: each time ANOTHER player uses Meeting
Place, both they and the owner get 1 food; if the owner uses it, the owner gets 1
food.

An `any_player` `before_action_space` automatic effect on Meeting Place, which is
SELF-HOSTING in the card game (no register_action_space_hook). Collapses to: owner
always +1 food; if actor != owner, actor also +1 food. Card-mode Meeting Place gives
no food of its own (become-SP + optional minor), so the only food change is Chairman's.
Requires CARDS mode for Meeting Place to be hosted.
"""
import agricola.cards.chairman  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.pending import PendingMeetingPlace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player

CARD_ID = "chairman"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _cards_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return cs


def _give(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {cid}) if i == idx
        else state.players[i] for i in range(2)))


def test_registration():
    assert CARD_ID in OCCUPATIONS
    s = _cards_state()
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


def test_owner_uses_meeting_place():
    """Owner uses it → owner +1 food only (the 'if you use it' clause)."""
    s = with_current_player(_cards_state(), 0)
    s = _give(s, 0)
    f0 = s.players[0].resources.food
    f1 = s.players[1].resources.food

    s = step(s, PlaceWorker(space="meeting_place"))
    assert isinstance(s.pending_stack[-1], PendingMeetingPlace)   # self-hosted
    assert s.players[0].resources.food == f0 + 1
    assert s.players[1].resources.food == f1                      # opponent unchanged


def test_opponent_uses_meeting_place():
    """Another player uses it → both the actor and the owner get 1 food."""
    s = with_current_player(_cards_state(), 1)
    s = _give(s, 0)                       # owner is P0; P1 is the actor
    f_owner = s.players[0].resources.food
    f_actor = s.players[1].resources.food

    s = step(s, PlaceWorker(space="meeting_place"))
    assert s.players[0].resources.food == f_owner + 1   # owner
    assert s.players[1].resources.food == f_actor + 1   # actor


def test_no_food_without_owner():
    """Neither player owns Chairman → no bonus food from Meeting Place (card mode)."""
    s = with_current_player(_cards_state(), 0)
    f0 = s.players[0].resources.food
    f1 = s.players[1].resources.food
    s = step(s, PlaceWorker(space="meeting_place"))
    assert s.players[0].resources.food == f0
    assert s.players[1].resources.food == f1
