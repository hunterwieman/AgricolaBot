"""Tests for Collier (B144) — an occupation granting +1 wood +1 reed AFTER each
use of the Clay Pit accumulation space (the 'Hollow' clause is a 3+/4-player space
absent from this engine).

Explicit "after you use" → an `after_action_space` automatic effect: the reward
lands at the host's work-complete flip, after the clay is taken. Clay Pit is atomic,
so it is hosted via register_action_space_hook. Owner-gated. Driven through the real
engine flow (setup + injected occupation, PlaceWorker → Proceed).
"""
import agricola.cards.collier  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import with_current_player, with_space

CARD_ID = "collier"


def _give(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {cid}) if i == idx
        else state.players[i] for i in range(2)))


def _clay_pit_state(clay=2, owner=0):
    s = setup(seed=0)
    s = with_current_player(s, owner)
    s = with_space(s, "clay_pit", revealed=True, accumulated=Resources(clay=clay))
    return _give(s, owner)


def test_registration():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s   # no on-play effect


def test_after_clay_pit_grants_wood_and_reed():
    s = _clay_pit_state(clay=2)
    w0 = s.players[0].resources.wood
    r0 = s.players[0].resources.reed
    c0 = s.players[0].resources.clay

    s = step(s, PlaceWorker(space="clay_pit"))
    # Hosted before-phase: the AFTER auto has NOT fired yet.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.players[0].resources.wood == w0

    s = step(s, Proceed())   # resolve Clay Pit (take clay) + flip to after (Collier)
    assert s.players[0].resources.clay == c0 + 2   # the clay taken
    assert s.players[0].resources.wood == w0 + 1   # Collier's +1 wood
    assert s.players[0].resources.reed == r0 + 1   # Collier's +1 reed
    assert legal_actions(s) == [Stop()]            # after-phase, nothing else


def test_fires_for_owner_regardless_of_seat():
    s = _clay_pit_state(clay=1, owner=1)
    w0 = s.players[1].resources.wood
    s = step(s, PlaceWorker(space="clay_pit"))
    s = step(s, Proceed())
    assert s.players[1].resources.wood == w0 + 1
    assert s.players[1].resources.reed == 1


def test_no_fire_on_other_space():
    """Forest (not hooked by Collier) resolves atomically — no +1 reed bonus."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "forest", revealed=True, accumulated=Resources(wood=3))
    s = _give(s, 0)
    r0 = s.players[0].resources.reed
    s = step(s, PlaceWorker(space="forest"))
    # Forest is atomic for a Collier-only owner → resolved directly, no host, no reed.
    assert s.players[0].resources.reed == r0
