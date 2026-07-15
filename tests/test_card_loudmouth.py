"""Tests for Loudmouth (D140) — an occupation granting +1 food each time you take
at least 4 building resources OR at least 4 animals from an accumulation space.

Bare "each time you take" + flat +1 food → a `before_action_space` automatic effect.
The threshold is read from the space at the before-phase: a building space's Resources
bank (wood+clay+reed+stone) for the building clause (atomic → hooked), or the market
frame's staged `gained` for the animal clause (non-atomic → always hosted). Owner-gated.
"""
import agricola.cards.loudmouth  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import with_current_player, with_space

CARD_ID = "loudmouth"


def _give(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {cid}) if i == idx
        else state.players[i] for i in range(2)))


def test_registration():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


def test_four_building_resources_grants_food():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "forest", revealed=True, accumulated=Resources(wood=4))
    s = _give(s, 0)
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="forest"))   # 4 building resources → +1 food (before)
    assert s.players[0].resources.food == f0 + 1


def test_three_building_resources_no_food():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "forest", revealed=True, accumulated=Resources(wood=3))
    s = _give(s, 0)
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="forest"))   # only 3 → below threshold
    assert s.players[0].resources.food == f0


def test_four_animals_grants_food():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "pig_market", revealed=True, accumulated_amount=4)
    s = _give(s, 0)
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="pig_market"))   # 4 boar staged → +1 food (before)
    assert s.players[0].resources.food == f0 + 1


def test_three_animals_no_food():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "pig_market", revealed=True, accumulated_amount=3)
    s = _give(s, 0)
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="pig_market"))   # only 3 → below threshold
    assert s.players[0].resources.food == f0
