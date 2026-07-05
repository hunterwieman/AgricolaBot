"""Tests for Town Hall (minor improvement, E48; Ephipparius Expansion; players -).

Card text: "In the feeding phase of each harvest, if you live in a clay or stone
house, you get 1 or 2 food, respectively."

Cost 2 Wood, 2 Clay; VPs 2. A choice-free feeding-income auto on the ``"feeding"``
window, conditioned on house material: wood -> nothing, clay -> 1 food, stone ->
2 food, delivered at the FEED entry (before the payment decision).
"""
from __future__ import annotations

import agricola.cards.town_hall  # noqa: F401  (register the card)

from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS
from agricola.cards.town_hall import CARD_ID
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import HouseMaterial, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import GameState

from tests.factories import with_house, with_phase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {CARD_ID})


def _harvest_state(seed=0, food=10):
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = _edit_player(state, idx, resources=fast_replace(
            state.players[idx].resources, food=food))
    return state


def _run_harvest(state, pick=lambda acts: acts[0]):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=2, clay=2))
    assert spec.vps == 2
    assert spec.min_occupations == 0 and spec.prereq is None


def test_registered_on_feeding_window():
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("feeding", ())}
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("feeding", set())


# ---------------------------------------------------------------------------
# The income (by house material)
# ---------------------------------------------------------------------------

def test_wood_house_grants_nothing():
    state = _own(_harvest_state(food=10), 0)
    state = with_house(state, 0, HouseMaterial.WOOD)
    f0 = state.players[0].resources.food
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 - 4     # feeding only, no income


def test_clay_house_grants_one_food():
    state = _own(_harvest_state(food=10), 0)
    state = with_house(state, 0, HouseMaterial.CLAY)
    f0 = state.players[0].resources.food
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 + 1 - 4


def test_stone_house_grants_two_food():
    state = _own(_harvest_state(food=10), 0)
    state = with_house(state, 0, HouseMaterial.STONE)
    f0 = state.players[0].resources.food
    after = _run_harvest(state)
    assert after.players[0].resources.food == f0 + 2 - 4


# ---------------------------------------------------------------------------
# Payability
# ---------------------------------------------------------------------------

def test_income_is_payable_before_feeding_decision():
    """A stone-house Town Hall owner with 2 food feeds 2 adults (4 food) with no
    begging — the +2 income arrives BEFORE the payment decision."""
    state = _own(_harvest_state(food=2), 0)
    state = with_house(state, 0, HouseMaterial.STONE)
    state = _edit_player(state, 1, resources=fast_replace(
        state.players[1].resources, food=10))
    after = _run_harvest(state)
    assert after.players[0].resources.food == 0          # 2 + 2 − 4
    assert after.players[0].begging_markers == 0


# ---------------------------------------------------------------------------
# Owner-gating
# ---------------------------------------------------------------------------

def test_non_owner_gets_no_income():
    """The opponent, who does not own Town Hall, gets no feeding income even in a
    stone house."""
    state = _own(_harvest_state(food=10), 0)
    state = with_house(state, 1, HouseMaterial.STONE)    # opponent, NOT an owner
    f1 = state.players[1].resources.food
    after = _run_harvest(state)
    assert after.players[1].resources.food == f1 - 4     # feeding only, no income
