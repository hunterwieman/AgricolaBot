"""Tests for Spice Trader (occupation, E104; Ephipparius): "If you play this
card in round 4 or before, place 3 vegetables on the space for round 11. At the
start of that round, you get the vegetables."

Choice-free on_play: played in round <= 4, schedule 3 veg on the fixed round-11
slot of `future_resources`; played round 5+, no effect (the card still plays).
Mirrors tests/test_card_lumberjack.py (the deferred-goods occupation shape:
direct on_play assertions + the play-via-Lessons engine flow + the
round-entry collection via `_complete_preparation`).
"""
import agricola.cards.spice_trader  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env

_POOL = CardPool(
    occupations=("spice_trader",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _veg_schedule(state, idx):
    return [r.veg for r in state.players[idx].future_resources]


def _at_round(state, rnd):
    return fast_replace(state, round_number=rnd)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "spice_trader" in OCCUPATIONS


# ---------------------------------------------------------------------------
# on_play — round 4 or before: 3 veg on the round-11 space
# ---------------------------------------------------------------------------

def test_played_round_3_schedules_three_veg_on_round_11():
    s = _at_round(setup(0), 3)
    out = OCCUPATIONS["spice_trader"].on_play(s, 0)
    v = _veg_schedule(out, 0)
    assert v[10] == 3          # slot 10 holds round 11
    assert sum(v) == 3         # no other slot touched
    # Nothing lands in the supply at play time.
    assert out.players[0].resources.veg == s.players[0].resources.veg


def test_played_round_4_exactly_schedules():
    # Boundary: "round 4 or before" includes round 4 itself.
    s = _at_round(setup(0), 4)
    out = OCCUPATIONS["spice_trader"].on_play(s, 0)
    assert _veg_schedule(out, 0)[10] == 3


def test_played_round_5_no_effect():
    s = _at_round(setup(0), 5)
    out = OCCUPATIONS["spice_trader"].on_play(s, 0)
    assert sum(_veg_schedule(out, 0)) == 0


def test_played_round_1_at_setup_schedules():
    s = setup(0)   # round 1
    out = OCCUPATIONS["spice_trader"].on_play(s, 0)
    assert _veg_schedule(out, 0)[10] == 3


def test_opponent_untouched():
    s = _at_round(setup(0), 2)
    out = OCCUPATIONS["spice_trader"].on_play(s, 0)
    assert sum(_veg_schedule(out, 1)) == 0
    assert out.players[1] == s.players[1]


# ---------------------------------------------------------------------------
# Real engine flow — play via Lessons in round 1, then collect at round 11
# ---------------------------------------------------------------------------

def test_played_via_lessons_schedules():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"spice_trader"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    assert cs.round_number == 1   # round 1 <= 4 — the condition holds

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="spice_trader"))

    assert "spice_trader" in cs.players[cp].occupations
    v = _veg_schedule(cs, cp)
    assert v[10] == 3
    assert sum(v) == 3


def test_hand_only_is_inert():
    # Holding the card in hand (never played) schedules nothing.
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"spice_trader"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    assert sum(_veg_schedule(cs, cp)) == 0
    assert "spice_trader" not in cs.players[cp].occupations


def test_scheduled_veg_collected_at_start_of_round_11():
    # Drive _complete_preparation from round 10 into round 11 and confirm the
    # promised vegetables are paid into the supply ("at the start of that round").
    s = fast_replace(setup(0), round_number=10, phase=Phase.PREPARATION)
    p = s.players[0]
    p = fast_replace(p, occupations=p.occupations | {"spice_trader"})
    slots = list(p.future_resources)
    slots[10] = slots[10] + Resources(veg=3)   # slot 10 → round 11
    p = fast_replace(p, future_resources=tuple(slots))
    s = fast_replace(s, players=(p, s.players[1]))
    veg_before = s.players[0].resources.veg

    out = _complete_preparation(s)
    assert out.round_number == 11
    assert out.players[0].resources.veg == veg_before + 3
