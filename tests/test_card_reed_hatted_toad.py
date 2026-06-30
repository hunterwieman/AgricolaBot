"""Tests for Reed-Hatted Toad (minor improvement, C78; Corbarius Expansion).

Card text: "Add 5, 7, 9, 11, and 13 to the current round and place 1 reed on each
corresponding round space. At the start of these rounds, you get the reed."
Cost: 1 Food. No prerequisite. VPs: 0. Not passing.

Category-8 deferred-goods minor: on play it schedules 1 reed onto the round spaces
R+5, R+7, R+9, R+11, R+13 of `future_resources`, collected at the start of those
rounds. Mirrors tests/test_card_chick_stable.py.
"""
from __future__ import annotations

import agricola.cards.reed_hatted_toad  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("reed_hatted_toad",) + tuple(f"m{i}" for i in range(20)),
)


def _reed(state, idx):
    return [r.reed for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_reed_hatted_toad_registered():
    assert "reed_hatted_toad" in MINORS
    spec = MINORS["reed_hatted_toad"]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    # No prerequisite: any state qualifies.
    assert prereq_met(spec, setup(0), 0)


# ---------------------------------------------------------------------------
# on_play scheduling — 1 reed on R+5, R+7, R+9, R+11, R+13 (non-consecutive)
# ---------------------------------------------------------------------------

def test_reed_hatted_toad_on_play_schedules_offsets():
    s = setup(0)   # R=1 → rounds 6, 8, 10, 12, 14 (slots 5, 7, 9, 11, 13)
    out = MINORS["reed_hatted_toad"].on_play(s, 0)
    f = _reed(out, 0)
    assert f[5] == 1 and f[7] == 1 and f[9] == 1 and f[11] == 1 and f[13] == 1
    assert sum(f) == 5
    # The skipped offsets (even gaps) are NOT scheduled.
    assert f[6] == 0 and f[8] == 0 and f[10] == 0 and f[12] == 0
    assert f[0] == 0   # current round untouched


def test_reed_hatted_toad_uses_offsets_not_absolute():
    # Played at round 2: offsets give rounds 7, 9, 11, 13 (slots 6, 8, 10, 12);
    # R+13 = 15 is dropped. Absolute [5,7,9,11,13] would (wrongly) include round 5.
    s = fast_replace(setup(0), round_number=2)
    out = MINORS["reed_hatted_toad"].on_play(s, 0)
    f = _reed(out, 0)
    assert f[6] == 1 and f[8] == 1 and f[10] == 1 and f[12] == 1  # rounds 7,9,11,13
    assert f[4] == 0   # round 5 NOT scheduled — proves offsets, not absolutes
    assert sum(f) == 4  # R+13 = round 15 falls off the board


# ---------------------------------------------------------------------------
# Clamping past round 14 — late plays forfeit unreachable round spaces
# ---------------------------------------------------------------------------

def test_reed_hatted_toad_clamps_past_14():
    # Played at round 8: offsets → rounds 13, 15, 17, 19, 21; only round 13 (slot
    # 12) is on the board.
    s = fast_replace(setup(0), round_number=8)
    out = MINORS["reed_hatted_toad"].on_play(s, 0)
    f = _reed(out, 0)
    assert f[12] == 1
    assert sum(f) == 1


def test_reed_hatted_toad_clamps_all_past_14():
    # Played at round 10: every offset (R+5 = 15 and beyond) is off the board.
    s = fast_replace(setup(0), round_number=10)
    out = MINORS["reed_hatted_toad"].on_play(s, 0)
    assert sum(_reed(out, 0)) == 0


# ---------------------------------------------------------------------------
# End-to-end: play the minor through the engine, collect reed at round start
# ---------------------------------------------------------------------------

def _at_play_minor_frame():
    """A CARDS-mode state at a PendingPlayMinor host with the current player holding
    reed_hatted_toad in hand and able to afford it (1 food).

    Mirrors tests/test_card_chick_stable.py: drive PendingPlayMinor by pushing it
    onto the stack directly (the established factory pattern for testing pendings)."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"reed_hatted_toad"}),
                     resources=Resources(food=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def test_reed_hatted_toad_is_only_legal_minor_play():
    cs, _cp = _at_play_minor_frame()
    assert legal_actions(cs) == [sole_play_minor(cs, "reed_hatted_toad")]


def test_reed_hatted_toad_real_play_and_collect():
    cs, cp = _at_play_minor_frame()
    cs = step(cs, sole_play_minor(cs, "reed_hatted_toad"))
    # Card left hand (non-passing → kept in tableau), cost paid: 1 food.
    assert "reed_hatted_toad" not in cs.players[cp].hand_minors
    assert "reed_hatted_toad" in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.food == 0
    # Reed scheduled on R+5 (round 6) etc. — game is at round 1.
    assert cs.round_number == 1
    assert _reed(cs, cp)[5] == 1 and _reed(cs, cp)[13] == 1

    # Drain the pending stack, then advance to the start of round 6 and confirm the
    # scheduled reed is actually distributed into the supply at round start.
    while cs.pending_stack:
        cs = step(cs, legal_actions(cs)[0])
    before_reed = cs.players[cp].resources.reed
    s6 = fast_replace(cs, round_number=5, phase=Phase.PREPARATION)
    s6 = _complete_preparation(s6)
    assert s6.round_number == 6
    # Round 6 (slot 5) reed collected; round 8 (slot 7) still pending.
    assert s6.players[cp].resources.reed - before_reed == 1
    assert _reed(s6, cp)[7] == 1
