"""Tests for Tree Guard (occupation, C102; Corbarius Expansion; players 1+).

Card text: "Each time after you use a wood accumulation space, you can place 4 wood
from your supply on that space to get 2 stone, 1 clay, 1 reed, and 1 grain."
No cost / prereq / VPs; not passing.

Shape: an OPTIONAL `after_action_space` FireTrigger on the atomic-hosted Forest
(the only wood accumulation space on the 2-player board). The atomic Forest host
runs its +3 wood pickup on Proceed FIRST, then flips to the after-phase where this
trigger is surfaced — so the "have 4 wood to place" check reads the POST-pickup
supply. Firing PLACES 4 wood from the player's supply ONTO the Forest's accumulated
pile (not the general supply) and grants 2 stone / 1 clay / 1 reed / 1 grain in
return; declining is not firing (the host's Stop exits without the exchange).
"""
from __future__ import annotations

import agricola.cards.tree_guard  # noqa: F401  (registers the card)

from agricola.actions import (
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources

CARD_ID = "tree_guard"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _place_forest_to_after(state):
    """Place P0 at the (already-revealed) Forest and Proceed past the pickup so the
    host frame is in its after-phase (where the trigger is surfaced). Returns the
    after-phase state. Forest accrues +3 wood on Proceed and is emptied."""
    state = step(state, PlaceWorker(space="forest"))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())                 # +3 wood, empty space, flip to after
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_tree_guard_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID not in MINORS                    # it is an occupation, not a minor
    # Optional after_action_space trigger + an atomic Forest host.
    aas = {e.card_id for e in TRIGGERS.get("after_action_space", [])}
    assert CARD_ID in aas
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("forest", set())


def test_on_play_is_noop():
    state, _cp = _card_state()
    after = OCCUPATIONS[CARD_ID].on_play(state, 0)
    assert after == state


# ---------------------------------------------------------------------------
# Eligibility boundaries (need >= 4 wood in supply, post-pickup)
# ---------------------------------------------------------------------------

def test_offered_with_four_wood_after_pickup():
    # 1 wood + Forest's 3 = 4 (the threshold, AFTER pickup) → offered.
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=1)
    s = _place_forest_to_after(s)
    assert s.players[cp].resources.wood == 4        # post-pickup
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_not_offered_with_three_wood_after_pickup():
    # 0 wood + 3 = 3 < 4 → cannot place 4, not offered.
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=0)
    s = _place_forest_to_after(s)
    assert s.players[cp].resources.wood == 3        # post-pickup, just under
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_offered_with_abundant_wood():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=10)
    s = _place_forest_to_after(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_not_offered_without_card():
    # Without the card, Forest is NOT hosted (atomic fast path): placing resolves
    # immediately, no host frame, no trigger.
    s, cp = _card_state()
    s = with_resources(s, cp, wood=10)
    s = step(s, PlaceWorker(space="forest"))
    assert not s.pending_stack                      # resolved atomically
    assert s.players[cp].resources.wood == 13       # 10 + 3 pickup, no exchange


# ---------------------------------------------------------------------------
# The effect via the real engine flow
# ---------------------------------------------------------------------------

def test_fire_places_four_wood_and_grants_goods():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=4, stone=0, clay=0, reed=0, grain=0)
    s = _place_forest_to_after(s)
    assert s.players[cp].resources.wood == 7        # 4 + 3 pickup
    forest_before = get_space(s.board, "forest").accumulated.wood
    assert forest_before == 0                       # space emptied by its own pickup

    s = step(s, FireTrigger(card_id=CARD_ID))

    p = s.players[cp].resources
    # -4 wood from supply, +2 stone / +1 clay / +1 reed / +1 grain.
    assert p.wood == 3                              # 7 - 4
    assert p.stone == 2
    assert p.clay == 1
    assert p.reed == 1
    assert p.grain == 1
    # The 4 wood was PLACED ONTO the Forest's accumulated pile, not discarded.
    assert get_space(s.board, "forest").accumulated.wood == 4

    # Firing pushes no sub-decision; the host is back at its after-phase, the
    # trigger already resolved, so the only exit is Stop.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert Stop() in legal_actions(s)


def test_fires_once_per_use():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=10)
    s = _place_forest_to_after(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    # Already fired this host-visit → not re-offered even though still >= 4 wood.
    assert s.players[cp].resources.wood >= 4
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Optionality — declining = not firing
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_stop():
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=8, stone=0, clay=0, reed=0, grain=0)
    s = _place_forest_to_after(s)
    la = legal_actions(s)
    # Both firing AND declining (the host's Stop) are available — optionality lives
    # at the FireTrigger.
    assert FireTrigger(card_id=CARD_ID) in la
    assert Stop() in la
    s = step(s, Stop())                             # decline → host exits, turn ends
    assert not s.pending_stack                      # Forest use complete
    p = s.players[cp].resources
    assert p.wood == 11                             # 8 + 3 pickup, no 4 spent
    assert p.stone == 0 and p.clay == 0 and p.reed == 0 and p.grain == 0
    # No deposit onto the space either.
    assert get_space(s.board, "forest").accumulated.wood == 0


# ---------------------------------------------------------------------------
# Wrong space / wrong event does not fire
# ---------------------------------------------------------------------------

def test_clay_pit_does_not_fire():
    # Clay Pit is an accumulation space, but CLAY not wood — Tree Guard is not
    # hooked on it, so the space stays atomic (no host) and nothing fires.
    s, cp = _card_state()
    s = _own_occ(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=10)
    sp = fast_replace(get_space(s.board, "clay_pit"), revealed=True, workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "clay_pit", sp))
    s = step(s, PlaceWorker(space="clay_pit"))
    # Not hosted for this card → resolves atomically, no FireTrigger anywhere.
    assert not s.pending_stack
