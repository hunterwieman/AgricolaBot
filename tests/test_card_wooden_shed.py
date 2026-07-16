"""Tests for Wooden Shed (minor improvement, D9).

Card text: "This card can only be played via a 'Major Improvement' action. It provides
room for one person. You may no longer renovate." Cost 2 wood, 1 reed; prereq Still in
Wooden House.

Three effects: +1 PEOPLE-capacity; playable ONLY via the "Major or Minor Improvement"
action (composite-only); and a renovation ban (the Mantlepiece seam).
"""
import agricola.cards.wooden_shed  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import HouseMaterial
from agricola.legality import (
    _housing_capacity,
    _legal_basic_wish_for_children,
    _legal_farm_redevelopment,
    _legal_house_redevelopment,
    _legal_renovate_targets,
    legal_actions,
    playable_minors,
)
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from tests.factories import (
    with_current_player,
    with_house,
    with_minors,
    with_pending_stack,
    with_people,
    with_resources,
    with_space,
)

CARD_ID = "wooden_shed"


def _hand(state, idx, cards):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, hand_minors=frozenset(cards)) if i == idx
        else state.players[i] for i in range(2)))


def _own(state, idx):
    return with_minors(state, idx, state.players[idx].minor_improvements | {CARD_ID})


# --- Registration / cost / prereq -------------------------------------------

def test_registration_cost_and_prereq():
    assert CARD_ID in MINORS
    assert MINORS[CARD_ID].cost == Cost(resources=Resources(wood=2, reed=1))
    s = setup(seed=0)                                   # WOOD house
    assert prereq_met(MINORS[CARD_ID], s, 0) is True
    assert prereq_met(MINORS[CARD_ID], with_house(s, 0, HouseMaterial.CLAY), 0) is False


# --- Capacity + gate flip ----------------------------------------------------

def test_capacity_and_gate_flip():
    base = with_people(with_space(with_current_player(setup(seed=0), 0),
                                  "basic_wish_for_children", revealed=True), 0, total=2)
    assert _legal_basic_wish_for_children(base) is False
    withcard = _own(base, 0)
    assert _housing_capacity(withcard, 0) == 3          # 2 rooms + 1
    assert _legal_basic_wish_for_children(withcard) is True


# --- Composite-only play restriction -----------------------------------------

def test_playable_only_via_composite_action():
    s = with_resources(setup(seed=0), 0, wood=2, reed=1)  # WOOD house, affordable
    s = _hand(s, 0, {CARD_ID})
    assert playable_minors(s, 0, composite_only_ok=True) == [CARD_ID]
    assert playable_minors(s, 0, composite_only_ok=False) == []   # bare routes exclude it


def test_frame_origin_gates_the_offer():
    """Offered on a composite play-minor frame; NOT on a bare one (Meeting Place)."""
    s = with_current_player(with_resources(setup(seed=0), 0, wood=2, reed=1), 0)
    s = _hand(s, 0, {CARD_ID})

    comp = with_pending_stack(s, [PendingPlayMinor(
        player_idx=0, initiated_by_id="major_minor_improvement")])
    assert any(isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
               for a in legal_actions(comp))

    bare = with_pending_stack(s, [PendingPlayMinor(
        player_idx=0, initiated_by_id="space:meeting_place")])
    assert not any(isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                   for a in legal_actions(bare))


def test_prereq_still_gates_on_composite_route():
    """Even via the composite, a non-wooden house makes it unplayable (the prereq)."""
    s = with_house(with_resources(setup(seed=0), 0, wood=2, reed=1), 0, HouseMaterial.CLAY)
    s = _hand(s, 0, {CARD_ID})
    assert playable_minors(s, 0, composite_only_ok=True) == []


# --- "You may no longer renovate" --------------------------------------------

def test_renovation_forbidden_for_owner():
    s = with_resources(setup(seed=0), 0, clay=5, reed=2)   # WOOD house, renovation affordable
    assert _legal_renovate_targets(s, s.players[0]) == [HouseMaterial.CLAY]   # without card
    s2 = _own(s, 0)
    assert _legal_renovate_targets(s2, s2.players[0]) == []                   # forbidden

    s2 = with_current_player(s2, 0)
    s2 = with_space(with_space(s2, "house_redevelopment", revealed=True),
                    "farm_redevelopment", revealed=True)
    assert _legal_house_redevelopment(s2) is False
    assert _legal_farm_redevelopment(s2) is False


def test_mantlepiece_renovation_ban_still_works():
    """Regression: Mantlepiece's ban moved from a hardcode to the shared forbid registry."""
    s = with_resources(setup(seed=0), 0, clay=5, reed=2)
    s = with_minors(s, 0, frozenset({"mantlepiece"}))
    assert _legal_renovate_targets(s, s.players[0]) == []
