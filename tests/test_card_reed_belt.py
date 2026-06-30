"""Tests for Reed Belt (minor improvement, B78; Bubulcus Expansion).

Card text: "Place 1 reed on each of the remaining space for rounds 5, 8, 10, and 12.
At the start of these rounds, you get the reed."
Cost: 2 Food. No prerequisite. VPs: none. Not passing.

Category 8 (deferred goods), the Sack Cart shape: on play, +1 reed is scheduled onto
each of the ABSOLUTE remaining rounds {5, 8, 10, 12} (strictly after the current
round), riding on `future_resources` and collected at each round's start by
`engine._complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.reed_belt  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState, get_space, with_space
from tests.factories import with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("reed_belt",) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _reed(state: GameState, idx: int):
    return [r.reed for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_reed_belt_registered():
    assert "reed_belt" in MINORS
    spec = MINORS["reed_belt"]
    assert spec.cost == Cost(resources=Resources(food=2))
    assert spec.vps == 0
    assert spec.passing_left is False
    # No prerequisite: any state satisfies it.
    assert prereq_met(spec, setup(0), 0)
    assert prereq_met(spec, setup(0), 1)


# ---------------------------------------------------------------------------
# on_play scheduling — the deferred goods
# ---------------------------------------------------------------------------

def test_reed_belt_all_remaining_at_round_1():
    s = setup(0)   # R=1 → all of {5, 8, 10, 12} remain
    out = MINORS["reed_belt"].on_play(s, 0)
    reed = _reed(out, 0)
    for rnd in (5, 8, 10, 12):
        assert reed[rnd - 1] == 1
    assert sum(reed) == 4
    # Only the owner is scheduled; the opponent is untouched.
    assert sum(_reed(out, 1)) == 0


def test_reed_belt_drops_already_entered_rounds():
    # Round 9 is current → rounds 5, 8 already gone; only {10, 12} remain.
    s = fast_replace(setup(0), round_number=9)
    out = MINORS["reed_belt"].on_play(s, 0)
    reed = _reed(out, 0)
    assert reed[4] == 0 and reed[7] == 0   # rounds 5, 8 dropped
    assert reed[9] == 1 and reed[11] == 1  # rounds 10, 12
    assert sum(reed) == 2


def test_reed_belt_exactly_current_round_dropped():
    # The filter is STRICTLY > R: scheduling while sitting on round 10 drops round 10
    # (its space has already been collected) and keeps only round 12.
    s = fast_replace(setup(0), round_number=10)
    out = MINORS["reed_belt"].on_play(s, 0)
    reed = _reed(out, 0)
    assert reed[9] == 0    # round 10 (current) dropped
    assert reed[11] == 1   # round 12 kept
    assert sum(reed) == 1


def test_reed_belt_schedule_is_additive():
    # on_play adds onto whatever is already promised (the helper is additive), so the
    # existing future_resources slots are preserved, not overwritten.
    s = setup(0)
    p = s.players[0]
    fr = list(p.future_resources)
    fr[4] = fr[4] + Resources(reed=2)   # round 5 already has 2 reed promised
    s = fast_replace(s, players=(fast_replace(p, future_resources=tuple(fr)),
                                 s.players[1]))
    out = MINORS["reed_belt"].on_play(s, 0)
    reed = _reed(out, 0)
    assert reed[4] == 3   # 2 pre-existing + 1 from Reed Belt


# ---------------------------------------------------------------------------
# End-to-end collection at round start
# ---------------------------------------------------------------------------

def test_reed_belt_reed_collected_at_round_start():
    # Schedule the reed, then enter a scheduled round via _complete_preparation and
    # confirm the promised reed lands in the player's actual supply.
    s = MINORS["reed_belt"].on_play(setup(0), 0)
    reed_before = s.players[0].resources.reed
    # Sit in PREPARATION on round 4; completing it enters round 5 (a scheduled round).
    s = fast_replace(s, round_number=4, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 5
    assert out.players[0].resources.reed == reed_before + 1
    # The consumed slot is cleared so it is not collected again.
    assert out.players[0].future_resources[4].reed == 0


def test_reed_belt_unscheduled_round_grants_nothing():
    # Entering a NON-scheduled round (round 6) collects no Reed Belt reed.
    s = MINORS["reed_belt"].on_play(setup(0), 0)
    reed_before = s.players[0].resources.reed
    s = fast_replace(s, round_number=5, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 6
    assert out.players[0].resources.reed == reed_before


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_reed_belt_played_via_engine_schedules_reed():
    # Drive the actual play-minor flow through the Major Improvement space in CARDS
    # mode (PlaceWorker -> improvement -> play_minor -> CommitPlayMinor), confirming
    # the card enters the tableau, the 2-food cost is paid, and the reed is scheduled.
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, food=2)   # afford the 2-food cost
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"reed_belt"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    food_before = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "reed_belt"))

    # The card is now in the tableau and its reed is scheduled.
    assert "reed_belt" in cs.players[cp].minor_improvements
    reed = _reed(cs, cp)
    for rnd in (5, 8, 10, 12):
        assert reed[rnd - 1] == 1
    assert sum(reed) == 4
    # Cost was paid: the 2 food is gone.
    assert cs.players[cp].resources.food == food_before - 2
