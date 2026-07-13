"""Tests for Bee Statue (minor improvement, E40; Ephipparius Expansion).

Card text: "Pile (from bottom to top) 1 vegetable, 1 stone, 1 grain, 1 stone,
1 grain on this card. Each time you use the 'Day Laborer' action space, you get
the top good."
Cost: 2 Clay.

Consumed TOP-first: grain, stone, grain, stone, veg (five uses), then empty. A
`before_action_space` automatic effect on the atomic Day Laborer space, metered by
a CardStore counter. Tests drive a real Day Laborer placement, then exercise the
full dispense sequence via the auto, plus the own-only / wrong-space / exhausted
boundaries.
"""
import json
from pathlib import Path

import agricola.cards.bee_statue  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS, apply_auto_effects
from agricola.engine import step
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from tests.factories import with_current_player, with_pending_stack

CARD_ID = "bee_statue"

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Bee Statue")


def _own(state, idx):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _at_day_laborer_host(idx=0):
    """A state at a Day Laborer before-phase host, owner holds Bee Statue."""
    state = with_current_player(setup(0), idx)
    state = _own(state, idx)
    return with_pending_stack(
        state, (PendingActionSpace(player_idx=idx, initiated_by_id="space:day_laborer"),))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_json_row():
    assert _ROW["cost"] == "2 Clay"
    assert _ROW["text"] == (
        'Pile (from bottom to top) 1 vegetable, 1 stone, 1 grain, 1 stone, '
        '1 grain on this card. Each time you use the "Day Laborer" action space, '
        'you get the top good.')
    import agricola.cards.bee_statue as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered():
    assert MINORS[CARD_ID].cost == Cost(resources=Resources(clay=2))
    assert CARD_ID in {e.card_id for e in AUTO_EFFECTS.get("before_action_space", [])}
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("day_laborer", set())


# ---------------------------------------------------------------------------
# Real Day Laborer placement dispenses the first good (grain) + the 2 food
# ---------------------------------------------------------------------------

def test_real_placement_dispenses_grain_then_food():
    state = with_current_player(setup(0), 0)
    state = _own(state, 0)
    before_food = state.players[0].resources.food
    state = step(state, PlaceWorker(space="day_laborer"))
    # Bee Statue's before-auto fired at the host push: first good is grain.
    assert state.players[0].resources.grain == 1
    assert state.players[0].card_state.get(CARD_ID) == 1
    # Finish the Day Laborer action (its 2 food).
    state = step(state, Proceed())
    state = step(state, Stop())
    assert state.pending_stack == ()
    assert state.players[0].resources.food == before_food + 2


# ---------------------------------------------------------------------------
# Full dispense sequence: grain, stone, grain, stone, veg, then empty
# ---------------------------------------------------------------------------

def test_full_sequence_then_empty():
    state = _at_day_laborer_host(0)
    expected = [
        Resources(grain=1), Resources(stone=1), Resources(grain=1),
        Resources(stone=1), Resources(veg=1),
    ]
    running = Resources()
    for i, good in enumerate(expected):
        state = apply_auto_effects(state, "before_action_space", 0)
        running = running + good
        p = state.players[0]
        assert p.resources.grain == running.grain
        assert p.resources.stone == running.stone
        assert p.resources.veg == running.veg
        assert p.card_state.get(CARD_ID) == i + 1
    # 6th use: pile empty -> no-op, nothing more dispensed, counter stays at 5.
    after = apply_auto_effects(state, "before_action_space", 0)
    assert after.players[0].resources == state.players[0].resources
    assert after.players[0].card_state.get(CARD_ID) == 5


# ---------------------------------------------------------------------------
# Boundaries: wrong space, unowned, own-only
# ---------------------------------------------------------------------------

def test_not_fired_on_a_different_space():
    state = with_current_player(setup(0), 0)
    state = _own(state, 0)
    state = with_pending_stack(
        state, (PendingActionSpace(player_idx=0, initiated_by_id="space:forest"),))
    out = apply_auto_effects(state, "before_action_space", 0)
    assert out.players[0].resources.grain == 0


def test_unowned_noop():
    state = with_pending_stack(
        with_current_player(setup(0), 0),
        (PendingActionSpace(player_idx=0, initiated_by_id="space:day_laborer"),))
    out = apply_auto_effects(state, "before_action_space", 0)
    assert out is state          # not owned -> unchanged


def test_own_only_not_opponent():
    """"You use" -> only the owner's use dispenses; the opponent acting does not."""
    state = _at_day_laborer_host(0)          # player 0 owns Bee Statue
    out = apply_auto_effects(state, "before_action_space", 1)   # opponent acts
    assert out.players[0].resources.grain == 0
    assert out.players[0].card_state.get(CARD_ID) is None
