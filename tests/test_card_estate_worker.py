"""Tests for Estate Worker (occupation, B125; Bubulcus Expansion).

Card text: "Place 1 wood, 1 clay, 1 reed, and 1 stone in this order on the next 4
round spaces. At the start of these rounds, you get the respective building
resource."

A Category-8 deferred-goods occupation: one building resource placed per round,
mapped positionally (wood→R+1, clay→R+2, reed→R+3, stone→R+4), collected at the
start of each round via `engine._complete_preparation`. Covered:
- registration (in OCCUPATIONS, plain occupation: no cost/prereq/vps/passing);
- the on-play schedule (positional good mapping, not same-good-on-all-4);
- the late-play clamp past round 14;
- a REAL play-via-Lessons flow placing the schedule;
- an end-to-end round-start collection (scheduled good lands in actual resources).
"""
import agricola.cards.estate_worker  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env

_POOL = CardPool(
    occupations=("estate_worker",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wood(state, idx):
    return [r.wood for r in state.players[idx].future_resources]


def _clay(state, idx):
    return [r.clay for r in state.players[idx].future_resources]


def _reed(state, idx):
    return [r.reed for r in state.players[idx].future_resources]


def _stone(state, idx):
    return [r.stone for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_estate_worker_registered_plain_occupation():
    # OccupationSpec carries only card_id + on_play (no structured cost/prereq/vps
    # — occupations are plain, played via Lessons; the on-play schedule is the effect).
    assert "estate_worker" in OCCUPATIONS
    spec = OCCUPATIONS["estate_worker"]
    assert spec.card_id == "estate_worker"
    assert callable(spec.on_play)


# ---------------------------------------------------------------------------
# On-play schedule — positional good mapping
# ---------------------------------------------------------------------------

def test_on_play_positional_good_mapping():
    s = setup(0)   # R=1 → wood@2, clay@3, reed@4, stone@5
    out = OCCUPATIONS["estate_worker"].on_play(s, 0)
    w, c, r, st = _wood(out, 0), _clay(out, 0), _reed(out, 0), _stone(out, 0)
    # Each good lands on exactly one round, positionally — not all four on the
    # same rounds (that would be the Wall-Builder same-good shape).
    assert w[1] == 1 and sum(w) == 1   # wood on round 2 only
    assert c[2] == 1 and sum(c) == 1   # clay on round 3 only
    assert r[3] == 1 and sum(r) == 1   # reed on round 4 only
    assert st[4] == 1 and sum(st) == 1  # stone on round 5 only
    # The current round (1, slot 0) is never scheduled.
    assert w[0] == c[0] == r[0] == st[0] == 0


def test_on_play_other_player_untouched():
    s = setup(0)
    out = OCCUPATIONS["estate_worker"].on_play(s, 0)
    assert all(g == Resources() for g in out.players[1].future_resources)


def test_on_play_clamps_past_round_14():
    # R=12 → wood@13, clay@14 kept; reed@15, stone@16 dropped (> round 14).
    s = fast_replace(setup(0), round_number=12)
    out = OCCUPATIONS["estate_worker"].on_play(s, 0)
    assert _wood(out, 0)[12] == 1 and sum(_wood(out, 0)) == 1   # round 13
    assert _clay(out, 0)[13] == 1 and sum(_clay(out, 0)) == 1   # round 14
    assert sum(_reed(out, 0)) == 0    # round 15 dropped
    assert sum(_stone(out, 0)) == 0   # round 16 dropped


# ---------------------------------------------------------------------------
# Real play-via-Lessons flow
# ---------------------------------------------------------------------------

def test_played_via_lessons_schedules_next_four_rounds():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"estate_worker"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    R = cs.round_number

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="estate_worker"))

    assert "estate_worker" in cs.players[cp].occupations
    assert _wood(cs, cp)[R] == 1     # wood on round R+1 (slot R)
    assert _clay(cs, cp)[R + 1] == 1  # clay on round R+2
    assert _reed(cs, cp)[R + 2] == 1  # reed on round R+3
    assert _stone(cs, cp)[R + 3] == 1  # stone on round R+4


# ---------------------------------------------------------------------------
# End-to-end round-start collection
# ---------------------------------------------------------------------------

def test_scheduled_good_collected_at_round_start():
    # Schedule the four goods at R=1, then advance into round 2 via the real
    # preparation step and confirm the round-2 good (wood) lands in actual supply.
    s = setup(0)
    s = OCCUPATIONS["estate_worker"].on_play(s, 0)
    before = s.players[0].resources
    # Drive _complete_preparation entering round 2 (it reads round_number+1).
    prep = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(prep)
    assert out.round_number == 2
    assert out.players[0].resources.wood == before.wood + 1   # round-2 wood collected
    # The good is consumed from the schedule once collected.
    assert _wood(out, 0)[1] == 0
    # Later rounds' goods remain scheduled (not yet entered).
    assert _clay(out, 0)[2] == 1 and _reed(out, 0)[3] == 1 and _stone(out, 0)[4] == 1
