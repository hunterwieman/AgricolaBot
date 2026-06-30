"""Tests for Forest School (minor improvement A28): two clauses.

  CLAUSE 1 — the LEGALITY RELAXATION (occupancy override) on Lessons: the owner may place on
    Lessons even when one opponent already occupies it; with boundaries (no ownership, owner
    already holds it, non-lessons spaces, 2+ other players).

  CLAUSE 2 — replace the occupation's food cost with wood: an optional `before_play_occupation`
    trigger (spend the food-cost in wood, get that much food) that is ALSO an occupation-cost
    food source. Covers: registration; the value/substitution firing; the affordability gate
    offering a play payable only via Forest School; the commit gate withholding the commit
    until it is fired; the free-first-occupation no-op (nothing to replace); once-per-play.

  Plus registration / cost / vps and Family byte-identity (no card -> occupied lessons illegal).
"""
import agricola.cards.forest_school  # noqa: F401

import pytest

from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
)
from agricola.cards.forest_school import CARD_ID, _occupancy_override
from agricola.cards.specs import MINORS, OCCUPATION_FOOD_SOURCES
from agricola.cards.triggers import TRIGGERS
from agricola.engine import step
from agricola.legality import (
    OCCUPANCY_OVERRIDE_EXTENSIONS,
    legal_actions,
    legal_placements,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env

import tests.factories as f

_POOL = CardPool(
    occupations=("consultant", "priest") + tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.vps == 1
    assert spec.cost.resources.wood == 1
    assert spec.cost.resources.clay == 1
    assert CARD_ID in OCCUPATION_FOOD_SOURCES
    assert any(e.card_id == CARD_ID
               for e in TRIGGERS.get("before_play_occupation", []))
    assert _occupancy_override in OCCUPANCY_OVERRIDE_EXTENSIONS


# ===========================================================================
# CLAUSE 1 — Lessons occupancy override
# ===========================================================================

def _lessons_state(seed=5, *, owner=None):
    """CARDS-mode state with Lessons revealed, p0 to move, and a playable (free first) occupation
    in p0's hand so `_legal_lessons_cards`' own affordability gate is satisfied — isolating the
    occupancy override. `owner=0` -> p0 owns Forest School. (Lessons is a CARDS-only space —
    illegal in the Family game — so this must be card mode.)"""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = f.with_current_player(cs, 0)
    cs = f.with_space(cs, "lessons", revealed=True)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset({"consultant"}),
                      resources=Resources(food=5))
    cs = fast_replace(cs, players=(p0, cs.players[1]))
    if owner is not None:
        cs = f.with_minors(cs, owner, frozenset({CARD_ID}))
    return cs


def _set_workers(cs, w):
    return f.with_space(cs, "lessons", workers=w)


def _lessons_placeable(cs):
    return PlaceWorker(space="lessons") in legal_placements(cs)


def test_owner_may_use_lessons_occupied_by_opponent():
    cs = _lessons_state(owner=0)
    cs = _set_workers(cs, (0, 1))   # opponent (p1) holds Lessons
    assert _lessons_placeable(cs)


def test_not_offered_without_ownership():
    cs = _lessons_state(owner=None)
    cs = _set_workers(cs, (0, 1))
    assert not _lessons_placeable(cs)


def test_not_offered_when_owner_already_holds_lessons():
    cs = _lessons_state(owner=0)
    cs = _set_workers(cs, (1, 0))   # owner (p0) is the sole occupant
    assert not _lessons_placeable(cs)


def test_override_does_not_apply_to_non_lessons_spaces():
    cs = _lessons_state(owner=0)
    cs = f.with_space(cs, "forest", revealed=True, workers=(0, 1))
    assert PlaceWorker(space="forest") not in legal_placements(cs)


def test_two_other_players_blocks_override():
    # 4-player shape: 2+ OTHER players holding the space -> override declines (== 1 only).
    cs = _lessons_state(owner=0)
    cs = _set_workers(cs, (0, 1))
    cs3 = f.with_space(cs, "lessons", workers=(0, 1, 1))
    assert _occupancy_override(cs3, "lessons") is False
    assert _occupancy_override(cs, "lessons") is True


def test_unoccupied_lessons_uses_normal_legality():
    # The override is irrelevant when the space is unoccupied; normal legality applies. With a
    # playable, affordable occupation in hand (set by the helper) and Lessons free, it is placeable.
    cs = _lessons_state(owner=0)
    cs = _set_workers(cs, (0, 0))
    assert _lessons_placeable(cs)


# ===========================================================================
# CLAUSE 2 — replace the occupation's food cost with wood
# ===========================================================================

def _play_state(*, owned=(CARD_ID,), occupations=(), hand=("consultant",), food=0, wood=0):
    """p0 owns the listed minors + has the listed occupations already in front of them, with the
    given hand and resources. (`occupations` non-empty makes the next play cost 1 food.)"""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        minor_improvements=frozenset(owned),
        occupations=frozenset(occupations),
        hand_occupations=frozenset(hand),
        resources=Resources(food=food, wood=wood),
    )
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _spaces(cs):
    return {a.space for a in legal_placements(cs)}


def _to_play_occupation(cs):
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    return cs


def test_substitution_fires_and_pays_in_wood():
    # 0 food, 1 wood, own Forest School, play a 2nd occupation (cost 1 food). The commit is
    # withheld (food short) — only the substitution is offered; firing it converts 1 wood -> 1
    # food, then the commit unlocks and the occupation is paid for in food (raised from wood).
    cs, cp = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=1)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="consultant") not in la   # withheld: food short
    assert FireTrigger(card_id=CARD_ID) in la

    cs = step(cs, FireTrigger(card_id=CARD_ID))                    # 1 wood -> 1 food
    p = cs.players[cp]
    assert p.resources.wood == 0
    assert p.resources.food == 1
    assert CommitPlayOccupation(card_id="consultant") in legal_actions(cs)   # now unlocked

    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    p = cs.players[cp]
    assert "consultant" in p.occupations
    assert p.resources.food == 0          # raised 1 from wood, paid the 1-food cost
    assert p.resources.wood == 0
    assert p.resources.clay == 3          # consultant's on-play ran


def test_lessons_offered_only_via_forest_school():
    # 0 food, 0 liquidation fuel, 1 wood, own Forest School: the 2nd occupation's 1-food cost is
    # payable only by firing the substitution first — Lessons must be offered (the gate consults
    # the food source). Without the wood it must NOT be offered.
    cs, _ = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=1)
    assert "lessons" in _spaces(cs)
    cs_nowood, _ = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=0)
    assert "lessons" not in _spaces(cs_nowood)


def test_not_offered_for_free_first_occupation():
    # The free first occupation costs 0 food: nothing to replace, so the substitution is NOT
    # offered (no pointless 0-wood -> 0-food no-op).
    cs, _cp = _play_state(occupations=(), hand=("consultant",), food=0, wood=2)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert CommitPlayOccupation(card_id="consultant") in la   # free, immediately committable


def test_substitution_optional_when_food_on_hand():
    # With food already on hand the player may decline (pay food) OR substitute. Both the commit
    # and the FireTrigger are offered; the commit alone pays food and leaves wood untouched.
    cs, cp = _play_state(occupations=("priest",), hand=("consultant",), food=5, wood=2)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID) in la
    assert CommitPlayOccupation(card_id="consultant") in la
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))   # decline: pay food
    p = cs.players[cp]
    assert p.resources.food == 4          # 5 - 1, paid in food
    assert p.resources.wood == 2          # untouched


def test_substitution_once_per_play():
    # "each food" is 1 food in the 2p game -> a single fire suffices and the trigger is consumed
    # (host `triggers_resolved`): after firing once it is no longer offered this play.
    cs, cp = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=3)
    cs = _to_play_occupation(cs)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id=CARD_ID))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)   # consumed for this play
    assert cs.players[cp].resources.wood == 2   # only one wood spent


@pytest.mark.parametrize("wood,expected", [(0, None), (1, (1, Resources(wood=1)))])
def test_food_source_contract(wood, expected):
    # The food source reports (food_produced, inputs) when firing is possible, else None — for a
    # next occupation costing 1 food (one already in front).
    from agricola.cards.forest_school import _food_source
    cs, _cp = _play_state(occupations=("priest",), hand=("consultant",), food=0, wood=wood)
    assert _food_source(cs, cs.current_player) == expected


def test_food_source_none_for_free_first_occupation():
    # No occupations in front -> next play is free -> nothing to produce.
    from agricola.cards.forest_school import _food_source
    cs, _cp = _play_state(occupations=(), hand=("consultant",), food=0, wood=2)
    assert _food_source(cs, cs.current_player) is None
