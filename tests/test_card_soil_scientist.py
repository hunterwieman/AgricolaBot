"""Tests for Soil Scientist (occupation, C114; Corbarius Expansion).

Card text: "Each time after you use a clay/stone accumulation space, you can place
1 stone/2 clay from your supply on the space to get 2 grain/1 vegetable,
respectively."

Resolved positionally by which space was used:
  - a CLAY space (Clay Pit)            → pay 1 STONE → get 2 grain
  - a STONE space (Western/Eastern Quarry) → pay 2 CLAY → get 1 vegetable

Shape: an OPTIONAL `after_action_space` FireTrigger on the three atomic-hosted
mineral accumulation spaces. The atomic host runs its own pickup on Proceed FIRST
(flipping to the after-phase), where this trigger is surfaced. Firing performs the
deterministic goods swap (no pushed frame); declining is not firing (Stop exits).
"""
import agricola.cards.soil_scientist  # noqa: F401  (registers the card)

import pytest

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources

CARD_ID = "soil_scientist"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(s, current_player=0), 0


def _own(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _reveal_quarry(state, space_id, stone=2):
    """Quarries are Stage 2/4 spaces (not up at round 1) — reveal + stock one."""
    sp = get_space(state.board, space_id)
    return fast_replace(state, board=with_space(
        state.board, space_id,
        fast_replace(sp, revealed=True, accumulated=Resources(stone=stone))))


def _place_to_after(state, space_id):
    """Place P0 at the (hosted) space and Proceed past the pickup so the host
    frame is in its after-phase (where the trigger is surfaced)."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())                 # primary pickup, flip to after
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_soil_scientist_registered():
    assert CARD_ID in OCCUPATIONS
    spec = OCCUPATIONS[CARD_ID]
    # Pure occupation: no cost / prereq / vps / passing surfaced on the spec.
    assert getattr(spec, "vps", 0) == 0
    # Optional after_action_space trigger on the three mineral spaces.
    aas = {e.card_id for e in TRIGGERS.get("after_action_space", [])}
    assert CARD_ID in aas
    for sid in ("clay_pit", "western_quarry", "eastern_quarry"):
        assert CARD_ID in OWN_ACTION_HOOK_CARDS[sid]


def test_no_on_play_effect():
    # Owning the occupation alone changes no resources (on-play is a no-op).
    s, cp = _card_state()
    s = with_resources(s, cp, stone=3, clay=3)
    s2 = _own(s, cp)
    assert s2.players[cp].resources == s.players[cp].resources


# ---------------------------------------------------------------------------
# Clay Pit branch: pay 1 stone -> get 2 grain
# ---------------------------------------------------------------------------

def test_clay_pit_offered_with_stone():
    s, cp = _card_state()
    s = _own(s, cp)
    s = with_resources(s, cp, stone=1)
    s = _place_to_after(s, "clay_pit")
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_clay_pit_not_offered_without_stone():
    s, cp = _card_state()
    s = _own(s, cp)
    s = with_resources(s, cp, stone=0)
    s = _place_to_after(s, "clay_pit")
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_clay_pit_fire_swaps_stone_for_grain():
    s, cp = _card_state()
    s = _own(s, cp)
    s = with_resources(s, cp, stone=2, grain=1)
    accum_clay = get_space(s.board, "clay_pit").accumulated.clay
    s = _place_to_after(s, "clay_pit")
    # Clay Pit pickup added its accumulated clay; stone/grain untouched yet.
    assert s.players[cp].resources.stone == 2
    assert s.players[cp].resources.grain == 1
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[cp].resources.stone == 1          # paid 1 stone
    assert s.players[cp].resources.grain == 3          # gained 2 grain
    # The clay pickup is unaffected by the swap.
    assert s.players[cp].resources.clay == accum_clay


# ---------------------------------------------------------------------------
# Quarry branch: pay 2 clay -> get 1 vegetable (both quarries share it)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space", ["western_quarry", "eastern_quarry"])
def test_quarry_offered_with_two_clay(space):
    s, cp = _card_state()
    s = _own(s, cp)
    s = _reveal_quarry(s, space, stone=2)
    s = with_resources(s, cp, clay=2)
    s = _place_to_after(s, space)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


@pytest.mark.parametrize("space", ["western_quarry", "eastern_quarry"])
def test_quarry_not_offered_with_one_clay(space):
    # Needs 2 clay; exactly 1 is short.
    s, cp = _card_state()
    s = _own(s, cp)
    s = _reveal_quarry(s, space, stone=2)
    s = with_resources(s, cp, clay=1)
    s = _place_to_after(s, space)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


@pytest.mark.parametrize("space", ["western_quarry", "eastern_quarry"])
def test_quarry_fire_swaps_two_clay_for_veg(space):
    s, cp = _card_state()
    s = _own(s, cp)
    s = _reveal_quarry(s, space, stone=2)
    s = with_resources(s, cp, clay=3, veg=0)
    s = _place_to_after(s, space)
    assert s.players[cp].resources.stone == 2          # 2 accumulated stone picked up
    assert s.players[cp].resources.clay == 3
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[cp].resources.clay == 1           # paid 2 clay
    assert s.players[cp].resources.veg == 1            # gained 1 veg
    assert s.players[cp].resources.stone == 2          # stone pickup untouched


# ---------------------------------------------------------------------------
# Optionality — declining = not firing
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_stop():
    s, cp = _card_state()
    s = _own(s, cp)
    s = with_resources(s, cp, stone=1, grain=0)
    s = _place_to_after(s, "clay_pit")
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Stop() in la
    s = step(s, Stop())                                # decline: just exit
    assert not s.pending_stack
    assert s.players[cp].resources.stone == 1          # no swap happened
    assert s.players[cp].resources.grain == 0


# ---------------------------------------------------------------------------
# Once per use — triggers_resolved gating
# ---------------------------------------------------------------------------

def test_fires_once_per_use():
    s, cp = _card_state()
    s = _own(s, cp)
    s = with_resources(s, cp, stone=2, grain=0)
    s = _place_to_after(s, "clay_pit")
    s = step(s, FireTrigger(card_id=CARD_ID))          # fire once
    # Still in the after-phase host frame, already resolved -> not re-offered,
    # even though the player still holds a second stone.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.players[cp].resources.stone == 1
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Scoping — without the card the space is unhosted; not offered on other spaces
# ---------------------------------------------------------------------------

def test_not_hosted_without_card():
    # Without the occupation, Clay Pit is atomic fast-path: resolves immediately,
    # no host frame, no trigger.
    s, cp = _card_state()
    s = with_resources(s, cp, stone=5)
    s = step(s, PlaceWorker(space="clay_pit"))
    assert not s.pending_stack


def test_not_offered_on_unrelated_space():
    # Forest is a wood space, not a clay/stone one — the trigger never fires there
    # even when hosted by some other card. Here it is simply unhosted (no host
    # frame), confirming Soil Scientist does not reach it.
    s, cp = _card_state()
    s = _own(s, cp)
    s = with_resources(s, cp, stone=5, clay=5)
    s = step(s, PlaceWorker(space="forest"))
    assert not s.pending_stack                         # forest not hosted by this card
