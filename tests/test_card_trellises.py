"""Tests for Trellises (minor improvement, A47; Artifex Expansion).

Card text: "Immediately place 1 food on each of the next round spaces, up to the
number of fences you have built. At the start of these rounds, you get the food."
Cost: 1 Wood. No prerequisite. VPs: 0. Not passing.

Category-8 deferred-goods card (mirrors tests/test_cards_category8.py): the whole
effect runs at play (on_play), scheduling +1 food onto rounds R+1..R+N where
N = fences_built(farmyard). Collection rides on `future_resources`, paid out at the
start of each scheduled round by `_complete_preparation`.
"""
from __future__ import annotations

import agricola.cards.trellises  # noqa: F401  (registers the card; not in __init__)

from agricola.cards.specs import MINORS
from agricola.cards.triggers import TRIGGERS
from agricola.engine import _complete_preparation, step
from agricola.helpers import fences_built
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Phase
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _set_fences(state, idx, n):
    """Place `n` fence pieces for player `idx` by flipping the first `n` slots of
    the horizontal fence array (shape 4x5 = 20 pieces, plenty for any test)."""
    p = state.players[idx]
    flat = [False] * 20
    for i in range(n):
        flat[i] = True
    h = tuple(tuple(flat[r * 5 + c] for c in range(5)) for r in range(4))
    fy = fast_replace(p.farmyard, horizontal_fences=h)
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _food(state, idx):
    return [r.food for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_trellises_registered():
    assert "trellises" in MINORS
    spec = MINORS["trellises"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    # Pure on-play minor — no trigger/hook machinery.
    for entries in TRIGGERS.values():
        assert "trellises" not in {e.card_id for e in entries}


# ---------------------------------------------------------------------------
# on_play scheduling — N fences → +1 food on the next N round spaces
# ---------------------------------------------------------------------------

def test_on_play_schedules_next_n_round_spaces():
    s = _set_fences(setup(0), 0, 3)   # R=1, 3 fences → rounds 2,3,4
    assert fences_built(s.players[0].farmyard) == 3
    out = MINORS["trellises"].on_play(s, 0)
    f = _food(out, 0)
    assert f[0] == 0                   # round 1 (current) untouched
    assert f[1] == f[2] == f[3] == 1   # rounds 2,3,4
    assert f[4] == 0                   # round 5 not scheduled
    assert sum(f) == 3


def test_on_play_count_is_fence_pieces_not_pastures():
    # 5 fence pieces → 5 scheduled rounds, regardless of pasture decomposition.
    s = _set_fences(setup(0), 0, 5)   # R=1 → rounds 2..6
    out = MINORS["trellises"].on_play(s, 0)
    f = _food(out, 0)
    assert [f[i] for i in range(1, 6)] == [1, 1, 1, 1, 1]
    assert sum(f) == 5


def test_on_play_zero_fences_schedules_nothing():
    s = setup(0)
    assert fences_built(s.players[0].farmyard) == 0
    out = MINORS["trellises"].on_play(s, 0)
    assert sum(_food(out, 0)) == 0


def test_on_play_clamps_past_round_14():
    # Round 12 with 5 fences → rounds 13,14 scheduled; 15,16,17 dropped by the
    # 1..14 slot clamp (the "up to ... remaining round spaces" cap, for free).
    s = _set_fences(fast_replace(setup(0), round_number=12), 0, 5)
    out = MINORS["trellises"].on_play(s, 0)
    f = _food(out, 0)
    assert f[12] == 1 and f[13] == 1   # rounds 13, 14
    assert sum(f) == 2                  # only 2 remaining rounds, not 5


def test_on_play_starts_after_current_round_midgame():
    # Mid-game (R=7): scheduling starts at R+1=8, never re-credits the current round.
    s = _set_fences(fast_replace(setup(0), round_number=7), 0, 2)
    out = MINORS["trellises"].on_play(s, 0)
    f = _food(out, 0)
    assert f[6] == 0                    # round 7 (current) untouched
    assert f[7] == 1 and f[8] == 1      # rounds 8, 9
    assert sum(f) == 2


# ---------------------------------------------------------------------------
# End-to-end: play the minor at a real PendingPlayMinor, then collect at round start
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("trellises",) + tuple(f"m{i}" for i in range(20)),
)


def test_play_minor_flow_and_round_start_collection():
    cs, _env = setup_env(0, card_pool=_POOL)
    cp = cs.current_player
    # Give the player the card in hand, the wood to pay, and 2 fence pieces.
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"trellises"}),
                     resources=Resources(wood=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = _set_fences(cs, cp, 2)        # R=1 → schedule rounds 2,3

    # Drive a real PendingPlayMinor and commit the card.
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, "trellises"))

    # Card left the hand; cost paid; food scheduled on rounds 2 and 3.
    pl = cs.players[cp]
    assert "trellises" in pl.minor_improvements
    assert "trellises" not in pl.hand_minors
    assert pl.resources.wood == 0
    f = _food(cs, cp)
    assert f[1] == 1 and f[2] == 1 and f[0] == 0 and f[3] == 0

    # Collection at the start of round 2: _complete_preparation pays out the slot.
    food_before = cs.players[cp].resources.food
    prep = fast_replace(cs, round_number=1, phase=Phase.PREPARATION)
    prep = _complete_preparation(prep)
    while prep.pending_stack:                       # resolve the reveal nature step
        prep = step(prep, legal_actions(prep)[0])
    assert prep.round_number == 2
    assert prep.players[cp].resources.food == food_before + 1
