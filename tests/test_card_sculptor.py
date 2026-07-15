"""Tests for Sculptor (occupation, Dulcinaria D105).

"Each time you use a clay accumulation space, you also get 1 food. Each time
you use a stone accumulation space, you also get 1 grain."

Two before_action_space automatics on the 2-player clay/stone accumulation
spaces: Clay Pit -> +1 food; Western/Eastern Quarry -> +1 grain. All three are
atomic spaces hosted via register_action_space_hook.
"""
import agricola.cards.sculptor  # noqa: F401

import pytest

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
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    """A card-mode round-1 WORK state."""
    s, env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, occupations=(), minors=()):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations),
                     minor_improvements=state.players[idx].minor_improvements | set(minors))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reveal_quarry(state, space_id, stone=2):
    """Quarries are stage cards (not up at round 1); reveal + stock one."""
    sp = get_space(state.board, space_id)
    return fast_replace(state, board=with_space(state.board, space_id,
                                                fast_replace(sp, revealed=True,
                                                             accumulated=Resources(stone=stone))))


def _play_hosted_space(state, space_id):
    """Drive the full hosted lifecycle: place, then Proceed and Stop.
    Sculptor is automatic-only, so both phases are singletons."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack            # host popped, turn ended
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_sculptor_registered():
    from agricola.cards.specs import OCCUPATIONS
    assert "sculptor" in OCCUPATIONS
    # Two automatics on before_action_space (clay -> food, stone -> grain).
    entries = [e for e in AUTO_EFFECTS.get("before_action_space", ())
               if e.card_id == "sculptor"]
    assert len(entries) == 2
    # Hooks all three atomic spaces (own use only).
    for space in ("clay_pit", "western_quarry", "eastern_quarry"):
        assert "sculptor" in OWN_ACTION_HOOK_CARDS[space]


# ---------------------------------------------------------------------------
# Clay accumulation space -> +1 food
# ---------------------------------------------------------------------------

def test_clay_pit_gives_one_food():
    s = _own(_card_state(), 0, occupations=("sculptor",))
    s = fast_replace(s, current_player=0)
    accumulated = get_space(s.board, "clay_pit").accumulated.clay
    before_food = s.players[0].resources.food
    before_clay = s.players[0].resources.clay
    before_grain = s.players[0].resources.grain
    out = _play_hosted_space(s, "clay_pit")
    assert out.players[0].resources.food == before_food + 1        # Sculptor
    assert out.players[0].resources.clay == before_clay + accumulated
    assert out.players[0].resources.grain == before_grain          # no cross-fire


# ---------------------------------------------------------------------------
# Stone accumulation spaces -> +1 grain
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("quarry", ["western_quarry", "eastern_quarry"])
def test_quarry_gives_one_grain(quarry):
    s = _own(_card_state(), 0, occupations=("sculptor",))
    s = fast_replace(s, current_player=0)
    s = _reveal_quarry(s, quarry, stone=2)
    before_grain = s.players[0].resources.grain
    before_food = s.players[0].resources.food
    before_stone = s.players[0].resources.stone
    out = _play_hosted_space(s, quarry)
    assert out.players[0].resources.grain == before_grain + 1      # Sculptor
    assert out.players[0].resources.stone == before_stone + 2      # accumulated
    assert out.players[0].resources.food == before_food            # no cross-fire


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------

def test_no_effect_on_other_spaces():
    # Forest is neither clay nor stone; Sculptor doesn't hook it -> atomic path.
    s = _own(_card_state(), 0, occupations=("sculptor",))
    s = fast_replace(s, current_player=0)
    assert not should_host_space(s, "forest", 0)
    before_food = s.players[0].resources.food
    before_grain = s.players[0].resources.grain
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before_food
    assert out.players[0].resources.grain == before_grain


def test_opponent_use_pays_nobody():
    # Player 0 owns Sculptor; player 1 uses Clay Pit -> no host, no payout to
    # either player.
    s = _own(_card_state(), 0, occupations=("sculptor",))
    s = fast_replace(s, current_player=1)
    assert not should_host_space(s, "clay_pit", 1)
    accumulated = get_space(s.board, "clay_pit").accumulated.clay
    before = [(p.resources.food, p.resources.grain) for p in s.players]
    out = step(s, PlaceWorker(space="clay_pit"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    for i in range(2):
        assert out.players[i].resources.food == before[i][0]
        assert out.players[i].resources.grain == before[i][1]
    assert out.players[1].resources.clay == s.players[1].resources.clay + accumulated


def test_hand_only_card_is_inert():
    # Sculptor in hand (not played) must not host or fire.
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_occupations=s.players[0].hand_occupations | {"sculptor"})
    s = fast_replace(s, players=(p, s.players[1]), current_player=0)
    assert not should_host_space(s, "clay_pit", 0)
    before_food = s.players[0].resources.food
    out = step(s, PlaceWorker(space="clay_pit"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before_food
