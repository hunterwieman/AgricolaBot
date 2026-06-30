"""Tests for Cattle Whisperer (occupation, C166; Consul Dirigens Expansion).

Card text: "Add 5 and 8 to the current round and place 1 cattle on each corresponding
round space. At the start of these rounds, you get the cattle."

A Category-8 deferred-goods occupation, the ANIMAL variant: 1 cattle scheduled onto each
of the round spaces R+5 and R+8 (R = the round the card is played), collected +
auto-accommodated at the start of those rounds via `engine._collect_future_rewards`.
Covered:
- registration (in OCCUPATIONS, plain occupation: no cost/prereq/vps/passing);
- the on-play schedule (R+5 and R+8 round-relative offsets, opponent untouched);
- the late-play clamp past round 14 (one or both targets dropped);
- a REAL play-via-Lessons flow placing the schedule;
- an end-to-end round-start collection (the scheduled cattle land in actual animals,
  auto-accommodated; slot cleared) via the collector and the full preparation step.
"""
import agricola.cards.cattle_whisperer  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import Phase
from agricola.engine import _collect_future_rewards, _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.setup import CardPool, setup, setup_env

_POOL = CardPool(
    occupations=("cattle_whisperer",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _cattle(state, idx):
    return [fr.animals.cattle for fr in state.players[idx].future_rewards]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_cattle_whisperer_registered_plain_occupation():
    # OccupationSpec carries only card_id + on_play (no structured cost/prereq/vps —
    # occupations are plain, played via Lessons; the on-play schedule is the effect).
    assert "cattle_whisperer" in OCCUPATIONS
    spec = OCCUPATIONS["cattle_whisperer"]
    assert spec.card_id == "cattle_whisperer"
    assert callable(spec.on_play)


# ---------------------------------------------------------------------------
# On-play schedule — R+5 and R+8 round-relative offsets
# ---------------------------------------------------------------------------

def test_on_play_schedules_cattle_rounds_R5_and_R8():
    s = setup(0)               # round 1 → cattle on rounds 6 and 9 (slots 5 and 8)
    R = s.round_number
    out = OCCUPATIONS["cattle_whisperer"].on_play(s, 0)
    cattle = _cattle(out, 0)
    assert cattle[R + 4] == 1   # round R+5 → slot R+4
    assert cattle[R + 7] == 1   # round R+8 → slot R+7
    # Exactly two cattle scheduled, nothing leaks onto any other slot.
    assert sum(cattle) == 2
    # The current round (slot R-1) is never scheduled.
    assert cattle[R - 1] == 0


def test_on_play_other_player_untouched():
    s = setup(0)
    out = OCCUPATIONS["cattle_whisperer"].on_play(s, 0)
    assert all(not fr for fr in out.players[1].future_rewards)


# ---------------------------------------------------------------------------
# Late-play clamp past round 14
# ---------------------------------------------------------------------------

def test_on_play_clamps_R8_target_past_round_14():
    # R=8 → R+5=13 (kept), R+8=16 (> round 14, dropped).
    s = fast_replace(setup(0), round_number=8)
    out = OCCUPATIONS["cattle_whisperer"].on_play(s, 0)
    cattle = _cattle(out, 0)
    assert cattle[12] == 1       # round 13 kept (slot 12)
    assert sum(cattle) == 1      # round 16 dropped


def test_on_play_clamps_both_targets_past_round_14():
    # R=14 → both targets (19, 22) are past the game → both dropped.
    s = fast_replace(setup(0), round_number=14)
    out = OCCUPATIONS["cattle_whisperer"].on_play(s, 0)
    assert all(not fr for fr in out.players[0].future_rewards)


# ---------------------------------------------------------------------------
# Real play-via-Lessons flow
# ---------------------------------------------------------------------------

def test_played_via_lessons_schedules_rounds_R5_and_R8():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"cattle_whisperer"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="cattle_whisperer"))

    assert "cattle_whisperer" in cs.players[cp].occupations
    cattle = _cattle(cs, cp)
    assert cattle[R + 4] == 1    # cattle on round R+5 (slot R+4)
    assert cattle[R + 7] == 1    # cattle on round R+8 (slot R+7)
    assert sum(cattle) == 2


# ---------------------------------------------------------------------------
# End-to-end round-start collection (collected + auto-accommodated)
# ---------------------------------------------------------------------------

def test_cattle_collected_and_accommodated_at_round_start():
    s = setup(0)                 # round 1 → cattle on rounds 6 and 9
    R = s.round_number
    s = OCCUPATIONS["cattle_whisperer"].on_play(s, 0)
    cattle0 = s.players[0].animals.cattle
    # Collect the slot for round R+5 (slot index R+4): 1 cattle fits the house pet on a
    # default farm, so it is kept and the slot is cleared.
    out = _collect_future_rewards(s, R + 4)
    assert out.players[0].animals.cattle == cattle0 + 1
    assert out.players[0].future_rewards[R + 4].animals == Animals()
    # The other scheduled slot (R+8) is untouched until its round is entered.
    assert out.players[0].future_rewards[R + 7].animals == Animals(cattle=1)


def test_cattle_collected_via_full_preparation():
    # Drive the real round-boundary path (_complete_preparation), not just the
    # collector. Play at R=5 so R+5=10 is the next round entered; confirm the cattle
    # lands when round 10 begins.
    s = fast_replace(setup(0), round_number=5)
    s = OCCUPATIONS["cattle_whisperer"].on_play(s, 0)   # schedules rounds 10 and 13
    cattle0 = s.players[0].animals.cattle
    # Entering round 10: _complete_preparation reads round_number+1.
    prep = fast_replace(s, round_number=9, phase=Phase.PREPARATION)
    out = _complete_preparation(prep)
    assert out.round_number == 10
    assert out.players[0].animals.cattle == cattle0 + 1
    # Round-13 cattle remains scheduled (not yet entered).
    assert out.players[0].future_rewards[12].animals == Animals(cattle=1)
