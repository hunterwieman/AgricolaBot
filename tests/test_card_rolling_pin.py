"""Tests for Rolling Pin (minor improvement, D52; Dulcinaria Expansion).

Card text: "In the returning home phase of each round, if you have more clay
than wood in your supply, you get 1 food."

An automatic effect (ruling 21: "you get" is choice-free) on the round-end
ladder's ``returning_home`` window (ruling 49, 2026-07-12) — the same window
Swimming Class fires on, so the fire tests drive the REAL round-end walk
(`_advance_until_decision` on a drained WORK state, every person placed) and
read the resulting food. It fires EVERY round, harvest rounds included (the
returning-home phase precedes the harvest), gated only on clay > wood in supply.
"""
from __future__ import annotations

import agricola.cards.rolling_pin  # noqa: F401  (register the card)

from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from tests.factories import with_resources

CARD_ID = "rolling_pin"


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx,
                        minor_improvements=p.minor_improvements | {CARD_ID})


def _drained_work_state(*, round_number=1, seed=0):
    """A WORK state with every person placed (people_home=0 for both), so the
    next _advance_until_decision walks the round-end ladder (returning_home)."""
    state = setup(seed)
    state = fast_replace(state, phase=Phase.WORK, round_number=round_number)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _food(state, idx=0):
    return state.players[idx].resources.food


# --- Registration -----------------------------------------------------------

def test_registration():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))   # cost: 1 wood
    assert spec.min_occupations == 1                        # prereq: 1 occupation
    assert spec.vps == 0
    assert not spec.passing_left
    assert any(e.card_id == CARD_ID
               for e in AUTO_EFFECTS.get("returning_home", ()))


# --- The fire, through the real round-end walk --------------------------------

def test_food_when_clay_exceeds_wood():
    state = _own_minor(_drained_work_state(), 0)
    state = with_resources(state, 0, clay=2)        # clay 2 > wood 0; food 0
    food0 = _food(state)
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION          # round 1: no harvest
    assert _food(state) == food0 + 1


def test_no_food_when_clay_equals_wood():
    state = _own_minor(_drained_work_state(), 0)
    state = with_resources(state, 0, clay=2, wood=2)  # clay == wood -> nothing
    food0 = _food(state)
    state = _advance_until_decision(state)
    assert _food(state) == food0


def test_no_food_when_wood_exceeds_clay():
    state = _own_minor(_drained_work_state(), 0)
    state = with_resources(state, 0, clay=1, wood=3)  # clay < wood -> nothing
    food0 = _food(state)
    state = _advance_until_decision(state)
    assert _food(state) == food0


def test_fires_on_harvest_round_before_harvest():
    """"each round" is unconditioned on the round kind: on round 4 the food is
    granted in the returning-home phase, BEFORE the harvest feeding is paid — so
    at the harvest pause the +1 is already in supply, un-touched by feeding
    (feeding is a still-pending decision at that point)."""
    state = _own_minor(_drained_work_state(round_number=4), 0)
    state = with_resources(state, 0, clay=2)
    food0 = _food(state)
    state = _advance_until_decision(state)
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)
    assert _food(state) == food0 + 1


def test_scopes_to_owner():
    """Ownership-gated per player: only the owner (player 1) gains, even though
    player 0 also has clay > wood."""
    state = _drained_work_state()
    state = _own_minor(state, 1)
    state = with_resources(state, 0, clay=2)   # eligible-looking but UNowned
    state = with_resources(state, 1, clay=2)
    f0, f1 = _food(state, 0), _food(state, 1)
    state = _advance_until_decision(state)
    assert _food(state, 0) == f0        # unowned -> nothing
    assert _food(state, 1) == f1 + 1    # owner -> +1


def test_unowned_does_not_fire():
    state = _drained_work_state()
    state = with_resources(state, 0, clay=2)   # clay > wood, but not owned
    food0 = _food(state)
    state = _advance_until_decision(state)
    assert _food(state) == food0
