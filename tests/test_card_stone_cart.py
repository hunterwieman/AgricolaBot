"""Tests for Stone Cart (minor improvement, C79; Consul Dirigens Expansion).

Card text: "Place 1 stone on each remaining even-numbered round space. At the start
of these rounds, you get the stone."
Cost: 2 Wood. Prerequisite: 2 Occupations. VPs: none. Not passing.

Category 8 (deferred goods), the Sack Cart shape: on play, +1 stone is scheduled onto
each of the remaining EVEN-numbered rounds {2, 4, 6, 8, 10, 12, 14} (strictly after
the current round), riding on `future_resources` and collected at each round's start
by `engine._complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.stone_cart  # noqa: F401  (registers the card)

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

CARD_ID = "stone_cart"
_EVEN_ROUNDS = (2, 4, 6, 8, 10, 12, 14)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _stone(state: GameState, idx: int):
    return [r.stone for r in state.players[idx].future_resources]


def _with_occupations(state: GameState, idx: int, occ):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | set(occ))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_stone_cart_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.min_occupations == 2     # "2 Occupations" prerequisite
    assert spec.vps == 0
    assert spec.passing_left is False


def test_stone_cart_prereq_requires_two_occupations():
    spec = MINORS[CARD_ID]
    s = setup(0)
    # 0 occupations → fails.
    assert not prereq_met(spec, s, 0)
    # exactly 1 → still fails (< 2).
    s1 = _with_occupations(s, 0, ("oa",))
    assert not prereq_met(spec, s1, 0)
    # exactly 2 → met.
    s2 = _with_occupations(s, 0, ("oa", "ob"))
    assert prereq_met(spec, s2, 0)
    # 3 → still met (it is a >= bound).
    s3 = _with_occupations(s, 0, ("oa", "ob", "oc"))
    assert prereq_met(spec, s3, 0)


# ---------------------------------------------------------------------------
# on_play scheduling — the deferred goods
# ---------------------------------------------------------------------------

def test_stone_cart_all_remaining_at_round_1():
    s = setup(0)   # R=1 → all even rounds remain
    out = MINORS[CARD_ID].on_play(s, 0)
    stone = _stone(out, 0)
    for rnd in _EVEN_ROUNDS:
        assert stone[rnd - 1] == 1
    assert sum(stone) == len(_EVEN_ROUNDS)   # 7
    # Odd round spaces are untouched.
    for rnd in (1, 3, 5, 7, 9, 11, 13):
        assert stone[rnd - 1] == 0
    # Only the owner is scheduled; the opponent is untouched.
    assert sum(_stone(out, 1)) == 0


def test_stone_cart_drops_already_entered_rounds():
    # Round 7 is current → rounds 2, 4, 6 already gone; {8, 10, 12, 14} remain.
    s = fast_replace(setup(0), round_number=7)
    out = MINORS[CARD_ID].on_play(s, 0)
    stone = _stone(out, 0)
    assert stone[1] == 0 and stone[3] == 0 and stone[5] == 0   # rounds 2, 4, 6 dropped
    for rnd in (8, 10, 12, 14):
        assert stone[rnd - 1] == 1
    assert sum(stone) == 4


def test_stone_cart_exactly_current_round_dropped():
    # The filter is STRICTLY > R: scheduling while sitting on round 8 drops round 8
    # (its space has already been collected) and keeps {10, 12, 14}.
    s = fast_replace(setup(0), round_number=8)
    out = MINORS[CARD_ID].on_play(s, 0)
    stone = _stone(out, 0)
    assert stone[7] == 0    # round 8 (current) dropped
    for rnd in (10, 12, 14):
        assert stone[rnd - 1] == 1
    assert sum(stone) == 3


def test_stone_cart_late_play_only_round_14():
    # Round 13 current → only round 14 remains.
    s = fast_replace(setup(0), round_number=13)
    out = MINORS[CARD_ID].on_play(s, 0)
    stone = _stone(out, 0)
    assert stone[13] == 1
    assert sum(stone) == 1


def test_stone_cart_schedule_is_additive():
    # on_play adds onto whatever is already promised (the helper is additive), so the
    # existing future_resources slots are preserved, not overwritten.
    s = setup(0)
    p = s.players[0]
    fr = list(p.future_resources)
    fr[3] = fr[3] + Resources(stone=2)   # round 4 already has 2 stone promised
    s = fast_replace(s, players=(fast_replace(p, future_resources=tuple(fr)),
                                 s.players[1]))
    out = MINORS[CARD_ID].on_play(s, 0)
    stone = _stone(out, 0)
    assert stone[3] == 3   # 2 pre-existing + 1 from Stone Cart


# ---------------------------------------------------------------------------
# End-to-end collection at round start
# ---------------------------------------------------------------------------

def test_stone_cart_collected_at_scheduled_round_start():
    # Schedule the stone, then enter a scheduled (even) round via _complete_preparation
    # and confirm the promised stone lands in the player's actual supply.
    s = MINORS[CARD_ID].on_play(setup(0), 0)
    stone_before = s.players[0].resources.stone
    # Sit in PREPARATION on round 5; completing it enters round 6 (a scheduled round).
    s = fast_replace(s, round_number=5, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 6
    assert out.players[0].resources.stone == stone_before + 1
    # The consumed slot is cleared so it is not collected again.
    assert out.players[0].future_resources[5].stone == 0


def test_stone_cart_unscheduled_round_grants_nothing():
    # Entering a NON-scheduled (odd) round (round 7) collects no Stone Cart stone.
    s = MINORS[CARD_ID].on_play(setup(0), 0)
    stone_before = s.players[0].resources.stone
    s = fast_replace(s, round_number=6, phase=Phase.PREPARATION)
    out = _complete_preparation(s)
    assert out.round_number == 7
    assert out.players[0].resources.stone == stone_before


# ---------------------------------------------------------------------------
# Real play flow — play the minor through a live engine decision point
# ---------------------------------------------------------------------------

def test_stone_cart_played_via_engine_schedules_stone():
    # Drive the actual play-minor flow through the Major Improvement space in CARDS
    # mode (PlaceWorker -> improvement -> play_minor -> CommitPlayMinor), confirming
    # the card enters the tableau, the 2-wood cost is paid, and the stone is scheduled.
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, wood=2)   # afford the 2-wood cost
    # Give the owner 2 occupations to satisfy the play-time prerequisite.
    cs = _with_occupations(cs, cp, ("oa", "ob"))
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    wood_before = cs.players[cp].resources.wood

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    # The card is now in the tableau and its stone is scheduled.
    assert CARD_ID in cs.players[cp].minor_improvements
    stone = _stone(cs, cp)
    for rnd in _EVEN_ROUNDS:
        assert stone[rnd - 1] == 1
    assert sum(stone) == len(_EVEN_ROUNDS)
    # Cost was paid: the 2 wood is gone.
    assert cs.players[cp].resources.wood == wood_before - 2
