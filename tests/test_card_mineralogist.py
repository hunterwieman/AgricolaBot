"""Tests for Mineralogist (occupation, B122).

Card text: "Each time you use a clay/stone accumulation space, you also get 1 of
the other good, stone/clay." So Clay Pit (clay space) also yields +1 stone, and
the two quarries (stone spaces) each also yield +1 clay — always the OTHER good.

Mirrors tests/test_cards_action_space_hook.py (the Geologist/Wood Cutter shape):
the hook hosts an otherwise-atomic accumulation space with a PendingActionSpace
frame, runs before-auto (Mineralogist's bonus) → Proceed (primary take) → Stop.
"""
import agricola.cards.mineralogist  # noqa: F401  (registers the card)

import pytest

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS, should_host_space
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, *, occupations=()):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occupations))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reveal_quarry(state, space_id, stone=2):
    """Quarries are Stage 2/4 spaces (not up at round 1) — reveal + stock one."""
    sp = get_space(state.board, space_id)
    return fast_replace(state, board=with_space(
        state.board, space_id,
        fast_replace(sp, revealed=True, accumulated=Resources(stone=stone))))


def _play_hosted_space(state, space_id):
    """Drive the full hosted lifecycle: place, then auto-skip Proceed and Stop.
    Automatic-only card → before-phase is a singleton Proceed (no FireTrigger)."""
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
    assert "mineralogist" in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "mineralogist" in auto_ids
    for sid in ("clay_pit", "western_quarry", "eastern_quarry"):
        assert "mineralogist" in OWN_ACTION_HOOK_CARDS[sid]


# ---------------------------------------------------------------------------
# The bonus is the OTHER good, space-dependent
# ---------------------------------------------------------------------------

def test_clay_pit_also_grants_one_stone():
    s = _own(_card_state(), 0, occupations=("mineralogist",))
    s = fast_replace(s, current_player=0)
    accumulated_clay = get_space(s.board, "clay_pit").accumulated.clay
    before_clay = s.players[0].resources.clay
    before_stone = s.players[0].resources.stone
    out = _play_hosted_space(s, "clay_pit")
    # Clay Pit gives its accumulated clay (Proceed) + 1 stone (Mineralogist).
    assert out.players[0].resources.clay == before_clay + accumulated_clay
    assert out.players[0].resources.stone == before_stone + 1


@pytest.mark.parametrize("space", ["western_quarry", "eastern_quarry"])
def test_quarry_also_grants_one_clay(space):
    s = _own(_card_state(), 0, occupations=("mineralogist",))
    s = fast_replace(s, current_player=0)
    s = _reveal_quarry(s, space, stone=2)
    before_clay = s.players[0].resources.clay
    before_stone = s.players[0].resources.stone
    out = _play_hosted_space(s, space)
    # Quarry gives 2 accumulated stone (Proceed) + 1 clay (Mineralogist).
    assert out.players[0].resources.stone == before_stone + 2
    assert out.players[0].resources.clay == before_clay + 1


# ---------------------------------------------------------------------------
# Eligibility boundaries — does NOT fire on unrelated accumulation spaces
# ---------------------------------------------------------------------------

def test_does_not_fire_on_unrelated_space():
    # Forest (a wood space) is not hooked by Mineralogist → atomic path, no host
    # frame, no clay/stone bonus.
    s = _own(_card_state(), 0, occupations=("mineralogist",))
    s = fast_replace(s, current_player=0)
    assert not should_host_space(s, "forest", 0)
    before_clay = s.players[0].resources.clay
    before_stone = s.players[0].resources.stone
    accumulated_wood = get_space(s.board, "forest").accumulated.wood
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.clay == before_clay        # no +1 clay
    assert out.players[0].resources.stone == before_stone      # no +1 stone
    assert out.players[0].resources.wood == s.players[0].resources.wood + accumulated_wood


def test_does_not_host_without_card():
    # Without owning Mineralogist, the clay/stone spaces are not hosted.
    s = _card_state()
    for sid in ("clay_pit", "western_quarry", "eastern_quarry"):
        assert not should_host_space(s, sid, s.current_player)


def test_only_owner_benefits():
    # Player 0 owns it; when player 1 uses Clay Pit there is no bonus and no host.
    s = _own(_card_state(), 0, occupations=("mineralogist",))
    s = fast_replace(s, current_player=1)
    assert not should_host_space(s, "clay_pit", 1)
    before_stone = s.players[1].resources.stone
    out = step(s, PlaceWorker(space="clay_pit"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[1].resources.stone == before_stone      # opponent gets no +stone


# ---------------------------------------------------------------------------
# Family game byte-identity — the card never exists, so clay_pit stays atomic
# ---------------------------------------------------------------------------

def test_family_clay_pit_not_hosted():
    s = setup(0)
    s = step(s, PlaceWorker(space="clay_pit"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
