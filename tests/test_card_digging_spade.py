"""Tests for Digging Spade (minor B51): each time you use a clay accumulation
space (clay_pit), you also get food equal to your wild-boar count. Plays in round
7 or later. Pure automatic income on the atomic clay_pit host (before_action_space).
"""
import agricola.cards.digging_spade  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS, should_host_space
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space

CARD_ID = "digging_spade"

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


def _set_boar(state, idx, n):
    p = fast_replace(state.players[idx], animals=Animals(boar=n))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _play_clay_pit(state):
    """Drive the full hosted clay_pit lifecycle (place → Proceed → Stop)."""
    state = step(state, PlaceWorker(space="clay_pit"))
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
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.vps == 0
    assert spec.passing_left is False
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD_ID in auto_ids
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["clay_pit"]


# ---------------------------------------------------------------------------
# Prerequisite: round 7 or later
# ---------------------------------------------------------------------------

def test_prereq_blocked_before_round_7():
    s = _card_state()
    spec = MINORS[CARD_ID]
    for r in (1, 6):
        s = fast_replace(s, round_number=r)
        assert not prereq_met(spec, s, 0)


def test_prereq_met_in_round_7_and_later():
    s = _card_state()
    spec = MINORS[CARD_ID]
    for r in (7, 10, 14):
        s = fast_replace(s, round_number=r)
        assert prereq_met(spec, s, 0)


# ---------------------------------------------------------------------------
# Effect through a real clay_pit placement
# ---------------------------------------------------------------------------

def test_grants_food_equal_to_boar_on_clay_pit():
    s = _own(_card_state(), 0, minors=(CARD_ID,))
    s = fast_replace(s, current_player=0)
    s = _set_boar(s, 0, 3)
    before_food = s.players[0].resources.food
    accumulated_clay = get_space(s.board, "clay_pit").accumulated.clay
    before_clay = s.players[0].resources.clay

    out = _play_clay_pit(s)

    # +3 food (3 boar) and the clay the space itself yields.
    assert out.players[0].resources.food == before_food + 3
    assert out.players[0].resources.clay == before_clay + accumulated_clay


def test_no_food_when_zero_boar_but_still_hosts():
    s = _own(_card_state(), 0, minors=(CARD_ID,))
    s = fast_replace(s, current_player=0)
    s = _set_boar(s, 0, 0)
    before_food = s.players[0].resources.food

    out = _play_clay_pit(s)   # still hosts (owns the card), grants +0 food
    assert out.players[0].resources.food == before_food


def test_boar_count_is_owners_not_opponents():
    # Opponent has boar; acting player (0) has none → no food for player 0.
    s = _own(_card_state(), 0, minors=(CARD_ID,))
    s = fast_replace(s, current_player=0)
    s = _set_boar(s, 0, 0)
    s = _set_boar(s, 1, 5)
    before_food = s.players[0].resources.food
    out = _play_clay_pit(s)
    assert out.players[0].resources.food == before_food


# ---------------------------------------------------------------------------
# Eligibility boundaries: only clay_pit, only when owned
# ---------------------------------------------------------------------------

def test_does_not_fire_on_other_clay_paths_like_forest():
    # Owns the card and has boar, but Forest is a wood space, not clay_pit.
    # Digging Spade does not hook forest → atomic fast path, no host frame, no food.
    s = _own(_card_state(), 0, minors=(CARD_ID,))
    s = fast_replace(s, current_player=0)
    s = _set_boar(s, 0, 4)
    assert not should_host_space(s, "forest", 0)
    before_food = s.players[0].resources.food
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before_food


def test_not_hosted_without_card():
    s = _card_state()
    assert not should_host_space(s, "clay_pit", s.current_player)


def test_hand_card_does_not_host():
    # A card in HAND (not played) must not host the space.
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_minors=s.players[0].hand_minors | {CARD_ID})
    s = fast_replace(s, players=(p, s.players[1]))
    assert not should_host_space(s, "clay_pit", 0)


def test_family_clay_pit_not_hosted():
    # The Family game never owns this card → clay_pit stays atomic, byte-identical.
    s = setup(0)
    s = step(s, PlaceWorker(space="clay_pit"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
