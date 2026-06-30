"""Tests for Brewery Pond (minor B40, Bubulcus): "Each time you use the
'Fishing' or 'Reed Bank' accumulation space, you also get 1 grain and 1 wood."

An automatic-income action-space hook (Category 3) over TWO atomic spaces, fired
at `before_action_space`. Mirrors the Geologist multi-space case in
test_cards_action_space_hook.py. The card is not yet in cards/__init__.py, so the
module import below is what registers it.
"""
import agricola.cards.brewery_pond  # noqa: F401

import pytest

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS, should_host_space
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space

CARD_ID = "brewery_pond"

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


def _play_hosted_space(state, space_id):
    """Drive the full hosted lifecycle: place, then auto-skip Proceed and Stop.

    The grant is a choice-free automatic effect, so the before-phase is a
    singleton Proceed (no FireTrigger surfaces)."""
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

def test_registered_as_minor_with_prereq_and_vps():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.min_occupations == 2           # "2 Occupations" prerequisite
    assert spec.vps == -1                       # -1 VP
    assert spec.cost == Cost()                  # no resource cost
    assert spec.passing_left is False


def test_registered_as_automatic_hook_on_both_spaces():
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD_ID in auto_ids
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["fishing"]
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["reed_bank"]


def test_prereq_requires_two_occupations():
    s = _card_state()
    spec = MINORS[CARD_ID]
    # 0 occupations → prereq fails.
    assert not prereq_met(spec, s, 0)
    # exactly 2 → prereq met.
    s2 = _own(s, 0, occupations=("oa", "ob"))
    assert prereq_met(spec, s2, 0)


# ---------------------------------------------------------------------------
# The effect via a real engine flow
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space", ["fishing", "reed_bank"])
def test_adds_grain_and_wood_on_its_spaces(space):
    s = _own(_card_state(), 0, minors=(CARD_ID,))
    s = fast_replace(s, current_player=0)
    before = s.players[0].resources
    out = _play_hosted_space(s, space)
    # +1 grain and +1 wood from Brewery Pond (the space's own accumulated goods
    # land on top via Proceed; we only assert the card's delta on grain/wood here
    # relative to the space's own contribution).
    space_goods = get_space(s.board, space).accumulated
    assert out.players[0].resources.grain == before.grain + space_goods.grain + 1
    assert out.players[0].resources.wood == before.wood + space_goods.wood + 1


def test_fishing_still_yields_its_own_food():
    """The hook is BEFORE the space's own effect, not instead of it: Fishing's
    accumulated food is still collected."""
    s = _own(_card_state(), 0, minors=(CARD_ID,))
    s = fast_replace(s, current_player=0)
    food_before = s.players[0].resources.food
    # Fishing yields a scalar `accumulated_amount` of food (not the `accumulated`
    # Resources object the building spaces use).
    accumulated_food = get_space(s.board, "fishing").accumulated_amount
    out = _play_hosted_space(s, "fishing")
    assert out.players[0].resources.food == food_before + accumulated_food


# ---------------------------------------------------------------------------
# Eligibility boundaries — does NOT fire elsewhere or unowned
# ---------------------------------------------------------------------------

def test_does_not_fire_on_other_space():
    s = _own(_card_state(), 0, minors=(CARD_ID,))
    s = fast_replace(s, current_player=0)
    # Forest is not a Brewery Pond space and the card doesn't hook it → atomic path,
    # no host frame, no grain/wood grant.
    grain_before = s.players[0].resources.grain
    accumulated = get_space(s.board, "forest").accumulated
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.grain == grain_before           # no +1 grain
    assert out.players[0].resources.wood == s.players[0].resources.wood + accumulated.wood


def test_not_hosted_without_card():
    s = _card_state()
    assert not should_host_space(s, "fishing", s.current_player)
    assert not should_host_space(s, "reed_bank", s.current_player)


def test_hosted_when_owned():
    s = _own(_card_state(), 0, minors=(CARD_ID,))
    assert should_host_space(s, "fishing", 0)
    assert should_host_space(s, "reed_bank", 0)
    assert not should_host_space(s, "forest", 0)        # not a hooked space


def test_hand_card_does_not_host():
    # A card in HAND (not played) must not host — only played cards fire.
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_minors=s.players[0].hand_minors | {CARD_ID})
    s = fast_replace(s, players=(p, s.players[1]))
    assert not should_host_space(s, "fishing", 0)


# ---------------------------------------------------------------------------
# Family game: byte-identical (the card is never owned)
# ---------------------------------------------------------------------------

def test_family_fishing_not_hosted():
    s = setup(0)
    s = step(s, PlaceWorker(space="fishing"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# Scoring: -1 VP flows through the minor's vps
# ---------------------------------------------------------------------------

def test_vps_minus_one_in_scoring():
    from agricola.scoring import score
    base = _card_state()
    base = fast_replace(base, current_player=0)
    owned = _own(base, 0, minors=(CARD_ID,))
    total_base, _ = score(base, 0)
    total_owned, _ = score(owned, 0)
    assert total_owned == total_base - 1
