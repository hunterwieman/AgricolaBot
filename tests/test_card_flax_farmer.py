"""Tests for Flax Farmer (E137) — an occupation granting +1 grain each time you use
the Reed Bank and +1 reed each time you use the Grain Seeds space.

Bare "each time you use" + flat rewards → `before_action_space` automatic effects
(fired at the host push, before the space's own goods). Both spaces are atomic, so
both are hosted via register_action_space_hook. Owner-gated. Driven through the real
engine flow (setup + injected occupation).
"""
import agricola.cards.flax_farmer  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import with_current_player, with_space

CARD_ID = "flax_farmer"


def _give(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {cid}) if i == idx
        else state.players[i] for i in range(2)))


def test_registration():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


def test_reed_bank_grants_grain():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "reed_bank", revealed=True, accumulated=Resources(reed=1))
    s = _give(s, 0)
    g0 = s.players[0].resources.grain
    r0 = s.players[0].resources.reed

    s = step(s, PlaceWorker(space="reed_bank"))
    # Before-auto fires at the push: +1 grain, before the reed is taken.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.players[0].resources.grain == g0 + 1
    assert s.players[0].resources.reed == r0        # not taken yet

    s = step(s, Proceed())                          # take the reed
    assert s.players[0].resources.reed == r0 + 1
    assert s.players[0].resources.grain == g0 + 1   # not double-applied


def test_grain_seeds_grants_reed():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _give(s, 0)
    r0 = s.players[0].resources.reed
    g0 = s.players[0].resources.grain

    s = step(s, PlaceWorker(space="grain_seeds"))
    assert s.players[0].resources.reed == r0 + 1    # Flax Farmer's +1 reed
    assert s.players[0].resources.grain == g0       # the 1 grain not taken yet

    s = step(s, Proceed())
    assert s.players[0].resources.grain == g0 + 1   # Grain Seeds' own grain
    assert s.players[0].resources.reed == r0 + 1


def test_no_fire_on_other_space():
    """Forest (neither of Flax Farmer's spaces) grants no grain/reed bonus."""
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "forest", revealed=True, accumulated=Resources(wood=3))
    s = _give(s, 0)
    g0 = s.players[0].resources.grain
    r0 = s.players[0].resources.reed
    s = step(s, PlaceWorker(space="forest"))
    assert s.players[0].resources.grain == g0
    assert s.players[0].resources.reed == r0
