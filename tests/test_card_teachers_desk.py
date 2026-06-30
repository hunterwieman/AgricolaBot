"""Tests for Teacher's Desk (minor improvement, C28; Corbarius Expansion).

Card text: "Each time you use the 'Major Improvement' or 'House Redevelopment'
action space, you can also play 1 occupation at an occupation cost of 1 food."
Cost: 1 Wood. Prerequisite: 1 Occupation. No VPs. Not passing.

Shape: an OPTIONAL `before_action_space` FireTrigger surfaced at the before-phase of
the two improvement-building hosts — Major Improvement (PendingSubActionSpace) and
House Redevelopment (PendingHouseRedevelopment). The text says "each time you use the
... action space" with NO "after" wording, so it rides `before_action_space`. Firing
pushes a PendingPlayOccupation with a flat 1-food cost; declining is simply not firing
(the player takes the host's mandatory ChooseSubAction / Proceed instead). Both spaces
are non-atomic and already hosted, so the card needs NO action-space hook — a single
registration covers both.
"""
from __future__ import annotations

import agricola.cards.teachers_desk  # noqa: F401  (registers the card)
import agricola.cards.consultant     # noqa: F401  (a real occupation to play)

from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingHouseRedevelopment,
    PendingPlayOccupation,
    PendingSubActionSpace,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_resources

CARD_ID = "teachers_desk"
_OCC = "consultant"   # on-play grants +3 clay (2p); no prereq

_POOL = CardPool(
    occupations=(_OCC,) + tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, "market_stall") + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _with_hand_occupation(state, idx, occ_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, hand_occupations=p.hand_occupations | {occ_id}) if i == idx
        else state.players[i] for i in range(2)))


def _empty_hand_occupations(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, hand_occupations=frozenset()) if i == idx
        else state.players[i] for i in range(2)))


def _place_major(state):
    """Place P0 at Major Improvement; the host frame is in its before-phase, where the
    trigger is surfaced. Requires the player to afford some major improvement."""
    state = step(state, PlaceWorker(space="major_improvement"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace)
    assert top.space_id == "major_improvement"
    assert top.phase == "before"
    return state


def _place_house_redev(state):
    """Place P0 at House Redevelopment; the host frame is in its before-phase (renovate
    still unchosen), where the trigger is surfaced. Requires the player to afford the
    renovate (wood->clay: num_rooms clay + 1 reed)."""
    state = step(state, PlaceWorker(space="house_redevelopment"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHouseRedevelopment)
    assert top.space_id == "house_redevelopment"
    assert top.phase == "before"
    assert not top.renovate_chosen
    return state


def _rich(state, idx):
    """Plenty of every building good so a major improvement / renovate is affordable."""
    return with_resources(state, idx, wood=20, clay=20, reed=20, stone=20, food=5)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_teachers_desk_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.min_occupations == 1          # prereq "1 Occupation"
    assert spec.max_occupations is None
    assert spec.vps == 0
    assert not spec.passing_left
    # Optional before_action_space trigger; NO action-space hook (both spaces hosted).
    bas = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert CARD_ID in bas
    # Not registered as a mandatory (auto) effect.
    aas_auto = OWN_ACTION_HOOK_CARDS.get("major_improvement", set())
    assert CARD_ID not in aas_auto


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_offered_at_major_improvement():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = _rich(s, cp)
    s = _place_major(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_offered_at_house_redevelopment():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = _rich(s, cp)
    s = _place_house_redev(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_not_offered_without_a_playable_hand_occupation():
    # Affordable food but no occupation in hand → no dead-end fire.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _empty_hand_occupations(s, cp)
    s = _rich(s, cp)
    s = _place_major(s)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_without_food():
    # Playable occupation, but the player cannot raise the 1-food cost (no food, no
    # liquidatable goods) → not offered.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    # Building goods to afford the major, but zero food and zero liquidatable crops/animals.
    s = with_resources(s, cp, wood=20, clay=20, reed=20, stone=20,
                       food=0, grain=0, veg=0)
    s = _place_major(s)
    assert s.players[cp].resources.food == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_without_the_card():
    # Without owning Teacher's Desk, the host fires no trigger (Family-style host).
    s, cp = _card_state()
    s = _with_hand_occupation(s, cp, _OCC)
    s = _rich(s, cp)
    s = _place_major(s)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_food_can_be_liquidated_for_the_cost():
    # No food on hand, but a crop the food-shortfall guard can liquidate → still offered.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=20, clay=20, reed=20, stone=20,
                       food=0, grain=3)
    s = _place_major(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


# ---------------------------------------------------------------------------
# The effect via the real engine flow
# ---------------------------------------------------------------------------

def test_fire_plays_occupation_for_one_food_at_major():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=20, clay=0, reed=20, stone=20, food=3)
    s = _place_major(s)
    food_before = s.players[cp].resources.food

    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)
    assert top.cost == Resources(food=1)          # flat 1-food cost on the frame
    assert top.phase == "before"

    # The play-occupation enumerator offers the hand occupation's commit.
    la = legal_actions(s)
    assert CommitPlayOccupation(card_id=_OCC) in la

    s = step(s, CommitPlayOccupation(card_id=_OCC))
    p = s.players[cp]
    assert p.resources.food == food_before - 1    # 1 food debited
    assert _OCC in p.occupations
    assert _OCC not in p.hand_occupations
    assert p.resources.clay == 3                   # consultant's +3 clay on-play
    # The play frame flips to its after-phase, then the Major Improvement host resumes
    # (the renovate/improvement work still ahead of us).
    assert s.pending_stack[-1].phase == "after"


def test_fire_plays_occupation_for_one_food_at_house_redev():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=20, clay=20, reed=20, stone=20, food=3)
    s = _place_house_redev(s)
    food_before = s.players[cp].resources.food

    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)
    assert top.cost == Resources(food=1)
    s = step(s, CommitPlayOccupation(card_id=_OCC))
    p = s.players[cp]
    assert p.resources.food == food_before - 1
    assert _OCC in p.occupations
    # The occupation's play frame is now in its after-phase; Stop pops it and returns to
    # the House Redevelopment host, whose mandatory renovate is still ahead (the before-
    # window play left the renovate->improvement->Proceed lifecycle intact).
    assert s.pending_stack[-1].phase == "after"
    assert Stop() in legal_actions(s)
    s = step(s, Stop())
    host = s.pending_stack[-1]
    assert isinstance(host, PendingHouseRedevelopment)
    assert not host.renovate_chosen
    # The mandatory renovate sub-action is offered (lifecycle intact).
    assert ChooseSubAction(name="renovate") in legal_actions(s)


def test_fires_once_per_use():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=20, clay=0, reed=20, stone=20, food=3)
    s = _place_major(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitPlayOccupation(card_id=_OCC))   # play the occupation
    s = step(s, Stop())                               # pop the after-phase play frame
    # Back at the Major Improvement host; already fired → not re-offered, even with a
    # second hand occupation available.
    s = _with_hand_occupation(s, cp, "o1")
    assert isinstance(s.pending_stack[-1], PendingSubActionSpace)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Optionality — declining = not firing
# ---------------------------------------------------------------------------

def test_optional_can_decline_by_proceeding_with_the_space():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = _rich(s, cp)
    s = _place_major(s)
    la = legal_actions(s)
    # Both firing AND the host's own mandatory ChooseSubAction are available —
    # optionality lives at the FireTrigger, not in the play host.
    assert FireTrigger(card_id=CARD_ID) in la
    assert ChooseSubAction(name="improvement") in la
    # Decline by taking the space's mandatory sub-action instead of firing.
    s = step(s, ChooseSubAction(name="improvement"))
    # The occupation was NOT played; it remains in hand.
    assert _OCC in s.players[cp].hand_occupations
    assert _OCC not in s.players[cp].occupations


# ---------------------------------------------------------------------------
# Wrong space does not fire
# ---------------------------------------------------------------------------

def test_does_not_fire_at_an_unrelated_space():
    # Farmland is a hosted non-atomic space but NOT one Teacher's Desk fires on.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = _rich(s, cp)
    s = step(s, PlaceWorker(space="farmland"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
