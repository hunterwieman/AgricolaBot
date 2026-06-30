"""Tests for Lumberjack (occupation, B119; Bubulcus): "You immediately get 1 wood.
Additionally, place 1 wood on each of the next round spaces, up to the number of
fences you built. At the start of these rounds, you get the wood."

Two parts: an immediate +1 wood, then +1 wood scheduled onto the next N round
spaces where N = fence pieces built (`helpers.fences_built`). Mirrors
tests/test_cards_category8.py (the deferred-goods scheduler shape) and
tests/test_card_fellow_grazer.py (the play-via-Lessons engine flow).
"""
import agricola.cards.lumberjack  # noqa: F401  (registers the card)

from agricola import helpers
from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import _complete_preparation, step
from agricola.constants import Phase
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env

_POOL = CardPool(
    occupations=("lumberjack",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_fences(state, idx, n):
    """Mark `n` fence pieces built for player `idx` by flipping the first `n`
    horizontal-fence cells True. `fences_built` just sums all True cells, so the
    exact geometry is irrelevant to the count this card reads."""
    fy = state.players[idx].farmyard
    cells = [list(row) for row in fy.horizontal_fences]  # shape (4, 5)
    placed = 0
    for r in range(len(cells)):
        for c in range(len(cells[r])):
            if placed >= n:
                break
            cells[r][c] = True
            placed += 1
    fy = fast_replace(fy, horizontal_fences=tuple(tuple(row) for row in cells))
    p = fast_replace(state.players[idx], farmyard=fy)
    return fast_replace(state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx, card_id):
    p = fast_replace(state.players[idx], occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _wood_schedule(state, idx):
    return [r.wood for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "lumberjack" in OCCUPATIONS


# ---------------------------------------------------------------------------
# on_play — immediate +1 wood AND deferred wood on next N round spaces
# ---------------------------------------------------------------------------

def test_immediate_wood_and_schedule_with_three_fences():
    s = _set_fences(setup(0), 0, 3)  # round 1, 3 fences built
    before = s.players[0].resources.wood
    out = OCCUPATIONS["lumberjack"].on_play(s, 0)

    # Immediate +1 wood to supply.
    assert out.players[0].resources.wood == before + 1

    # Deferred: 1 wood on rounds 2, 3, 4 (R+1..R+3); slot r-1 holds round r.
    w = _wood_schedule(out, 0)
    assert w[0] == 0                  # round 1 (current) untouched
    assert w[1] == w[2] == w[3] == 1  # rounds 2, 3, 4
    assert w[4] == 0                  # round 5 not scheduled
    assert sum(w) == 3


def test_no_fences_grants_wood_but_schedules_nothing():
    s = setup(0)  # 0 fences built
    assert helpers.fences_built(s.players[0].farmyard) == 0
    before = s.players[0].resources.wood
    out = OCCUPATIONS["lumberjack"].on_play(s, 0)
    # Player still keeps the immediate +1 wood (the "immediately get 1 wood" clause).
    assert out.players[0].resources.wood == before + 1
    # No future round spaces scheduled.
    assert sum(_wood_schedule(out, 0)) == 0


def test_schedule_clamps_past_round_14():
    # Round 13 with 5 fences: rounds 14,15,16,17,18 — only round 14 is in range.
    s = _set_fences(fast_replace(setup(0), round_number=13), 0, 5)
    out = OCCUPATIONS["lumberjack"].on_play(s, 0)
    w = _wood_schedule(out, 0)
    assert w[13] == 1   # round 14
    assert sum(w) == 1  # rounds 15..18 dropped (past the 14-round game)


def test_count_reads_built_fences_not_supply():
    # Sanity: the count is fences PLACED on the board, independent of the supply pile.
    s = _set_fences(setup(0), 0, 2)
    assert helpers.fences_built(s.players[0].farmyard) == 2
    out = OCCUPATIONS["lumberjack"].on_play(s, 0)
    assert sum(_wood_schedule(out, 0)) == 2


def test_only_owner_is_affected():
    s = _set_fences(setup(0), 0, 3)
    s = _set_fences(s, 1, 3)
    out = OCCUPATIONS["lumberjack"].on_play(s, 0)
    # Opponent's schedule is untouched.
    assert sum(_wood_schedule(out, 1)) == 0


# ---------------------------------------------------------------------------
# Real engine flow — play via Lessons, then collect the scheduled wood
# ---------------------------------------------------------------------------

def test_played_via_lessons_grants_and_collects():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"lumberjack"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = _set_fences(cs, cp, 2)  # 2 fences → wood on rounds R+1, R+2
    R = cs.round_number
    wood_before = cs.players[cp].resources.wood

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="lumberjack"))

    assert "lumberjack" in cs.players[cp].occupations
    # Immediate +1 wood landed in the supply.
    assert cs.players[cp].resources.wood == wood_before + 1
    # The deferred wood is scheduled on rounds R+1 and R+2.
    w = _wood_schedule(cs, cp)
    assert w[R] == 1 and w[R + 1] == 1
    assert sum(w) == 2


def test_scheduled_wood_collected_at_round_start():
    # Drive _complete_preparation to enter the scheduled round and confirm the
    # promised wood is paid out into the supply.
    s = _own(fast_replace(setup(0), round_number=2, phase=Phase.PREPARATION), 0, "lumberjack")
    # Hand-schedule 1 wood for round 3 (the round about to be entered).
    p = s.players[0]
    slots = list(p.future_resources)
    slots[2] = slots[2] + Resources(wood=1)   # slot 2 → round 3
    p = fast_replace(p, future_resources=tuple(slots))
    s = fast_replace(s, players=(p, s.players[1]))
    wood_before = s.players[0].resources.wood

    out = _complete_preparation(s)
    assert out.round_number == 3
    assert out.players[0].resources.wood == wood_before + 1
