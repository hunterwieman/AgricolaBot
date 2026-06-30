"""Tests for Drift-Net Boat (minor A51): +2 food each time you use Fishing.

Mirrors tests/test_cards_action_space_hook.py — Drift-Net Boat is a Category-3
automatic-income minor hooking the atomic Fishing accumulation space, the exact
shape of Canoe / Corn Scoop.
"""
import agricola.cards.drift_net_boat  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space

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


def _play_hosted_space(state, space_id):
    """Drive the full automatic-only hosted lifecycle (place → Proceed → Stop)."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    assert legal_actions(state) == [Proceed()]   # no optional trigger surfaced
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    return state


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

def test_registered_as_minor_with_cost_and_vps():
    from agricola.cards.specs import MINORS
    from agricola.resources import Resources
    assert "drift_net_boat" in MINORS
    spec = MINORS["drift_net_boat"]
    assert spec.cost.resources == Resources(wood=1, reed=1)
    assert spec.vps == 1
    assert not spec.passing_left


def test_registered_auto_and_hook():
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "drift_net_boat" in auto_ids
    assert "drift_net_boat" in OWN_ACTION_HOOK_CARDS["fishing"]


def test_owned_card_hosts_only_fishing():
    s = _own(_card_state(), 0, minors=("drift_net_boat",))
    assert should_host_space(s, "fishing", 0)
    assert not should_host_space(s, "forest", 0)
    assert not should_host_space(s, "sheep_market", 0)


# --------------------------------------------------------------------------- #
# Effect via a real engine flow
# --------------------------------------------------------------------------- #

def test_grants_two_food_on_fishing():
    s = _own(_card_state(), 0, minors=("drift_net_boat",))
    s = fast_replace(s, current_player=0)
    accumulated = get_space(s.board, "fishing").accumulated_amount
    before = s.players[0].resources.food
    out = _play_hosted_space(s, "fishing")
    # Fishing pays its accumulated food (Proceed) + 2 (Drift-Net Boat, before-phase).
    assert out.players[0].resources.food == before + accumulated + 2


def test_grants_two_food_with_extra_accumulation():
    # Stock the fishing space heavier to confirm the +2 is additive, not replacing.
    s = _own(_card_state(), 0, minors=("drift_net_boat",))
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, "fishing")
    s = fast_replace(s, board=with_space(s.board, "fishing",
                                         fast_replace(sp, accumulated_amount=4)))
    before = s.players[0].resources.food
    out = _play_hosted_space(s, "fishing")
    assert out.players[0].resources.food == before + 4 + 2


# --------------------------------------------------------------------------- #
# Eligibility boundaries — fires only at Fishing, only when owned
# --------------------------------------------------------------------------- #

def test_does_not_fire_on_other_food_space():
    # Meeting Place is also a food accumulation space but is NOT hooked → atomic path,
    # no +2 food.  (In Cards mode Meeting Place is the become-SP space.)
    s = _own(_card_state(), 0, minors=("drift_net_boat",))
    s = fast_replace(s, current_player=0)
    assert not should_host_space(s, "meeting_place", s.current_player)


def test_hand_card_does_not_host_or_fire():
    # A card in HAND (not played) must not host — Family/unplayed byte-identity.
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_minors=s.players[0].hand_minors | {"drift_net_boat"})
    s = fast_replace(s, players=(p, s.players[1]))
    assert not should_host_space(s, "fishing", 0)


def test_unowned_player_gets_no_bonus():
    # Player 1 owns the card; player 0 (acting) does not → atomic fishing, no +2.
    s = _own(_card_state(), 1, minors=("drift_net_boat",))
    s = fast_replace(s, current_player=0)
    assert not should_host_space(s, "fishing", 0)
    before = s.players[0].resources.food
    accumulated = get_space(s.board, "fishing").accumulated_amount
    out = step(s, PlaceWorker(space="fishing"))
    # No host frame (player 0 doesn't own it) → plain accumulated food, no +2.
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before + accumulated


def test_family_fishing_unaffected():
    # The cardless Family game never owns the card → atomic fast path, byte-identical.
    s = setup(0)
    s = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
