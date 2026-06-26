"""Tests for the play-occupation foundation (CARD_IMPLEMENTATION_PLAN.md II.4):
the Lessons space in card mode, PendingPlayOccupation, the occupation-cost ramp,
the OccupationSpec registry, and the first two on-play occupations (Consultant,
Priest). The scoring-card path (Stable Architect) and minors land next.
"""
import pytest

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import GameMode, HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions, legal_placements, occupation_cost
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env

_POOL = CardPool(
    occupations=("consultant", "priest") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state_with_hand(seed=5, *, occupations=frozenset(),
                          hand=frozenset(), house=None, food=None):
    """A card-mode round-1 state with the current player's hand/tableau set
    deterministically (the random deal is replaced so plays are reproducible)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    changes = {"hand_occupations": hand, "occupations": occupations}
    if house is not None:
        changes["house_material"] = house
    if food is not None:
        changes["resources"] = fast_replace(p.resources, food=food)
    p = fast_replace(p, **changes)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _spaces(state):
    return {a.space for a in legal_placements(state)}


# ---------------------------------------------------------------------------
# Registry + mode gating
# ---------------------------------------------------------------------------

def test_occupations_registered():
    assert "consultant" in OCCUPATIONS
    assert "priest" in OCCUPATIONS


def test_lessons_never_legal_in_family():
    # Even handed a populated hand, the Family game never surfaces Lessons.
    s = setup(5)
    cp = s.current_player
    p = fast_replace(s.players[cp], hand_occupations=frozenset({"consultant"}))
    s = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    assert s.mode is GameMode.FAMILY
    assert "lessons" not in _spaces(s)


def test_lessons_needs_a_playable_occupation():
    # Empty hand -> not legal.
    cs, _ = _card_state_with_hand(hand=frozenset())
    assert "lessons" not in _spaces(cs)
    # A hand with only an UNREGISTERED occupation -> not playable -> not legal.
    cs, _ = _card_state_with_hand(hand=frozenset({"o3"}))
    assert "lessons" not in _spaces(cs)
    # A registered, playable occupation -> legal.
    cs, _ = _card_state_with_hand(hand=frozenset({"consultant"}))
    assert "lessons" in _spaces(cs)


# ---------------------------------------------------------------------------
# Playing an occupation
# ---------------------------------------------------------------------------

def test_play_consultant_via_lessons():
    cs, cp = _card_state_with_hand(hand=frozenset({"consultant"}))
    assert cs.players[cp].resources.clay == 0

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # singleton: push PendingPlayOccupation
    assert legal_actions(cs) == [CommitPlayOccupation(card_id="consultant")]

    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    p = cs.players[cp]
    assert p.resources.clay == 3                      # 2-player branch: +3 clay
    assert "consultant" in p.occupations              # moved to tableau
    assert "consultant" not in p.hand_occupations     # removed from hand
    cs = step(cs, Stop())                             # pop PendingPlayOccupation's after-phase
    cs = step(cs, Stop())                             # pop PendingSubActionSpace (lessons host)
    assert cs.pending_stack == ()                     # frame popped, turn ends


def test_first_occupation_is_free_later_costs_one_food():
    assert occupation_cost(0).food == 0
    assert occupation_cost(1).food == 1

    # Already played 1 occupation -> the next costs 1 food (debited at play).
    cs, cp = _card_state_with_hand(
        occupations=frozenset({"priest"}), hand=frozenset({"consultant"}), food=2,
    )
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # singleton: push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    assert cs.players[cp].resources.food == 1         # 2 - 1


def test_lessons_unaffordable_when_food_short():
    # Owe 1 food (1 occupation already played) but hold 0 food -> Lessons not legal.
    cs, _ = _card_state_with_hand(
        occupations=frozenset({"priest"}), hand=frozenset({"consultant"}), food=0,
    )
    assert "lessons" not in _spaces(cs)


# ---------------------------------------------------------------------------
# Priest — conditional on-play effect
# ---------------------------------------------------------------------------

def test_priest_grants_in_clay_house_with_two_rooms():
    cs, cp = _card_state_with_hand(hand=frozenset({"priest"}), house=HouseMaterial.CLAY)
    before = cs.players[cp].resources
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # singleton: push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="priest"))
    after = cs.players[cp].resources
    assert (after.clay - before.clay, after.reed - before.reed,
            after.stone - before.stone) == (3, 2, 2)
    assert "priest" in cs.players[cp].occupations


def test_priest_grants_nothing_in_wood_house_but_is_still_played():
    cs, cp = _card_state_with_hand(hand=frozenset({"priest"}))  # default wood house
    before = cs.players[cp].resources
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # singleton: push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="priest"))
    after = cs.players[cp].resources
    assert after == before                              # condition false -> no gain
    assert "priest" in cs.players[cp].occupations       # but the card is still played
