"""Tests for Sheep Rug (minor improvement, E21; Ephipparius).

Card text: "You can use any \"Wish for Children\" action space, even if it is
occupied by another player's person." Cost 1 Sheep; prereq 4 Sheep; 1 VP; kept.

The Sleeping Corner (A26) occupancy-override shape, with an animal cost/prereq.
Coverage:
  - registration (cost 1 sheep, prereq present, vps 1, override registered);
  - the relaxation through the REAL `legal_placements` path: the owner may place
    on a "Wish for Children" space occupied by one opponent, incl. the opponent's
    parent+newborn pair (count players, not workers);
  - boundaries: no ownership, owner already holds it, non-wish space, 2+ other
    players (== 1 only);
  - the "4 Sheep" prerequisite boundary (a have-check, distinct from the 1-sheep
    cost).
"""
import pytest

from agricola.actions import PlaceWorker
from agricola.cards.sheep_rug import CARD_ID, _occupancy_override
from agricola.cards.specs import MINORS, prereq_met
from agricola.legality import OCCUPANCY_OVERRIDE_EXTENSIONS, legal_placements
from agricola.resources import Animals, Cost
from agricola.setup import setup_env
import tests.factories as f

# Urgent Wish is legal whenever people_total < 5, isolating the occupancy override
# (Basic Wish additionally needs more rooms than people, which a setup state lacks).
WISH = "urgent_wish_for_children"


def _state(seed=5, *, owner=None):
    cs, _env = setup_env(seed, card_pool=None)
    cs = f.with_current_player(cs, 0)
    cs = f.with_space(cs, WISH, revealed=True)
    if owner is not None:
        cs = f.with_minors(cs, owner, frozenset({CARD_ID}))
    return cs


def _set_workers(cs, w):
    return f.with_space(cs, WISH, workers=w)


def _wish_placeable(cs):
    return PlaceWorker(space=WISH) in legal_placements(cs)


# --- registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert len(OCCUPANCY_OVERRIDE_EXTENSIONS) >= 1
    spec = MINORS[CARD_ID]
    assert spec.vps == 1
    assert spec.cost == Cost(animals=Animals(sheep=1))
    assert spec.prereq is not None


# --- the relaxation ---------------------------------------------------------

def test_owner_may_use_wish_occupied_by_opponent():
    cs = _state(owner=0)
    cs = _set_workers(cs, (0, 1))   # opponent (p1) holds the wish space
    assert _wish_placeable(cs)


def test_owner_may_use_wish_with_opponent_parent_and_newborn():
    # A normally-used wish space holds the opponent's parent + newborn = 2 workers,
    # ONE player. "Count players, not workers" must still permit the owner to use it.
    cs = _state(owner=0)
    cs = _set_workers(cs, (0, 2))
    assert _wish_placeable(cs)


# --- boundaries -------------------------------------------------------------

def test_not_offered_without_ownership():
    cs = _state(owner=None)
    cs = _set_workers(cs, (0, 1))
    assert not _wish_placeable(cs)


def test_not_offered_when_owner_already_holds_the_space():
    cs = _state(owner=0)
    cs = _set_workers(cs, (1, 0))   # the owner (p0) is the sole occupant
    assert not _wish_placeable(cs)


def test_override_does_not_apply_to_non_wish_spaces():
    cs = _state(owner=0)
    cs = f.with_space(cs, "forest", revealed=True, workers=(0, 1))
    assert PlaceWorker(space="forest") not in legal_placements(cs)


def test_two_other_players_blocks_override():
    # 4-player shape: 2+ OTHER players holding the space -> override declines (== 1).
    cs = _state(owner=0)
    cs = _set_workers(cs, (0, 1))
    cs3 = f.with_space(cs, WISH, workers=(0, 1, 1))   # two OTHER players
    assert _occupancy_override(cs3, WISH) is False
    assert _occupancy_override(cs, WISH) is True


def test_unoccupied_wish_placeable_regardless():
    cs = _state(owner=0)
    cs = _set_workers(cs, (0, 0))
    assert _wish_placeable(cs)


# --- prerequisite: 4 sheep --------------------------------------------------

@pytest.mark.parametrize("sheep,expected", [(0, False), (3, False), (4, True), (7, True)])
def test_prereq_four_sheep(sheep, expected):
    cs = _state(owner=0)
    cs = f.with_animals(cs, 0, sheep=sheep)
    assert prereq_met(MINORS[CARD_ID], cs, 0) is expected
