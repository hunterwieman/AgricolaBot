"""Tests for Granary (minor improvement, C65; Consul Dirigens): "Place 1 grain each
on the remaining spaces for rounds 8, 10, and 12. At the start of these rounds, you
get the grain." Cost 3 Wood / 3 Clay; no prereq; 1 VP; not passing.

A Category-8 deferred-goods card that schedules 1 grain onto the ABSOLUTE round
spaces 8, 10, 12 (future_resources slots 7, 9, 11), with a "/"-alternative cost.
Coverage: registration; the on-play schedule onto the correct absolute slots via a
REAL PendingPlayMinor play; the "remaining" clause (a past round is a harmless dead
write); the scheduled grain is actually collected at the target round's start; and
the alternative cost (pay 3 wood XOR 3 clay).
"""
import agricola.cards.granary  # noqa: F401  (registers the card)

from agricola.actions import CommitPlayMinor
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack, with_round

CARD_ID = "granary"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _grain_sched(state, idx):
    return [r.grain for r in state.players[idx].future_resources]


def _play_minor_state(res, round_number=1):
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = with_round(cs, round_number)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}), resources=res)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def _commits(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=3))
    assert spec.alt_costs == (Cost(resources=Resources(clay=3)),)
    assert spec.cost_labels == ()      # reward NOT coupled to which alt is paid
    assert spec.vps == 1
    assert not spec.passing_left
    assert spec.prereq is None


# ---------------------------------------------------------------------------
# The on-play schedule onto absolute rounds 8, 10, 12
# ---------------------------------------------------------------------------

def test_schedules_grain_on_rounds_8_10_12():
    cs, cp = _play_minor_state(Resources(wood=3), round_number=1)
    before = _grain_sched(cs, cp)
    (commit,) = _commits(cs)
    out = step(cs, commit)
    g = _grain_sched(out, cp)
    # Slots are 0-indexed: round N -> slot N-1. Rounds 8/10/12 -> slots 7/9/11.
    assert g[7] == before[7] + 1
    assert g[9] == before[9] + 1
    assert g[11] == before[11] + 1
    # Not rounds 9 or 11 (slots 8, 10), and not 13/14.
    assert g[8] == before[8]
    assert g[10] == before[10]
    assert g[12] == before[12] and g[13] == before[13]
    assert CARD_ID in out.players[cp].minor_improvements


def test_remaining_clause_past_round_is_harmless_dead_write():
    """Played in round 9, the round-8 slot (7) is written but never re-collected
    (rounds advance monotonically), so only the still-future rounds 10 and 12 pay
    out. The dead write to slot 7 is harmless."""
    cs, cp = _play_minor_state(Resources(wood=3), round_number=9)
    (commit,) = _commits(cs)
    out = step(cs, commit)
    g = _grain_sched(out, cp)
    # Slot 7 (round 8) was written but round 8 is in the past -> never collected.
    assert g[7] == 1
    # The still-future rounds 10 and 12 are scheduled and WILL pay out.
    assert g[9] == 1 and g[11] == 1


# ---------------------------------------------------------------------------
# The scheduled grain is actually collected at the target round's start
# ---------------------------------------------------------------------------

def test_grain_collected_at_round_8_start():
    from agricola.constants import Phase
    from agricola.engine import _complete_preparation

    cs, cp = _play_minor_state(Resources(wood=3), round_number=1)
    (commit,) = _commits(cs)
    s = step(cs, commit)
    assert _grain_sched(s, cp)[7] == 1

    grain_before = s.players[cp].resources.grain
    # Enter round 8's start (slot 7 is collected when round 8 is entered).
    s = fast_replace(s, round_number=7, phase=Phase.PREPARATION)
    s = _complete_preparation(s)
    assert s.round_number == 8
    assert s.players[cp].resources.grain == grain_before + 1
    assert _grain_sched(s, cp)[7] == 0   # slot consumed


# ---------------------------------------------------------------------------
# Alternative ("/") cost: pay EITHER 3 wood OR 3 clay, not both
# ---------------------------------------------------------------------------

def test_both_alternatives_offered_when_both_affordable():
    cs, _cp = _play_minor_state(Resources(wood=3, clay=3))
    payments = sorted((c.payment.wood, c.payment.clay) for c in _commits(cs))
    assert payments == [(0, 3), (3, 0)]   # a 3-clay option and a 3-wood option


def test_pay_via_clay_debits_only_clay():
    cs, cp = _play_minor_state(Resources(wood=3, clay=3))
    clay_commit = next(c for c in _commits(cs) if c.payment.clay == 3)
    out = step(cs, clay_commit)
    p = out.players[cp]
    assert p.resources.clay == 0 and p.resources.wood == 3
    assert CARD_ID in p.minor_improvements


def test_only_wood_alternative_when_only_wood_affordable():
    cs, _cp = _play_minor_state(Resources(wood=3, clay=2))
    commits = _commits(cs)
    assert len(commits) == 1
    assert commits[0].payment.wood == 3 and commits[0].payment.clay == 0


# ---------------------------------------------------------------------------
# Printed 1 VP is scored
# ---------------------------------------------------------------------------

def test_printed_vp_scored():
    cs, cp = _play_minor_state(Resources(wood=3))
    (commit,) = _commits(cs)
    out = step(cs, commit)
    with_card, _ = score(out, cp)
    stripped_p = fast_replace(
        out.players[cp],
        minor_improvements=out.players[cp].minor_improvements - {CARD_ID})
    stripped = fast_replace(out, players=tuple(
        stripped_p if i == cp else out.players[i] for i in range(2)))
    without_card, _ = score(stripped, cp)
    assert with_card == without_card + 1
