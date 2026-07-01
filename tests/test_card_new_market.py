"""Tests for New Market (minor D55, Dulcinaria Expansion).

Card text: "Each time you use an action space card on round spaces 8 to 11, you get
1 additional food." Cost: 1 Wood, 1 Clay. Prerequisite: none. VPs: 1.

"Round spaces 8 to 11" = the action-space cards filling game rounds 8–11, which are
exactly stage 3 (rounds 8–9: vegetable_seeds, pig_market) + stage 4 (rounds 10–11:
cattle_market, eastern_quarry). The effect is an automatic before_action_space hook
on those four spaces, granting the owner +1 food.

Two members are ATOMIC accumulation spaces (vegetable_seeds, eastern_quarry) — driven
via the hosted automatic-only lifecycle (PlaceWorker -> Proceed -> Stop), mirroring
test_card_calcium_fertilizers.py. Two are non-atomic animal markets (pig_market,
cattle_market) — driven through their own commit lifecycle, mirroring
test_cards_opponent_hook.py.
"""
import agricola.cards.new_market  # noqa: F401  (registers the card)

import pytest

from agricola.actions import CommitAccommodate, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD_ID = "new_market"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own_minor(state, idx, card_id):
    p = fast_replace(
        state.players[idx],
        minor_improvements=state.players[idx].minor_improvements | {card_id},
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _ready_accum(state, space_id, owner=0):
    """Reveal + stock an accumulation space and make it `owner`'s turn."""
    state = fast_replace(state, current_player=owner)
    sp = get_space(state.board, space_id)
    return fast_replace(
        state,
        board=with_space(
            state.board, space_id,
            fast_replace(sp, revealed=True, accumulated=Resources(stone=2)),
        ),
    )


def _ready_veg(state, owner=0):
    """Reveal vegetable_seeds (no accumulation — it's a fixed +1 veg grant)."""
    state = fast_replace(state, current_player=owner)
    sp = get_space(state.board, "vegetable_seeds")
    return fast_replace(
        state,
        board=with_space(state.board, "vegetable_seeds", fast_replace(sp, revealed=True)),
    )


def _ready_cattle_market(state, owner=0, amount=1):
    state = fast_replace(state, current_player=owner)
    sp = get_space(state.board, "cattle_market")
    return fast_replace(
        state,
        board=with_space(state.board, "cattle_market",
                         fast_replace(sp, revealed=True, accumulated_amount=amount)),
    )


def _play_atomic(state, space_id):
    """Drive the hosted automatic-only lifecycle: place -> Proceed -> Stop."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.vps == 1
    assert not spec.passing_left
    assert spec.cost.resources == Resources(wood=1, clay=1)
    # No prerequisite on this card.
    assert spec.prereq is None
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD_ID in auto_ids
    # All four stage-3/4 spaces are hooked (the two atomic ones REQUIRE it).
    for space_id in ("vegetable_seeds", "pig_market", "cattle_market", "eastern_quarry"):
        assert CARD_ID in OWN_ACTION_HOOK_CARDS[space_id]


def test_no_prereq_always_playable():
    s = _card_state()
    assert prereq_met(MINORS[CARD_ID], s, 0)
    assert prereq_met(MINORS[CARD_ID], s, 1)


# ---------------------------------------------------------------------------
# Effect on the ATOMIC members (eastern_quarry, vegetable_seeds)
# ---------------------------------------------------------------------------

def test_grants_food_on_eastern_quarry():
    s = _own_minor(_card_state(), 0, CARD_ID)
    s = _ready_accum(s, "eastern_quarry", owner=0)
    f0 = s.players[0].resources.food
    stone0 = s.players[0].resources.stone

    out = _play_atomic(s, "eastern_quarry")

    # +1 food from New Market, on TOP of the quarry's own stone take.
    assert out.players[0].resources.food == f0 + 1
    assert out.players[0].resources.stone == stone0 + 2


def test_grants_food_on_vegetable_seeds():
    s = _own_minor(_card_state(), 0, CARD_ID)
    s = _ready_veg(s, owner=0)
    f0 = s.players[0].resources.food
    veg0 = s.players[0].resources.veg

    out = _play_atomic(s, "vegetable_seeds")

    # +1 food from New Market, plus the space's own +1 veg.
    assert out.players[0].resources.food == f0 + 1
    assert out.players[0].resources.veg == veg0 + 1


# ---------------------------------------------------------------------------
# Effect on a NON-ATOMIC member (cattle_market)
# ---------------------------------------------------------------------------

def test_grants_food_on_cattle_market():
    s = _own_minor(_card_state(), 0, CARD_ID)
    s = _ready_cattle_market(s, owner=0, amount=1)
    f0 = s.players[0].resources.food

    # The before-auto fires when the host frame is pushed at PlaceWorker.
    s = step(s, PlaceWorker(space="cattle_market"))
    assert s.players[0].resources.food == f0 + 1

    s = step(s, CommitAccommodate(sheep=0, boar=0, cattle=1))
    s = step(s, Stop())
    # Food unchanged after the +1; the grant fires exactly once for the action.
    assert s.players[0].resources.food == f0 + 1
    assert not s.pending_stack


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_does_not_fire_on_non_round_8_to_11_space():
    """Forest is a stage-irrelevant atomic space. New Market does not hook it, so it
    is not hosted on the owner's behalf and grants no food (byte-identical to Family)."""
    s = _own_minor(_card_state(), 0, CARD_ID)
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, "forest")
    s = fast_replace(s, board=with_space(
        s.board, "forest", fast_replace(sp, revealed=True, accumulated=Resources(wood=3))))
    f0 = s.players[0].resources.food

    s = step(s, PlaceWorker(space="forest"))
    # Forest is not hooked → atomic resolution, no host frame, no food grant.
    assert not s.pending_stack
    assert s.players[0].resources.food == f0


def test_opponent_card_does_not_fire_for_actor():
    """Player 1 owns the card; player 0 uses eastern_quarry. The card is own-action
    only (any_player=False), so neither player gets the +1 food, and the space is not
    hosted for player 0."""
    s = _own_minor(_card_state(), 1, CARD_ID)
    s = _ready_accum(s, "eastern_quarry", owner=0)
    f0, f1 = s.players[0].resources.food, s.players[1].resources.food

    s = step(s, PlaceWorker(space="eastern_quarry"))
    # Player 0 owns no hook card → atomic resolution, no host frame.
    assert not s.pending_stack
    assert s.players[0].resources.food == f0
    assert s.players[1].resources.food == f1


def test_owner_uses_space_grants_only_owner():
    """Owner (player 0) uses the space; the opponent gets nothing ('you' only)."""
    s = _own_minor(_card_state(), 0, CARD_ID)
    s = _ready_accum(s, "eastern_quarry", owner=0)
    f1 = s.players[1].resources.food
    out = _play_atomic(s, "eastern_quarry")
    assert out.players[1].resources.food == f1
