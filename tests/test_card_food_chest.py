"""Food Chest (minor improvement, B59).

Card text: "If you play this card on the 'Major Improvement' action space, you
immediately get 4 food. Otherwise, you get only 2 food." Cost 1 wood.

The discriminator is WHERE the card is played:
  - via the Major Improvement action space  -> +4 food,
  - via any other entry point (Meeting Place, etc.) -> +2 food.

These tests drive the REAL engine flows (place a worker on the space, choose
the play-minor branch, commit the play) and check the food gain, plus the
direct on_play discrimination via crafted stacks for the eligibility boundary.
"""
import agricola.cards.food_chest  # noqa: F401  -- registers the card

import pytest

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingMajorMinorImprovement,
    PendingMeetingPlace,
    PendingPlayMinor,
    PendingSubActionSpace,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("food_chest",) + tuple(f"m{i}" for i in range(20)),
)


def _state_with_card(seed=5, *, wood=2):
    """A cards-mode round-1 state where the active player holds Food Chest and
    has `wood` wood (default 2 — enough to build a major-ish AND pay the 1-wood
    minor cost). The opponent's hand is emptied so it can't interfere."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        hand_minors=frozenset({"food_chest"}),
        resources=cs.players[cp].resources + Resources(wood=wood),
    )
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_food_chest_registered():
    assert "food_chest" in MINORS
    spec = MINORS["food_chest"]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.vps == 0
    assert spec.passing_left is False


# ---------------------------------------------------------------------------
# Real-engine flow: Major Improvement space -> +4 food
# ---------------------------------------------------------------------------

def test_play_via_major_improvement_gives_4_food():
    cs, cp = _state_with_card()
    food0 = cs.players[cp].resources.food

    # Place a worker on the Major Improvement space.
    cs = step(cs, PlaceWorker(space="major_improvement"))
    assert isinstance(cs.pending_stack[-1], PendingSubActionSpace)
    assert cs.pending_stack[-1].initiated_by_id == "space:major_improvement"

    # The host's single sub-action: enter the composite.
    cs = step(cs, ChooseSubAction(name="improvement"))
    assert isinstance(cs.pending_stack[-1], PendingMajorMinorImprovement)

    # Choose the play-minor branch.
    cs = step(cs, ChooseSubAction(name="play_minor"))
    assert isinstance(cs.pending_stack[-1], PendingPlayMinor)
    # The major-improvement frame is still on the stack below us.
    assert any(getattr(f, "initiated_by_id", None) == "space:major_improvement"
               for f in cs.pending_stack)

    # Play Food Chest.
    cs = step(cs, sole_play_minor(cs, "food_chest"))

    # +4 food (major path), minus the 1-wood cost paid by the play-minor commit.
    assert cs.players[cp].resources.food == food0 + 4
    assert "food_chest" in cs.players[cp].minor_improvements
    assert "food_chest" not in cs.players[cp].hand_minors


# ---------------------------------------------------------------------------
# Real-engine flow: Meeting Place ("otherwise") -> +2 food
# ---------------------------------------------------------------------------

def test_play_via_meeting_place_gives_2_food():
    cs, cp = _state_with_card()
    food0 = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="meeting_place"))
    assert isinstance(cs.pending_stack[-1], PendingMeetingPlace)
    assert cs.pending_stack[-1].initiated_by_id == "space:meeting_place"
    # No major-improvement frame anywhere on the stack.
    assert not any(getattr(f, "initiated_by_id", None) == "space:major_improvement"
                   for f in cs.pending_stack)

    # Meeting Place offers an optional play-minor branch (minor is playable).
    cs = step(cs, ChooseSubAction(name="play_minor"))
    assert isinstance(cs.pending_stack[-1], PendingPlayMinor)

    cs = step(cs, sole_play_minor(cs, "food_chest"))

    # +2 food (the "otherwise" branch).
    assert cs.players[cp].resources.food == food0 + 2
    assert "food_chest" in cs.players[cp].minor_improvements


# ---------------------------------------------------------------------------
# on_play discrimination via crafted stacks (eligibility boundary, isolated)
# ---------------------------------------------------------------------------

def _craft_and_play(cs, cp, stack):
    """Push `stack` (ending in a PendingPlayMinor for `cp`) and play Food Chest."""
    cs = with_pending_stack(cs, stack)
    return step(cs, sole_play_minor(cs, "food_chest"))


def test_on_play_major_frame_anywhere_on_stack_gives_4():
    cs, cp = _state_with_card()
    food0 = cs.players[cp].resources.food
    stack = (
        PendingSubActionSpace(player_idx=cp, initiated_by_id="space:major_improvement"),
        PendingMajorMinorImprovement(player_idx=cp, initiated_by_id="major_minor_improvement"),
        PendingPlayMinor(player_idx=cp, initiated_by_id="major_minor_improvement"),
    )
    out = _craft_and_play(cs, cp, stack)
    assert out.players[cp].resources.food == food0 + 4


def test_on_play_without_major_frame_gives_2():
    cs, cp = _state_with_card()
    food0 = cs.players[cp].resources.food
    # House-Redevelopment improvement path: the composite shares the
    # "major_minor_improvement" PENDING_ID, but NO "space:major_improvement"
    # frame exists -> the "otherwise" 2-food branch.
    stack = (
        PendingMajorMinorImprovement(player_idx=cp, initiated_by_id="major_minor_improvement"),
        PendingPlayMinor(player_idx=cp, initiated_by_id="major_minor_improvement"),
    )
    out = _craft_and_play(cs, cp, stack)
    assert out.players[cp].resources.food == food0 + 2


def test_on_play_top_frame_alone_does_not_trigger_4():
    """Keying off the top frame's id ("major_minor_improvement") would mis-fire;
    the discriminator must be the deeper "space:major_improvement" frame. Here the
    play-minor frame alone yields the 2-food branch."""
    cs, cp = _state_with_card()
    food0 = cs.players[cp].resources.food
    stack = (
        PendingPlayMinor(player_idx=cp, initiated_by_id="major_minor_improvement"),
    )
    out = _craft_and_play(cs, cp, stack)
    assert out.players[cp].resources.food == food0 + 2
