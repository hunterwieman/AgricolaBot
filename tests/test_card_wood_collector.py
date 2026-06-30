"""Tests for Wood Collector (occupation, C118; Consul Dirigens Expansion).

Card text: "Place 1 wood on each of the next 5 round spaces. At the start of these
rounds, you get the wood."

A Category-8 deferred-goods occupation: 1 wood placed on each of the next 5 round
spaces (rounds R+1..R+5, 1-indexed), collected automatically at the start of each
round via `engine._complete_preparation`. Covered:
- registration (in OCCUPATIONS, plain occupation: no cost/prereq/vps/passing);
- the on-play schedule (same good on five consecutive rounds, current round skipped);
- the opponent is untouched (scoping);
- the late-play clamp past round 14 (only remaining round spaces get wood);
- a REAL play-via-Lessons flow placing the schedule;
- an end-to-end round-start collection (scheduled wood lands in actual resources).
"""
import agricola.cards.wood_collector  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env

_POOL = CardPool(
    occupations=("wood_collector",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wood(state, idx):
    return [r.wood for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_wood_collector_registered_plain_occupation():
    # OccupationSpec carries only card_id + on_play (no structured cost/prereq/vps
    # — occupations are plain, played via Lessons; the on-play schedule is the effect).
    assert "wood_collector" in OCCUPATIONS
    spec = OCCUPATIONS["wood_collector"]
    assert spec.card_id == "wood_collector"
    assert callable(spec.on_play)


# ---------------------------------------------------------------------------
# On-play schedule — same good on the next five round spaces
# ---------------------------------------------------------------------------

def test_on_play_schedules_one_wood_on_next_five_rounds():
    s = setup(0)   # R=1 → wood on rounds 2,3,4,5,6 (slots 1..5)
    out = OCCUPATIONS["wood_collector"].on_play(s, 0)
    w = _wood(out, 0)
    # 1 wood on each of rounds 2..6, nothing on the current round (1, slot 0).
    assert w[0] == 0
    assert w[1] == w[2] == w[3] == w[4] == w[5] == 1
    assert sum(w) == 5
    # Only wood is scheduled (no other building resource).
    assert all(g == Resources(wood=g.wood) for g in out.players[0].future_resources)


def test_on_play_other_player_untouched():
    s = setup(0)
    out = OCCUPATIONS["wood_collector"].on_play(s, 0)
    assert all(g == Resources() for g in out.players[1].future_resources)


def test_on_play_clamps_past_round_14():
    # R=12 → rounds 13,14 kept; 15,16,17 dropped (> round 14).
    s = fast_replace(setup(0), round_number=12)
    out = OCCUPATIONS["wood_collector"].on_play(s, 0)
    w = _wood(out, 0)
    assert w[12] == 1 and w[13] == 1   # rounds 13, 14
    assert sum(w) == 2                 # the other three dropped


def test_on_play_at_round_14_schedules_nothing():
    # Final round: every "next" round space is past the game and silently dropped.
    s = fast_replace(setup(0), round_number=14)
    out = OCCUPATIONS["wood_collector"].on_play(s, 0)
    assert sum(_wood(out, 0)) == 0


# ---------------------------------------------------------------------------
# Real play-via-Lessons flow
# ---------------------------------------------------------------------------

def test_played_via_lessons_schedules_next_five_rounds():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"wood_collector"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="wood_collector"))

    assert "wood_collector" in cs.players[cp].occupations
    w = _wood(cs, cp)
    # 1 wood on each of rounds R+1..R+5 (slots R..R+4).
    assert all(w[R + k] == 1 for k in range(5))
    assert w[R - 1] == 0   # current round never scheduled


# ---------------------------------------------------------------------------
# End-to-end round-start collection
# ---------------------------------------------------------------------------

def test_scheduled_wood_collected_at_round_start():
    # Schedule wood at R=1, then advance into round 2 via the real preparation step
    # and confirm the round-2 wood lands in actual supply and is consumed.
    s = setup(0)
    s = OCCUPATIONS["wood_collector"].on_play(s, 0)
    before = s.players[0].resources
    prep = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(prep)
    assert out.round_number == 2
    assert out.players[0].resources.wood == before.wood + 1   # round-2 wood collected
    # The good is consumed from the schedule once collected.
    assert _wood(out, 0)[1] == 0
    # Later rounds' wood remains scheduled (not yet entered).
    assert _wood(out, 0)[2] == 1 and _wood(out, 0)[5] == 1
    assert sum(_wood(out, 0)) == 4   # four of five rounds still pending
