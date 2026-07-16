"""Tests for Loudmouth (D140) — an occupation granting +1 food each time you take
at least 4 building resources OR at least 4 animals from an accumulation space.

Bare "each time you take" + flat +1 food → an `after_action_space` automatic effect
(Refactor A): the threshold is read from what was actually TAKEN. A building space's
`taken` (wood+clay+reed+stone), stamped at the Proceed take (atomic → hooked), covers
the building clause; the market frame's staged `gained` covers the animal clause
(non-atomic → always hosted). Owner-gated. The reward is +1 FOOD, which never collides
with the take (building resources / animals), and a fresh farmyard cooks no market
overflow (animal rate 0), so the food delta isolates the reward.
"""
import agricola.cards.loudmouth  # noqa: F401  (registers the card)

from agricola.actions import CommitAccommodate, PlaceWorker, Proceed
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
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


def _drive_to_after(state):
    """Drive the hosted lifecycle to the after-window, where the after-auto fires:
    Proceed runs the take for an atomic host; CommitAccommodate flips a market host."""
    if isinstance(state.pending_stack[-1], PendingActionSpace):
        return step(state, Proceed())            # atomic: the take, then after-flip
    accs = [a for a in legal_actions(state) if isinstance(a, CommitAccommodate)]
    return step(state, accs[0])                  # market: any accommodation → after-flip


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
    s = step(s, PlaceWorker(space="forest"))
    s = _drive_to_after(s)                     # take 4 wood → after-auto: +1 food
    assert s.players[0].resources.food == f0 + 1


def test_three_building_resources_no_food():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "forest", revealed=True, accumulated=Resources(wood=3))
    s = _give(s, 0)
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="forest"))
    s = _drive_to_after(s)                     # only 3 taken → below threshold
    assert s.players[0].resources.food == f0


def test_four_animals_grants_food():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "pig_market", revealed=True, accumulated_amount=4)
    s = _give(s, 0)
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="pig_market"))   # 4 boar staged on gained
    s = _drive_to_after(s)                          # accommodate → after-auto: +1 food
    assert s.players[0].resources.food == f0 + 1


def test_three_animals_no_food():
    s = setup(seed=0)
    s = with_current_player(s, 0)
    s = with_space(s, "pig_market", revealed=True, accumulated_amount=3)
    s = _give(s, 0)
    f0 = s.players[0].resources.food
    s = step(s, PlaceWorker(space="pig_market"))   # only 3 → below threshold
    s = _drive_to_after(s)
    assert s.players[0].resources.food == f0
