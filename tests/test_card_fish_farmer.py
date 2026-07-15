"""Tests for Fish Farmer (occupation, Dulcinaria D110).

"Each time there is 1/2/3+ food on the "Fishing" accumulation space, you get
an additional 2 food on the "Reed Bank"/ "Clay Pit"/ "Forest" accumulation
spaces." (Errata: Grove -> Forest.)

USER RULING 2026-07-14: a use-bonus — using Reed Bank / Clay Pit / Forest
while Fishing holds exactly 1 / exactly 2 / 3+ food pays the user +2 food
from the card (general supply, never placed on the space).
"""
import agricola.cards.fish_farmer  # noqa: F401  (registers the card)

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

THREE_SPACES = ("reed_bank", "clay_pit", "forest")


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, occupations=()):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_fishing(state, n):
    sp = get_space(state.board, "fishing")
    return fast_replace(state, board=with_space(state.board, "fishing",
                                                fast_replace(sp, accumulated_amount=n)))


def _owned_state(fishing_amount, seed=5):
    s = _own(_card_state(seed), 0, occupations=("fish_farmer",))
    s = fast_replace(s, current_player=0)
    return _set_fishing(s, fishing_amount)


def _play_hosted_space(state, space_id):
    """Drive the full automatic-only hosted lifecycle (place -> Proceed -> Stop)."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    assert legal_actions(state) == [Proceed()]   # choice-free automatic effect
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    return state


def _food_delta_from_use(state, space_id):
    """Play `space_id` through the hosted flow; return player 0's food gain.

    Reed Bank / Clay Pit / Forest accumulate reed / clay / wood — never food —
    so any food delta is exactly Fish Farmer's payout.
    """
    before = state.players[0].resources.food
    out = _play_hosted_space(state, space_id)
    return out.players[0].resources.food - before


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

def test_registered_as_occupation():
    from agricola.cards.specs import OCCUPATIONS
    assert "fish_farmer" in OCCUPATIONS


def test_registered_auto_and_hooks():
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "fish_farmer" in auto_ids
    for space_id in THREE_SPACES:
        assert "fish_farmer" in OWN_ACTION_HOOK_CARDS[space_id]
    # The card watches Fishing but must never hook (host) it.
    assert "fish_farmer" not in OWN_ACTION_HOOK_CARDS.get("fishing", set())


def test_owned_card_hosts_only_the_three_spaces():
    s = _own(_card_state(), 0, occupations=("fish_farmer",))
    for space_id in THREE_SPACES:
        assert should_host_space(s, space_id, 0)
    assert not should_host_space(s, "fishing", 0)
    assert not should_host_space(s, "grain_seeds", 0)


# --------------------------------------------------------------------------- #
# The slash-correlation — paying pairings
# --------------------------------------------------------------------------- #

def test_reed_bank_pays_when_fishing_holds_exactly_one():
    assert _food_delta_from_use(_owned_state(1), "reed_bank") == 2


def test_clay_pit_pays_when_fishing_holds_exactly_two():
    assert _food_delta_from_use(_owned_state(2), "clay_pit") == 2


def test_forest_pays_when_fishing_holds_three():
    assert _food_delta_from_use(_owned_state(3), "forest") == 2


def test_forest_pays_when_fishing_holds_five():
    # "3+" — any amount of three or more qualifies.
    assert _food_delta_from_use(_owned_state(5), "forest") == 2


# --------------------------------------------------------------------------- #
# The slash-correlation — non-paying pairings (strict, not thresholds)
# --------------------------------------------------------------------------- #

def test_reed_bank_pays_nothing_at_fishing_two():
    assert _food_delta_from_use(_owned_state(2), "reed_bank") == 0


def test_reed_bank_pays_nothing_at_fishing_three():
    # Strict "exactly 1" — NOT "1 or more".
    assert _food_delta_from_use(_owned_state(3), "reed_bank") == 0


def test_clay_pit_pays_nothing_at_fishing_one():
    assert _food_delta_from_use(_owned_state(1), "clay_pit") == 0


def test_clay_pit_pays_nothing_at_fishing_three():
    assert _food_delta_from_use(_owned_state(3), "clay_pit") == 0


def test_forest_pays_nothing_at_fishing_two():
    assert _food_delta_from_use(_owned_state(2), "forest") == 0


def test_nothing_pays_at_fishing_zero():
    assert _food_delta_from_use(_owned_state(0), "reed_bank") == 0


# --------------------------------------------------------------------------- #
# Using Fishing itself pays nothing
# --------------------------------------------------------------------------- #

def test_using_fishing_itself_pays_nothing():
    s = _owned_state(3)
    before = s.players[0].resources.food
    out = step(s, PlaceWorker(space="fishing"))
    # Not hosted by Fish Farmer -> atomic path, plain accumulated food only.
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before + 3


# --------------------------------------------------------------------------- #
# Ownership boundaries
# --------------------------------------------------------------------------- #

def test_opponent_use_pays_nothing():
    # Player 1 owns the card; player 0 uses Forest at fishing=3 -> no bonus.
    s = _own(_card_state(), 1, occupations=("fish_farmer",))
    s = fast_replace(s, current_player=0)
    s = _set_fishing(s, 3)
    assert not should_host_space(s, "forest", 0)
    before = s.players[0].resources.food
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before


def test_hand_card_does_not_host_or_fire():
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_occupations=s.players[0].hand_occupations | {"fish_farmer"})
    s = fast_replace(s, players=(p, s.players[1]))
    for space_id in THREE_SPACES:
        assert not should_host_space(s, space_id, 0)


def test_family_game_unaffected():
    s = setup(0)
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
