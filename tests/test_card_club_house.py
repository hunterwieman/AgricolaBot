"""Tests for Club House (minor improvement, B46; Bubulcus Expansion).

Card text: "Place 1 food on each of the next 4 round spaces and 1 stone on the
round space after that. At the start of these rounds, you get the respective
good."
Cost 3 Wood / 2 Clay; no prereq; not passing; 1 VP.

A Category-8 deferred-goods minor: 1 food on rounds R+1..R+4 and 1 stone on R+5
(R = current round), all riding on `future_resources`, collected at the start of
each round via `engine._complete_preparation`. Covered:
- registration (cost / vps / no prereq / not passing);
- the on-play schedule (food on the next 4 rounds, stone on the 5th — the
  off-by-one upper bound and single-round stone are the traps);
- the current round is never scheduled, the opponent is untouched;
- the late-play clamp past round 14;
- a REAL play-via-PendingPlayMinor flow placing the schedule + paying the cost;
- an end-to-end round-start collection (a scheduled good lands in actual supply).
"""
import agricola.cards.club_house  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from tests.factories import with_pending_stack

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("club_house",) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _food(state, idx):
    return [r.food for r in state.players[idx].future_resources]


def _stone(state, idx):
    return [r.stone for r in state.players[idx].future_resources]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "club_house" in MINORS
    spec = MINORS["club_house"]
    assert spec.card_id == "club_house"
    # "3 Wood / 2 Clay" is an ALTERNATIVE ("/") cost: printed 3-wood in `cost`, the
    # 2-clay alternative in `alt_costs` — pay ONE, not both.
    assert spec.cost == Cost(resources=Resources(wood=3))
    assert spec.alt_costs == (Cost(resources=Resources(clay=2)),)
    assert spec.vps == 1
    assert spec.passing_left is False


def test_no_prereq():
    # No prerequisite: prereq_met holds even on a fresh state.
    s = setup(0)
    assert prereq_met(MINORS["club_house"], s, 0)


# ---------------------------------------------------------------------------
# On-play schedule — food on R+1..R+4, stone on R+5
# ---------------------------------------------------------------------------

def test_on_play_schedules_food_next_four_and_stone_fifth():
    s = setup(0)   # R=1 → food on rounds 2,3,4,5; stone on round 6
    out = MINORS["club_house"].on_play(s, 0)
    f, st = _food(out, 0), _stone(out, 0)
    # Food on the next 4 round spaces (rounds 2..5 = slots 1..4), nowhere else.
    assert f[1] == f[2] == f[3] == f[4] == 1
    assert sum(f) == 4
    # Stone on the single round after that (round 6 = slot 5), nowhere else.
    assert st[5] == 1
    assert sum(st) == 1
    # The current round (1, slot 0) is never scheduled, for either good.
    assert f[0] == 0 and st[0] == 0
    # Food and stone do not overlap on any slot (the stone round carries no food).
    assert f[5] == 0


def test_on_play_other_player_untouched():
    s = setup(0)
    out = MINORS["club_house"].on_play(s, 0)
    assert all(g == Resources() for g in out.players[1].future_resources)


def test_on_play_mid_game_offset():
    # R=7 → food on rounds 8,9,10,11; stone on round 12.
    s = fast_replace(setup(0), round_number=7)
    out = MINORS["club_house"].on_play(s, 0)
    f, st = _food(out, 0), _stone(out, 0)
    assert [i for i, x in enumerate(f) if x] == [7, 8, 9, 10]   # rounds 8..11
    assert [i for i, x in enumerate(st) if x] == [11]           # round 12
    assert sum(f) == 4 and sum(st) == 1


def test_on_play_clamps_past_round_14():
    # R=12 → food on rounds 13,14 kept; food on 15,16 and stone on 17 dropped.
    s = fast_replace(setup(0), round_number=12)
    out = MINORS["club_house"].on_play(s, 0)
    f, st = _food(out, 0), _stone(out, 0)
    assert f[12] == 1 and f[13] == 1   # rounds 13, 14
    assert sum(f) == 2                  # rounds 15, 16 dropped
    assert sum(st) == 0                 # stone (round 17) dropped


def test_on_play_stone_kept_when_just_in_range():
    # R=9 → food on 10,11,12,13; stone on round 14 (the last legal slot, kept).
    s = fast_replace(setup(0), round_number=9)
    out = MINORS["club_house"].on_play(s, 0)
    f, st = _food(out, 0), _stone(out, 0)
    assert sum(f) == 4
    assert st[13] == 1 and sum(st) == 1   # round 14 stone survives the clamp


# ---------------------------------------------------------------------------
# Real play-via-PendingPlayMinor flow with the ALTERNATIVE ("/") cost
# ---------------------------------------------------------------------------

def _play_minor_state(res):
    """A CARDS state at a PendingPlayMinor with `club_house` in hand and `res` on
    hand. Returns (state, current_player)."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp], hand_minors=frozenset({"club_house"}), resources=res)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def _minor_commits(state, card_id="club_house"):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == card_id]


def test_both_alternatives_offered_when_both_affordable():
    # Enough of BOTH 3 wood and 2 clay -> two distinct options (3 wood XOR 2 clay).
    cs, _cp = _play_minor_state(Resources(wood=3, clay=2))
    commits = _minor_commits(cs)
    payments = sorted((c.payment.wood, c.payment.clay) for c in commits)
    assert payments == [(0, 2), (3, 0)]   # a 2-clay option and a 3-wood option


def test_pay_via_wood_debits_only_wood_and_schedules():
    cs, cp = _play_minor_state(Resources(wood=3, clay=2))
    R = cs.round_number
    wood_commit = next(c for c in _minor_commits(cs) if c.payment.wood == 3)
    out = step(cs, wood_commit)
    pl = out.players[cp]
    assert pl.resources.wood == 0    # 3 wood spent
    assert pl.resources.clay == 2    # clay untouched (alternative, not both)
    assert "club_house" in pl.minor_improvements        # kept (not passing)
    assert "club_house" not in pl.hand_minors           # left hand
    # The card effect still fires: food on R+1..R+4, stone on R+5.
    assert _food(out, cp)[R] == 1 and _food(out, cp)[R + 3] == 1
    assert sum(_food(out, cp)) == 4
    assert _stone(out, cp)[R + 4] == 1 and sum(_stone(out, cp)) == 1


def test_pay_via_clay_debits_only_clay_and_schedules():
    cs, cp = _play_minor_state(Resources(wood=3, clay=2))
    R = cs.round_number
    clay_commit = next(c for c in _minor_commits(cs) if c.payment.clay == 2)
    out = step(cs, clay_commit)
    pl = out.players[cp]
    assert pl.resources.clay == 0    # 2 clay spent
    assert pl.resources.wood == 3    # wood untouched
    assert "club_house" in pl.minor_improvements
    # The card effect still fires.
    assert sum(_food(out, cp)) == 4
    assert _stone(out, cp)[R + 4] == 1 and sum(_stone(out, cp)) == 1


def test_only_wood_alternative_offered_when_only_wood_affordable():
    # 3 wood but only 1 clay -> only the wood alternative is playable.
    cs, _cp = _play_minor_state(Resources(wood=3, clay=1))
    commits = _minor_commits(cs)
    assert len(commits) == 1
    assert commits[0].payment.wood == 3 and commits[0].payment.clay == 0


def test_only_clay_alternative_offered_when_only_clay_affordable():
    # 2 clay but only 2 wood (short of the 3-wood alternative) -> only clay is playable.
    cs, _cp = _play_minor_state(Resources(wood=2, clay=2))
    commits = _minor_commits(cs)
    assert len(commits) == 1
    assert commits[0].payment.clay == 2 and commits[0].payment.wood == 0


# ---------------------------------------------------------------------------
# End-to-end round-start collection
# ---------------------------------------------------------------------------

def test_food_collected_at_first_scheduled_round():
    # Schedule at R=1, then advance into round 2; the round-2 food lands in supply
    # and is cleared from the schedule.
    s = setup(0)
    s = MINORS["club_house"].on_play(s, 0)
    before = s.players[0].resources.food
    prep = fast_replace(s, round_number=1, phase=Phase.PREPARATION)
    out = _complete_preparation(prep)
    assert out.round_number == 2
    assert out.players[0].resources.food == before + 1   # round-2 food collected
    assert _food(out, 0)[1] == 0                          # consumed from the schedule
    # Later food rounds + the stone round remain scheduled.
    assert _food(out, 0)[2] == _food(out, 0)[3] == _food(out, 0)[4] == 1
    assert _stone(out, 0)[5] == 1


def test_stone_collected_at_fifth_scheduled_round():
    # Advance into round 6 (the stone round) and confirm 1 stone lands in supply.
    s = setup(0)
    s = MINORS["club_house"].on_play(s, 0)   # stone scheduled for round 6
    before = s.players[0].resources.stone
    prep = fast_replace(s, round_number=5, phase=Phase.PREPARATION)
    out = _complete_preparation(prep)
    assert out.round_number == 6
    assert out.players[0].resources.stone == before + 1   # round-6 stone collected
    assert _stone(out, 0)[5] == 0                          # consumed from the schedule
