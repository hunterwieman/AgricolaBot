"""Tests for Forestry Studies (minor improvement, B28; Bubulcus Expansion).

Card text: "Each time after you use the 'Forest' accumulation space, you can return
2 wood to that space to play 1 occupation without paying an occupation cost."
Cost: 2 Food. No prerequisite. No VPs. Not passing.

Shape: an OPTIONAL `after_action_space` FireTrigger on the atomic-hosted Forest (the
only wood accumulation space on the 2-player board). The atomic Forest host runs its
wood pickup on Proceed FIRST, then flips to the after-phase where this trigger is
surfaced — so "return 2 wood to that space" reads the POST-pickup supply. Firing
debits 2 wood (placing it back on the Forest space) and pushes a FREE
PendingPlayOccupation (cost=Resources()); declining is not firing (the host's Stop
exits without playing).
"""
from __future__ import annotations

import agricola.cards.forestry_studies  # noqa: F401  (registers the card)
import agricola.cards.consultant        # noqa: F401  (a real free occupation to play)

from agricola.actions import (
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingPlayOccupation
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources

CARD_ID = "forestry_studies"
_OCC = "consultant"   # plays free (its on-play just grants +3 clay in 2p)

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
    """Put a registered, playable occupation in player `idx`'s hand."""
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, hand_occupations=p.hand_occupations | {occ_id}) if i == idx
        else state.players[i] for i in range(2)))


def _empty_hand_occupations(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, hand_occupations=frozenset()) if i == idx
        else state.players[i] for i in range(2)))


def _place_forest_to_after(state):
    """Place P0 at the (already-revealed) Forest and Proceed past the pickup so the
    host frame is in its after-phase (where the trigger is surfaced). Returns the
    after-phase state. Forest accrues its wood pickup on Proceed."""
    state = step(state, PlaceWorker(space="forest"))
    # Forest is atomic-hosted (P0 owns the card) → before-phase, only Proceed legal.
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())                 # pickup, flip to after-phase
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_forestry_studies_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=2))
    assert spec.prereq is None
    assert spec.vps == 0
    assert not spec.passing_left
    # Optional after_action_space trigger + an atomic Forest host.
    aas = {e.card_id for e in TRIGGERS.get("after_action_space", [])}
    assert CARD_ID in aas
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("forest", set())


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_offered_with_two_wood_and_a_hand_occupation():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=0)               # rely on Forest's pickup for the wood
    s = _place_forest_to_after(s)
    assert s.players[cp].resources.wood >= 2        # post-pickup
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_not_offered_with_fewer_than_two_wood():
    # 0 wood and a Forest that only yields 1 on this seed would fail; force it
    # by zeroing the space's accumulated so the pickup is 0.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=0)
    sp = fast_replace(get_space(s.board, "forest"), accumulated=Resources(wood=1))
    s = fast_replace(s, board=with_space(s.board, "forest", sp))
    s = _place_forest_to_after(s)
    assert s.players[cp].resources.wood == 1        # post-pickup, under 2
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_without_a_playable_hand_occupation():
    # ≥ 2 wood but no playable occupation in hand → no dead-end fire.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _empty_hand_occupations(s, cp)
    s = with_resources(s, cp, wood=10)
    s = _place_forest_to_after(s)
    assert s.players[cp].resources.wood >= 2
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_without_card():
    # Without the card, Forest is NOT hosted (atomic fast path): placing resolves
    # immediately, no host frame, no trigger.
    s, cp = _card_state()
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=10)
    s = step(s, PlaceWorker(space="forest"))
    assert not s.pending_stack                       # resolved atomically


# ---------------------------------------------------------------------------
# The effect via the real engine flow
# ---------------------------------------------------------------------------

def test_fire_returns_two_wood_and_plays_a_free_occupation():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=5, food=0, clay=0)
    s = _place_forest_to_after(s)
    wood_after_pickup = s.players[cp].resources.wood
    forest_acc_before = get_space(s.board, "forest").accumulated.wood

    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)
    assert top.cost == Resources()                   # FREE occupation play
    assert top.phase == "before"
    # 2 wood debited from supply and placed back onto the Forest space.
    assert s.players[cp].resources.wood == wood_after_pickup - 2
    assert get_space(s.board, "forest").accumulated.wood == forest_acc_before + 2

    # The play-occupation enumerator offers a commit for the hand occupation.
    la = legal_actions(s)
    commits = [a for a in la if isinstance(a, CommitPlayOccupation)]
    assert CommitPlayOccupation(card_id=_OCC) in commits
    wood_before_play = s.players[cp].resources.wood
    food_before_play = s.players[cp].resources.food

    s = step(s, CommitPlayOccupation(card_id=_OCC))
    p = s.players[cp]
    # No food charged (free play), occupation moved hand->tableau, its on-play ran.
    assert p.resources.food == food_before_play      # 0, nothing debited
    assert _OCC in p.occupations
    assert _OCC not in p.hand_occupations
    assert p.resources.clay == 3                      # consultant's +3 clay on-play
    assert p.resources.wood == wood_before_play       # play itself spent no wood
    # Frame flips to after-phase, offering Stop.
    assert s.pending_stack[-1].phase == "after"
    assert Stop() in legal_actions(s)


def test_fires_once_per_use():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=5)
    s = _place_forest_to_after(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitPlayOccupation(card_id=_OCC))   # play the occupation
    s = step(s, Stop())                               # pop PendingPlayOccupation
    # Back at the Forest host's after-phase; already fired → not re-offered.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Optionality — declining = not firing
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_stop():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=8)
    s = _place_forest_to_after(s)
    wood_after_pickup = s.players[cp].resources.wood
    la = legal_actions(s)
    # Both firing AND declining (the host's Stop) are available — optionality lives
    # at the FireTrigger, not in the play host.
    assert FireTrigger(card_id=CARD_ID) in la
    assert Stop() in la
    s = step(s, Stop())                               # decline → host exits, turn ends
    assert not s.pending_stack                         # Forest use complete
    assert s.players[cp].resources.wood == wood_after_pickup  # no 2 wood returned
    assert _OCC in s.players[cp].hand_occupations      # occupation not played
    assert _OCC not in s.players[cp].occupations


# ---------------------------------------------------------------------------
# Wrong space does not fire
# ---------------------------------------------------------------------------

def test_clay_pit_does_not_fire():
    # Clay Pit is an accumulation space but CLAY not wood — Forestry Studies is not
    # hooked on it, so it stays atomic (no host) and nothing fires.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_hand_occupation(s, cp, _OCC)
    s = with_resources(s, cp, wood=10)
    sp = fast_replace(get_space(s.board, "clay_pit"), revealed=True, workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "clay_pit", sp))
    s = step(s, PlaceWorker(space="clay_pit"))
    assert not s.pending_stack
