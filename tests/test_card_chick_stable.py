"""Tests for Chick Stable (minor improvement, B44; Bubulcus Expansion).

Card text: "Add 3 and 4 to the current round and place 2 food on each corresponding
round space. At the start of these rounds, you get the food."
Cost: "1 Wood/1 Clay" — an ALTERNATIVE cost: pay exactly ONE of 1 wood or 1 clay
(the "/" is never a sum; alt_costs pattern). No prerequisite. VPs: 0. Not passing.

Category-8 deferred-goods minor: on play it schedules 2 food onto the round spaces
R+3 and R+4 of `future_resources`, collected at the start of those rounds. Mirrors
tests/test_cards_category8.py for the scheduling cards.
"""
from __future__ import annotations

import agricola.cards.chick_stable  # noqa: F401  (registers the card)

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
    minors=("chick_stable",) + tuple(f"m{i}" for i in range(20)),
)


def _food(state, idx):
    return [r.food for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration / spec
# ---------------------------------------------------------------------------

def test_chick_stable_registered():
    assert "chick_stable" in MINORS
    spec = MINORS["chick_stable"]
    # "1 Wood/1 Clay" = pay exactly ONE alternative, never both.
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.alt_costs == (Cost(resources=Resources(clay=1)),)
    assert spec.vps == 0
    assert spec.passing_left is False
    # No prerequisite: any state qualifies.
    assert prereq_met(spec, setup(0), 0)


# ---------------------------------------------------------------------------
# on_play scheduling — 2 food on R+3 and R+4 (non-consecutive offsets)
# ---------------------------------------------------------------------------

def test_chick_stable_on_play_schedules_r3_r4():
    s = setup(0)   # R=1 → rounds 4 and 5 (slots 3 and 4)
    out = MINORS["chick_stable"].on_play(s, 0)
    f = _food(out, 0)
    assert f[3] == 2 and f[4] == 2
    assert sum(f) == 4
    # R+1, R+2 are NOT scheduled (unlike Pond Hut's contiguous range).
    assert f[1] == 0 and f[2] == 0
    assert f[0] == 0   # current round untouched


def test_chick_stable_on_play_midgame_offsets():
    s = fast_replace(setup(0), round_number=7)   # → rounds 10 and 11 (slots 9, 10)
    out = MINORS["chick_stable"].on_play(s, 0)
    f = _food(out, 0)
    assert f[9] == 2 and f[10] == 2
    assert sum(f) == 4


# ---------------------------------------------------------------------------
# Clamping past round 14 — late plays forfeit unreachable round spaces
# ---------------------------------------------------------------------------

def test_chick_stable_clamps_one_past_14():
    s = fast_replace(setup(0), round_number=11)   # R+3=14 kept, R+4=15 dropped
    out = MINORS["chick_stable"].on_play(s, 0)
    f = _food(out, 0)
    assert f[13] == 2          # round 14
    assert sum(f) == 2         # the R+4=15 space falls off the board


def test_chick_stable_clamps_both_past_14():
    s = fast_replace(setup(0), round_number=12)   # R+3=15, R+4=16 both dropped
    out = MINORS["chick_stable"].on_play(s, 0)
    assert sum(_food(out, 0)) == 0


# ---------------------------------------------------------------------------
# End-to-end: play the minor through the engine, collect food at round start
# ---------------------------------------------------------------------------

def _at_play_minor_frame():
    """A CARDS-mode state at a PendingPlayMinor host with the current player holding
    chick_stable in hand and able to afford it (1 wood + 1 clay).

    Mirrors tests/test_cards_minors.py: drive PendingPlayMinor by pushing it onto the
    stack directly (the established factory pattern for testing pendings)."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"chick_stable"}),
                     resources=Resources(wood=1, clay=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def test_chick_stable_offers_one_play_per_affordable_alternative():
    from agricola.actions import CommitPlayMinor
    cs, _cp = _at_play_minor_frame()
    # Holding 1 wood + 1 clay: both alternatives affordable -> two plays.
    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == "chick_stable"]
    payments = {(a.payment.wood, a.payment.clay) for a in plays}
    assert payments == {(1, 0), (0, 1)}        # pay wood OR pay clay, never both
    assert legal_actions(cs) == plays          # nothing else legal at the frame


def _play_paying(cs, wood, clay):
    from agricola.actions import CommitPlayMinor
    opts = [a for a in legal_actions(cs)
            if isinstance(a, CommitPlayMinor) and a.card_id == "chick_stable"
            and a.payment.wood == wood and a.payment.clay == clay]
    assert len(opts) == 1
    return opts[0]


def test_chick_stable_real_play_and_collect():
    cs, cp = _at_play_minor_frame()
    cs = step(cs, _play_paying(cs, wood=1, clay=0))
    # Card left hand (non-passing → kept in tableau); paid the WOOD alternative
    # only — the clay stays (the "/" cost is one-of, never a sum).
    assert "chick_stable" not in cs.players[cp].hand_minors
    assert "chick_stable" in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.wood == 0
    assert cs.players[cp].resources.clay == 1
    # Food scheduled on R+3 (round 4) and R+4 (round 5) — game is at round 1.
    assert cs.round_number == 1
    assert _food(cs, cp)[3] == 2 and _food(cs, cp)[4] == 2

    # Drain the pending stack, then advance to the start of round 4 and confirm the
    # scheduled food is actually distributed into the supply at round start.
    while cs.pending_stack:
        cs = step(cs, legal_actions(cs)[0])
    before_food = cs.players[cp].resources.food
    s4 = fast_replace(cs, round_number=3, phase=Phase.PREPARATION)
    s4 = _complete_preparation(s4)
    assert s4.round_number == 4
    # Round 4 (slot 3) food collected; round 5 (slot 4) still pending.
    assert s4.players[cp].resources.food - before_food == 2
    assert _food(s4, cp)[4] == 2
