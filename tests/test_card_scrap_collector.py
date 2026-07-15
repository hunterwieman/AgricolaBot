"""Tests for Scrap Collector (occupation, E120; Ephipparius): "Alternate placing
1 wood and 1 clay on each of the next 6 round spaces, starting with wood. At the
start of these rounds, you get the respective resource."

Played in round R: wood on R+1, R+3, R+5; clay on R+2, R+4, R+6; rounds past 14
silently dropped (the alternation is anchored to the offsets, not to which
rounds survive the clip). Mirrors tests/test_card_lumberjack.py (the
deferred-goods scheduler shape + the play-via-Lessons engine flow).
"""
import agricola.cards.scrap_collector  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env

_POOL = CardPool(
    occupations=("scrap_collector",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _wood_schedule(state, idx):
    return [r.wood for r in state.players[idx].future_resources]


def _clay_schedule(state, idx):
    return [r.clay for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "scrap_collector" in OCCUPATIONS


# ---------------------------------------------------------------------------
# on_play — wood/clay alternation over the next 6 round spaces
# ---------------------------------------------------------------------------

def test_played_round_1_schedules_rounds_2_to_7_alternating():
    s = setup(0)  # round 1
    out = OCCUPATIONS["scrap_collector"].on_play(s, 0)
    w, c = _wood_schedule(out, 0), _clay_schedule(out, 0)
    # Slot r-1 holds round r. Rounds 2..7: wood/clay/wood/clay/wood/clay.
    assert w[1] == 1 and c[1] == 0   # round 2: wood
    assert w[2] == 0 and c[2] == 1   # round 3: clay
    assert w[3] == 1 and c[3] == 0   # round 4: wood
    assert w[4] == 0 and c[4] == 1   # round 5: clay
    assert w[5] == 1 and c[5] == 0   # round 6: wood
    assert w[6] == 0 and c[6] == 1   # round 7: clay
    # Nothing anywhere else — exactly 3 wood + 3 clay total.
    assert sum(w) == 3 and sum(c) == 3
    assert w[0] == 0 and c[0] == 0   # the current round (1) untouched
    assert w[7] == 0 and c[7] == 0   # round 8 not scheduled


def test_played_round_10_clips_at_round_14():
    # Round 10: offsets give 11 wood, 12 clay, 13 wood, 14 clay; 15/16 dropped.
    # The alternation stays anchored to the offsets despite the clip.
    s = fast_replace(setup(0), round_number=10)
    out = OCCUPATIONS["scrap_collector"].on_play(s, 0)
    w, c = _wood_schedule(out, 0), _clay_schedule(out, 0)
    assert w[10] == 1 and c[10] == 0   # round 11: wood
    assert w[11] == 0 and c[11] == 1   # round 12: clay
    assert w[12] == 1 and c[12] == 0   # round 13: wood
    assert w[13] == 0 and c[13] == 1   # round 14: clay
    assert sum(w) == 2 and sum(c) == 2  # rounds 15/16 dropped


def test_played_round_14_schedules_nothing():
    s = fast_replace(setup(0), round_number=14)
    out = OCCUPATIONS["scrap_collector"].on_play(s, 0)
    assert sum(_wood_schedule(out, 0)) == 0
    assert sum(_clay_schedule(out, 0)) == 0


def test_only_owner_is_affected():
    s = setup(0)
    out = OCCUPATIONS["scrap_collector"].on_play(s, 0)
    assert sum(_wood_schedule(out, 1)) == 0
    assert sum(_clay_schedule(out, 1)) == 0


def test_hand_only_is_inert():
    # Holding the card in hand schedules nothing — only on_play does.
    cs, _env = setup_env(5, card_pool=_POOL)
    for i in range(2):
        assert sum(_wood_schedule(cs, i)) == 0
        assert sum(_clay_schedule(cs, i)) == 0


# ---------------------------------------------------------------------------
# Real engine flow — play via Lessons, then collect at round starts
# ---------------------------------------------------------------------------

def test_played_via_lessons_schedules_the_alternation():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_occupations=frozenset({"scrap_collector"}))
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="scrap_collector"))

    assert "scrap_collector" in cs.players[cp].occupations
    w, c = _wood_schedule(cs, cp), _clay_schedule(cs, cp)
    for off in (1, 3, 5):   # wood offsets
        assert w[R + off - 1] == 1 and c[R + off - 1] == 0
    for off in (2, 4, 6):   # clay offsets
        assert c[R + off - 1] == 1 and w[R + off - 1] == 0
    assert sum(w) == 3 and sum(c) == 3


def test_scheduled_resources_collected_at_round_starts():
    # Play in round 2, then drive the round-2 -> 3 and 3 -> 4 boundaries:
    # round 3 pays the wood, round 4 pays the clay.
    s = _own(fast_replace(setup(0), round_number=2, phase=Phase.PREPARATION),
             0, "scrap_collector")
    s = OCCUPATIONS["scrap_collector"].on_play(s, 0)  # wood r3/5/7, clay r4/6/8
    wood_before = s.players[0].resources.wood
    clay_before = s.players[0].resources.clay

    out = _complete_preparation(s)  # enter round 3
    assert out.round_number == 3
    assert out.players[0].resources.wood == wood_before + 1
    assert out.players[0].resources.clay == clay_before

    out = _complete_preparation(fast_replace(out, phase=Phase.PREPARATION))
    assert out.round_number == 4  # enter round 4
    assert out.players[0].resources.wood == wood_before + 1
    assert out.players[0].resources.clay == clay_before + 1
