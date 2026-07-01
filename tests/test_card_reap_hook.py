"""Tests for Reap Hook (minor improvement, D67; Dulcinaria Expansion).

Card text: "Place 1 grain on each of the next 3 of the round spaces 4, 7, 9, 11,
13, and 14. At the start of these rounds, you get the grain."
Cost 1 Wood; no prereq; not passing; no VP.

A Category-8 deferred-goods minor: 1 grain on each of the next 3 ENTRIES of the
specific list {4, 7, 9, 11, 13, 14} strictly after the current round (NOT the
literal next 3 rounds; NOT all remaining of the list), riding on
`future_resources`, collected at the start of each round via
`engine._complete_preparation`. Covered:
- registration (cost / no vps / no prereq / not passing);
- the on-play schedule — the "next 3 of the list" reading at several R values
  (R=1, R after some entries collected, and where only 1 or 2 remain — the clamp);
- the current/already-collected round is never scheduled (`> R`, not `>=`);
- the opponent is untouched;
- a REAL play-via-PendingPlayMinor flow placing the schedule + paying the cost;
- an end-to-end round-start collection (a scheduled grain lands in actual supply).
"""
import agricola.cards.reap_hook  # noqa: F401  (registers the card)

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
    minors=("reap_hook",) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _grain(state, idx):
    return [r.grain for r in state.players[idx].future_resources]


def _scheduled_rounds(state, idx):
    # 1-indexed rounds that carry a grain (slot r-1 holds round r).
    return [i + 1 for i, g in enumerate(_grain(state, idx)) if g]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "reap_hook" in MINORS
    spec = MINORS["reap_hook"]
    assert spec.card_id == "reap_hook"
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert spec.passing_left is False


def test_no_prereq():
    s = setup(0)
    assert prereq_met(MINORS["reap_hook"], s, 0)


# ---------------------------------------------------------------------------
# On-play schedule — the "next 3 of the round spaces 4,7,9,11,13,14" reading
# ---------------------------------------------------------------------------

def test_on_play_early_game_schedules_4_7_9():
    # R=1 → the next 3 entries of the list after round 1 are 4, 7, 9.
    s = setup(0)
    out = MINORS["reap_hook"].on_play(s, 0)
    assert _scheduled_rounds(out, 0) == [4, 7, 9]
    assert sum(_grain(out, 0)) == 3


def test_on_play_skips_literal_next_rounds():
    # The "next 3" are entries of the SPECIFIC list, not R+1, R+2, R+3.
    # Played at R=5: list entries after 5 are 7, 9, 11, 13, 14 → next 3 = 7, 9, 11.
    s = fast_replace(setup(0), round_number=5)
    out = MINORS["reap_hook"].on_play(s, 0)
    assert _scheduled_rounds(out, 0) == [7, 9, 11]
    assert sum(_grain(out, 0)) == 3


def test_on_play_already_collected_round_not_scheduled():
    # `> R` (strict): on round 7 (its space already collected), 7 must NOT be
    # scheduled; the next 3 are 9, 11, 13.
    s = fast_replace(setup(0), round_number=7)
    out = MINORS["reap_hook"].on_play(s, 0)
    assert _scheduled_rounds(out, 0) == [9, 11, 13]
    assert 7 not in _scheduled_rounds(out, 0)


def test_on_play_fewer_than_three_remaining():
    # R=13 → only round 14 remains in the list after 13.
    s = fast_replace(setup(0), round_number=13)
    out = MINORS["reap_hook"].on_play(s, 0)
    assert _scheduled_rounds(out, 0) == [14]
    assert sum(_grain(out, 0)) == 1


def test_on_play_two_remaining():
    # R=11 → list entries after 11 are 13, 14 → only 2 scheduled.
    s = fast_replace(setup(0), round_number=11)
    out = MINORS["reap_hook"].on_play(s, 0)
    assert _scheduled_rounds(out, 0) == [13, 14]
    assert sum(_grain(out, 0)) == 2


def test_on_play_none_remaining():
    # R=14 → nothing in the list strictly after 14.
    s = fast_replace(setup(0), round_number=14)
    out = MINORS["reap_hook"].on_play(s, 0)
    assert sum(_grain(out, 0)) == 0


def test_on_play_takes_only_first_three_when_many_remain():
    # On round 3, entries after 3 are 4,7,9,11,13,14 — the [:3] slice caps at 4,7,9.
    s = fast_replace(setup(0), round_number=3)
    out = MINORS["reap_hook"].on_play(s, 0)
    assert _scheduled_rounds(out, 0) == [4, 7, 9]
    assert 11 not in _scheduled_rounds(out, 0)


def test_on_play_other_player_untouched():
    s = setup(0)
    out = MINORS["reap_hook"].on_play(s, 0)
    assert all(g == Resources() for g in out.players[1].future_resources)


# ---------------------------------------------------------------------------
# Real play-via-PendingPlayMinor flow (placement + cost payment)
# ---------------------------------------------------------------------------

def test_played_via_real_flow_schedules_and_pays_cost():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        hand_minors=frozenset({"reap_hook"}),
        resources=Resources(wood=1),
    )
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))

    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )
    assert legal_actions(cs) == [sole_play_minor(cs, "reap_hook")]
    cs = step(cs, sole_play_minor(cs, "reap_hook"))

    pl = cs.players[cp]
    assert "reap_hook" in pl.minor_improvements        # kept (not passing)
    assert "reap_hook" not in pl.hand_minors            # left hand
    assert pl.resources == Resources()                  # cost 1 wood paid in full
    # Deferred schedule placed: grain on rounds 4, 7, 9 (R=1 at setup_env start).
    assert _scheduled_rounds(cs, cp) == [4, 7, 9]


# ---------------------------------------------------------------------------
# End-to-end round-start collection
# ---------------------------------------------------------------------------

def test_grain_collected_at_first_scheduled_round():
    # Schedule at R=1 (rounds 4,7,9), advance into round 4; the round-4 grain
    # lands in supply and is cleared from the schedule.
    s = setup(0)
    s = MINORS["reap_hook"].on_play(s, 0)
    before = s.players[0].resources.grain
    prep = fast_replace(s, round_number=3, phase=Phase.PREPARATION)
    out = _complete_preparation(prep)
    assert out.round_number == 4
    assert out.players[0].resources.grain == before + 1   # round-4 grain collected
    assert _grain(out, 0)[3] == 0                          # consumed from the schedule
    # Later grain rounds (7, 9) remain scheduled.
    assert _scheduled_rounds(out, 0) == [7, 9]
