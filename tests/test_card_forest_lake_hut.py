"""Tests for Forest Lake Hut (minor A42): each time you use Fishing/Forest you
also get 1 wood/food (crossed: Fishing -> +1 wood, Forest -> +1 food).

Mirrors tests/test_card_drift_net_boat.py — Forest Lake Hut is a Category-3
automatic-income minor hooking the atomic Fishing AND Forest accumulation spaces,
the exact shape of Canoe / Drift-Net Boat, but granting a per-space good.
"""
import agricola.cards.forest_lake_hut  # noqa: F401  (registers the card)

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
    """Drive the full automatic-only hosted lifecycle (place -> Proceed -> Stop)."""
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
    assert "forest_lake_hut" in MINORS
    spec = MINORS["forest_lake_hut"]
    assert spec.cost.resources == Resources(clay=2)
    assert spec.vps == 1
    assert not spec.passing_left
    assert spec.prereq is None


def test_registered_auto_and_hooks_both_spaces():
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "forest_lake_hut" in auto_ids
    assert "forest_lake_hut" in OWN_ACTION_HOOK_CARDS["fishing"]
    assert "forest_lake_hut" in OWN_ACTION_HOOK_CARDS["forest"]


def test_owned_card_hosts_only_fishing_and_forest():
    s = _own(_card_state(), 0, minors=("forest_lake_hut",))
    assert should_host_space(s, "fishing", 0)
    assert should_host_space(s, "forest", 0)
    assert not should_host_space(s, "sheep_market", 0)
    assert not should_host_space(s, "clay_pit", 0)


# --------------------------------------------------------------------------- #
# Effect via a real engine flow — crossed mapping
# --------------------------------------------------------------------------- #

def test_fishing_grants_one_wood():
    # Fishing -> +1 WOOD (the crossed mapping), not food.
    s = _own(_card_state(), 0, minors=("forest_lake_hut",))
    s = fast_replace(s, current_player=0)
    accumulated_food = get_space(s.board, "fishing").accumulated_amount
    food_before = s.players[0].resources.food
    wood_before = s.players[0].resources.wood
    out = _play_hosted_space(s, "fishing")
    # Fishing pays its accumulated food (Proceed) and Forest Lake Hut adds 1 wood.
    assert out.players[0].resources.food == food_before + accumulated_food
    assert out.players[0].resources.wood == wood_before + 1


def test_forest_grants_one_food():
    # Forest -> +1 FOOD (the crossed mapping), not wood.
    s = _own(_card_state(), 0, minors=("forest_lake_hut",))
    s = fast_replace(s, current_player=0)
    # Stock the forest space so accumulated wood is deterministic and non-zero.
    sp = get_space(s.board, "forest")
    s = fast_replace(s, board=with_space(s.board, "forest",
                                         fast_replace(sp, accumulated_amount=3)))
    food_before = s.players[0].resources.food
    wood_before = s.players[0].resources.wood
    out = _play_hosted_space(s, "forest")
    # Forest pays its accumulated wood (Proceed) and Forest Lake Hut adds 1 food.
    assert out.players[0].resources.wood == wood_before + 3
    assert out.players[0].resources.food == food_before + 1


# --------------------------------------------------------------------------- #
# Eligibility boundaries — fires only at Fishing/Forest, only when owned
# --------------------------------------------------------------------------- #

def test_does_not_fire_on_other_accumulation_space():
    # clay_pit is an atomic accumulation space but is NOT hooked -> atomic path.
    s = _own(_card_state(), 0, minors=("forest_lake_hut",))
    s = fast_replace(s, current_player=0)
    assert not should_host_space(s, "clay_pit", s.current_player)


def test_hand_card_does_not_host_or_fire():
    # A card in HAND (not played) must not host -> Family/unplayed byte-identity.
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_minors=s.players[0].hand_minors | {"forest_lake_hut"})
    s = fast_replace(s, players=(p, s.players[1]))
    assert not should_host_space(s, "fishing", 0)
    assert not should_host_space(s, "forest", 0)


def test_unowned_player_gets_no_bonus():
    # Player 1 owns the card; player 0 (acting) does not -> atomic forest, no +food.
    s = _own(_card_state(), 1, minors=("forest_lake_hut",))
    s = fast_replace(s, current_player=0)
    assert not should_host_space(s, "forest", 0)
    sp = get_space(s.board, "forest")
    s = fast_replace(s, board=with_space(s.board, "forest",
                                         fast_replace(sp, accumulated_amount=3)))
    food_before = s.players[0].resources.food
    wood_before = s.players[0].resources.wood
    out = step(s, PlaceWorker(space="forest"))
    # No host frame (player 0 doesn't own it) -> plain accumulated wood, no +food.
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.wood == wood_before + 3
    assert out.players[0].resources.food == food_before


def test_family_forest_unaffected():
    # The cardless Family game never owns the card -> atomic fast path, byte-identical.
    s = setup(0)
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
