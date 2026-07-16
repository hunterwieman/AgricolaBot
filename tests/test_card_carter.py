"""Tests for Carter (E140) — an occupation that, for the round AFTER it is played
only, grants +1 food for each building resource you take from a building-resource
accumulation space.

on_play snapshots the play round into the CardStore; an `after_action_space`
automatic effect fires only when `round_number == played + 1`, and grants food equal
to the building resources the acting player took from the space (wood+clay+reed+stone
in the host frame's `taken`, stamped at Proceed). Owner-gated. Building spaces are
atomic → hosted via the hook.
"""
import agricola.cards.carter  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import with_current_player, with_round, with_space

CARD_ID = "carter"


def _give_and_play(state, idx, play_round):
    """Inject the occupation and run its on_play at `play_round` (stores the round)."""
    state = with_round(state, play_round)
    p = state.players[idx]
    state = fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))
    return OCCUPATIONS[CARD_ID].on_play(state, idx)


def test_registration():
    assert CARD_ID in OCCUPATIONS


def test_on_play_snapshots_round():
    s = setup(seed=0)
    s = _give_and_play(s, 0, play_round=5)
    assert s.players[0].card_state.get(CARD_ID) == 5


def test_active_next_round_food_per_resource():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _give_and_play(s, 0, play_round=5)
    s = with_round(s, 6)                                       # the "next round"
    s = with_space(s, "forest", revealed=True, accumulated=Resources(wood=3))
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="forest"))                  # host pushed (before-window)
    s = step(s, Proceed())                                    # take 3 wood → after-auto: +3 food
    assert s.players[0].resources.food == f0 + 3
    s = step(s, Stop())


def test_one_resource_one_food():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _give_and_play(s, 0, play_round=5)
    s = with_round(s, 6)
    s = with_space(s, "clay_pit", revealed=True, accumulated=Resources(clay=1))
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="clay_pit"))                # host pushed (before-window)
    s = step(s, Proceed())                                    # take 1 clay → after-auto: +1 food
    assert s.players[0].resources.food == f0 + 1
    s = step(s, Stop())


def test_inert_same_round():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _give_and_play(s, 0, play_round=5)                     # stays round 5
    s = with_space(s, "forest", revealed=True, accumulated=Resources(wood=3))
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="forest"))                  # not yet "next round"
    s = step(s, Proceed())                                    # take runs; after-auto inert
    assert s.players[0].resources.food == f0
    s = step(s, Stop())


def test_inert_two_rounds_later():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = _give_and_play(s, 0, play_round=5)
    s = with_round(s, 7)                                       # window already passed
    s = with_space(s, "forest", revealed=True, accumulated=Resources(wood=3))
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())                                    # take runs; after-auto inert
    assert s.players[0].resources.food == f0
    s = step(s, Stop())
