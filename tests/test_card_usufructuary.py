"""Tests for Usufructuary (occupation, E157; Ephipparius Expansion).

Card text: "When you play this card as your first occupation, you immediately get 1
food for every other occupation in play (by any player), up to a maximum of 7 food."

On-play, gated on being the owner's FIRST occupation (exactly one occupation owned,
counting this card which is already in the tableau at on_play time). The food equals
the number of OTHER occupations across both players (total - 1), capped at 7. Tests
drive the real Lessons flow (which adds the card before on_play, so "first" is
exercised faithfully) and cover: first-occupation payout counting the opponent's
occupations, the 7-food cap, zero others, and the not-first-occupation no-op.
"""
import agricola.cards.usufructuary  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.usufructuary import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env

from tests.factories import with_current_player, with_space

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _play_occupation(cs, idx, card_id):
    cs = with_current_player(cs, idx)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=card_id))
    return cs


def _set_occupations(state, idx, ids: frozenset, *, hand=frozenset()):
    p = state.players[idx]
    p = fast_replace(p, occupations=ids, hand_occupations=hand)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS


# --- Direct on-play (simulating the post-add tableau state) ------------------

def test_direct_first_occupation_counts_others():
    """Card already in owner's tableau (len 1 = first); opponent has 3 occupations
    -> 3 other occupations in play -> 3 food."""
    on_play = OCCUPATIONS[CARD_ID].on_play
    s = _set_occupations(setup(0), 0, frozenset({CARD_ID}))
    s = _set_occupations(s, 1, frozenset({"a", "b", "c"}))
    f0 = s.players[0].resources.food
    after = on_play(s, 0)
    assert after.players[0].resources.food == f0 + 3


def test_direct_caps_at_seven():
    on_play = OCCUPATIONS[CARD_ID].on_play
    s = _set_occupations(setup(0), 0, frozenset({CARD_ID}))
    s = _set_occupations(s, 1, frozenset(f"o{i}" for i in range(10)))  # 10 others
    f0 = s.players[0].resources.food
    after = on_play(s, 0)
    assert after.players[0].resources.food == f0 + 7        # capped


def test_direct_no_other_occupations():
    on_play = OCCUPATIONS[CARD_ID].on_play
    s = _set_occupations(setup(0), 0, frozenset({CARD_ID}))   # the only occupation
    f0 = s.players[0].resources.food
    after = on_play(s, 0)
    assert after.players[0].resources.food == f0             # total-1 = 0


def test_direct_not_first_occupation_no_food():
    """Owner already holds another occupation -> this is not their first -> no food,
    even though there are others in play."""
    on_play = OCCUPATIONS[CARD_ID].on_play
    s = _set_occupations(setup(0), 0, frozenset({"prior", CARD_ID}))  # len 2
    s = _set_occupations(s, 1, frozenset({"a", "b"}))
    f0 = s.players[0].resources.food
    after = on_play(s, 0)
    assert after.players[0].resources.food == f0


# --- Real engine flow (adds the card before on_play) ------------------------

def test_first_occupation_via_engine_flow():
    """Owner plays Usufructuary as their first occupation; opponent already has 2
    occupations -> +2 food."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _set_occupations(cs, 0, frozenset(), hand=frozenset({CARD_ID}))
    cs = _set_occupations(cs, 1, frozenset({"x", "y"}))
    f0 = cs.players[0].resources.food
    cs = _play_occupation(cs, 0, CARD_ID)
    assert CARD_ID in cs.players[0].occupations
    assert cs.players[0].resources.food == f0 + 2


def test_not_first_occupation_via_engine_flow():
    """Owner already has an occupation, then plays Usufructuary -> not first -> the
    card grants no food. (Playing a 2nd occupation via Lessons has its own food
    cost, so food may DROP; the card itself can only ever ADD food, and only when
    first — so a not-first play must never raise food above the pre-play total.)"""
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _set_occupations(cs, 0, frozenset({"prior"}), hand=frozenset({CARD_ID}))
    cs = _set_occupations(cs, 1, frozenset({"x", "y"}))
    f0 = cs.players[0].resources.food
    cs = _play_occupation(cs, 0, CARD_ID)
    assert CARD_ID in cs.players[0].occupations
    assert cs.players[0].resources.food <= f0     # no card food added
