"""Tests for Lodger (occupation, C133; players 3+, so injected, never dealt in 2p).

Card text: "This card provides room for one person, but only until the returning home
phase of round 9. If, by then, there is no room elsewhere for that person, remove it
from play." ("If you remove it from play, it can never grow back.")

Two effects: (1) a +1 PEOPLE-capacity bonus active only through round 9; (2) an
automatic round-9 `returning_home` eviction that removes the Lodger-housed person
(people_total -= 1) WITHOUT replenishing workers_in_supply, so the reachable family
size drops to 4 permanently. Also exercises the new `workers_in_supply` growth resource.
"""
import agricola.cards.lodger  # noqa: F401  (registers the card)

from agricola.cards.lodger import _capacity_bonus, _evict_eligible
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import apply_auto_effects
from agricola.constants import CellType, Phase
from agricola.engine import _advance_round_end
from agricola.legality import _housing_capacity, _legal_basic_wish_for_children
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import Cell
from tests.factories import (
    with_current_player,
    with_grid,
    with_people,
    with_round,
    with_space,
)

CARD_ID = "lodger"


def _own(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))


def _rooms(state, idx, n):
    """Force exactly n ROOM cells (default 2 at (1,0),(2,0); add along row 0)."""
    overrides = {(0, c): Cell(cell_type=CellType.ROOM) for c in range(n - 2)}
    return with_grid(state, idx, overrides)


# --- Registration + capacity bonus ------------------------------------------

def test_registration_and_noop_on_play():
    assert CARD_ID in OCCUPATIONS
    s = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) is s


def test_capacity_active_through_round_9_then_gone():
    s = _own(setup(seed=0), 0)
    assert _capacity_bonus(with_round(s, 1), 0) == 1
    assert _capacity_bonus(with_round(s, 9), 0) == 1
    assert _capacity_bonus(with_round(s, 10), 0) == 0


def test_gate_flips_with_lodger():
    """2 rooms, 2 people (supply 3): no spare room -> Basic Wish illegal. Lodger's +1
    (round <= 9) makes capacity 3 > 2 -> legal."""
    base = with_round(with_space(with_current_player(setup(seed=0), 0),
                                 "basic_wish_for_children", revealed=True), 5)
    base = with_people(base, 0, total=2)               # supply 3
    assert _legal_basic_wish_for_children(base) is False
    withcard = _own(base, 0)
    assert _housing_capacity(withcard, 0) == 3
    assert _legal_basic_wish_for_children(withcard) is True


# --- workers_in_supply: growth decrements it, cap is supply-based -------------

def test_growth_decrements_workers_in_supply():
    """Growing into the Lodger slot spends a supply meeple; at supply 0 the family cap
    blocks further growth even below 5 people (the point of the resource)."""
    from agricola.actions import PlaceWorker
    from agricola.engine import step
    s = with_round(with_space(with_current_player(setup(seed=0), 0),
                              "basic_wish_for_children", revealed=True), 5)
    s = _own(s, 0)
    s = with_people(s, 0, total=2, home=2, supply=1)   # only 1 meeple left in supply
    assert s.players[0].workers_in_supply == 1
    s = step(s, PlaceWorker(space="basic_wish_for_children"))
    # PendingFamilyGrowth (place_on_space) then commit; drive to completion.
    from agricola.legality import legal_actions
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    assert s.players[0].people_total == 3
    assert s.players[0].workers_in_supply == 0         # supply spent


# --- The round-9 returning-home eviction -------------------------------------

def _round9_return_home(idx=0, *, rooms=2, people=3, supply=2):
    """A round-9 RETURN_HOME state where P`idx` owns Lodger and has `people` people."""
    s = with_round(setup(seed=0), 9)
    s = fast_replace(s, phase=Phase.RETURN_HOME, starting_player=0)
    s = _own(s, idx)
    if rooms != 2:
        s = _rooms(s, idx, rooms)
    s = with_people(s, idx, total=people, home=0, supply=supply)
    return s


def test_evicts_when_no_room_elsewhere():
    """3 people in 2 rooms (the 3rd relies on Lodger): round-9 returning-home removes it,
    people_total drops to 2, and workers_in_supply is NOT replenished -> max family 4."""
    s = _round9_return_home(rooms=2, people=3, supply=2)
    assert _evict_eligible(s, 0) is True
    s, paused = _advance_round_end(s)
    assert paused is False
    p = s.players[0]
    assert p.people_total == 2                          # one removed
    assert p.workers_in_supply == 2                     # NOT replenished
    assert p.people_total + p.workers_in_supply == 4    # meeple gone from the game
    assert CARD_ID in p.fired_once                      # one-shot latched


def test_evicts_the_newborn_when_one_exists():
    """A round-9 newborn is the over-capacity overflow: eviction removes it (both
    people_total and newborns drop), so it is not fed at round 9's harvest."""
    s = _round9_return_home(rooms=2, people=3, supply=2)
    s = with_people(s, 0, total=3, home=0, supply=2, newborns=1)
    s, _ = _advance_round_end(s)
    p = s.players[0]
    assert p.people_total == 2
    assert p.newborns == 0                              # the newborn was the one removed
    assert p.workers_in_supply == 2


def test_no_eviction_when_housed_elsewhere():
    """3 people in 3 rooms: everyone has a real room, Lodger's person is spare -> no removal."""
    s = _round9_return_home(rooms=3, people=3, supply=2)
    assert _evict_eligible(s, 0) is False
    s, _ = _advance_round_end(s)
    assert s.players[0].people_total == 3
    assert CARD_ID not in s.players[0].fired_once


def test_no_eviction_before_round_9():
    s = _round9_return_home(rooms=2, people=3, supply=2)
    s = with_round(s, 7)
    assert _evict_eligible(s, 0) is False


def test_non_owner_unaffected():
    s = _round9_return_home(rooms=2, people=3, supply=2)
    # P1 does not own Lodger; the auto is owner-gated in apply_auto_effects.
    s2 = apply_auto_effects(s, "returning_home", 1)
    assert s2.players[1].people_total == s.players[1].people_total
