"""Tests for Grassland Harrow (minor improvement, B18; Bubulcus Expansion).

Card text: "Add 1 to the current round for each building resource in your supply and
place 1 field on the corresponding round space. At the start of the round, you can plow
the field."
Cost: 2 Wood. Prerequisite: 2 Occupations, 1 Building Resource in Your Supply After
Payment (transcription corrected against the physical card, user 2026-07-27 — the
catalog JSON had dropped the "After Payment" qualifier).

A Handplow (A19) variant: a deferred, optional round-start plow that rides on the
card-only `future_rewards` (FutureReward), differing in that (a) the round offset is
VARIABLE — "1 per building resource in your supply" rather than a fixed 5 — and (b) its
building-resource prerequisite reads the supply AFTER the play cost is debited: a
per-PAYMENT gate (`register_play_minor_payment_gate`), so the play is legal iff SOME
payment's post-debit state keeps >= 1 building resource and only qualifying payments
are offered. Mirrors `test_cards_category8.py`'s Handplow coverage plus the gate suite.
"""
from __future__ import annotations

import json
from pathlib import Path

import agricola.cards.grassland_harrow  # noqa: F401
import agricola.cards.wood_expert  # noqa: F401  (the food-for-wood conversion, for
#                                     the per-payment gate tests)

from agricola.actions import CommitFoodPayment, CommitPlayMinor, FireTrigger, Proceed
from agricola.cards.specs import MINORS, PLAY_MINOR_PAYMENT_GATES, prereq_met
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import _can_plow, legal_actions, playable_minors
from agricola.pending import (
    PendingFoodPayment,
    PendingHarvestWindow,
    PendingPlayMinor,
    PendingPlow,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell, FutureReward
from tests.factories import with_pending_stack

CARD_ID = "grassland_harrow"
_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"


# ---------------------------------------------------------------------------
# Test helpers (mirroring test_cards_category8.py)
# ---------------------------------------------------------------------------

def _give_occ_count(state, idx, n):
    p = state.players[idx]
    p = fast_replace(p, occupations=frozenset(f"_occ{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_resources(state, idx, **kw):
    p = state.players[idx]
    p = fast_replace(p, resources=Resources(**kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _fill_grid_fields(state, idx):
    """Fill every EMPTY cell with FIELD so no plowable cell remains."""
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.EMPTY:
                grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=2))
    assert spec.min_occupations == 2
    # The building-resource half of the prerequisite is POST-PAYMENT (corrected
    # transcription, user 2026-07-27): a per-payment gate, not a `prereq=` HAVE-check.
    assert spec.prereq is None
    assert CARD_ID in PLAY_MINOR_PAYMENT_GATES
    # The deferred plow is an OPTIONAL round_space_collection trigger (not a forced auto).
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("round_space_collection", [])}


def test_catalog_row_carries_corrected_prerequisite():
    """The catalog transcription was corrected against the physical card (user
    2026-07-27): the prerequisite reads "... After Payment"."""
    row = next(r for r in json.load(open(_DATA / "revised_minor_improvements.json"))
               if r["name"] == "Grassland Harrow")
    assert row["prerequisites"] == (
        "2 Occupations, 1 Building Resource in Your Supply After Payment")


# ---------------------------------------------------------------------------
# on_play — variable round offset
# ---------------------------------------------------------------------------

def test_on_play_schedules_at_round_plus_building_resources():
    # R=1 (setup), 3 building resources in supply → field on round 1+3 = 4 (slot 3).
    s = setup(0)
    s = _set_resources(s, 0, wood=1, clay=1, reed=1)  # 3 building resources
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[3].effect_card_ids          # round 4
    assert sum(1 for r in fr if r) == 1              # only that one slot populated
    # Goods carrier untouched (this is an effect, not goods).
    assert all(r.food == 0 for r in out.players[0].future_resources)


def test_on_play_counts_all_four_building_resources():
    # wood + clay + reed + stone = 1+2+1+1 = 5 → round 1+5 = 6 (slot 5).
    s = setup(0)
    s = _set_resources(s, 0, wood=1, clay=2, reed=1, stone=1)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[5].effect_card_ids          # round 6


def test_on_play_ignores_non_building_resources():
    # food / grain / veg are NOT building resources: count = wood only = 1 → round 2.
    s = setup(0)
    s = _set_resources(s, 0, wood=1, food=5, grain=3, veg=2)
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert CARD_ID in fr[1].effect_card_ids          # round 1+1 = 2
    assert sum(1 for r in fr if r) == 1


def test_on_play_clamps_past_round_14():
    # From a late round with a large building-resource count, the target round exceeds
    # 14 → schedule_effect silently drops it (no round space past 14).
    s = setup(0)
    s = fast_replace(s, round_number=13)
    s = _set_resources(s, 0, wood=5)                 # round 13+5 = 18 → dropped
    out = MINORS[CARD_ID].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert all(CARD_ID not in r.effect_card_ids for r in fr)


# (The pre-correction module had an "n == 0 schedules the current round — a wasted but
# legal play" test here. Under the corrected post-payment prerequisite, n >= 1 on every
# reachable play: a payment leaving zero building resources is filtered by the gate, so
# the n == 0 case is unreachable and the test was removed with it.)


# ---------------------------------------------------------------------------
# Prerequisites — the occupation half (pre-play) + the per-payment gate
# ---------------------------------------------------------------------------

def test_prereq_requires_two_occupations():
    # The occupation-count half stays an ordinary pre-play check (min_occupations=2);
    # prereq_met no longer reads resources (the building-resource half is the
    # per-payment gate below).
    s = setup(0)
    assert not prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 1), 0)
    assert prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 2), 0)
    assert prereq_met(MINORS[CARD_ID], _give_occ_count(s, 0, 3), 0)  # >= 2


def _at_play_frame(occupations=("_occ0", "_occ1"), **res):
    """A state at a PendingPlayMinor with Grassland Harrow in player 0's hand, the
    given occupations played (2 fakes by default — the occupation prereq), and the
    given resources."""
    s = setup(0)
    p = fast_replace(s.players[0],
                     hand_minors=frozenset({CARD_ID}),
                     occupations=frozenset(occupations),
                     resources=Resources(**res))
    s = fast_replace(s, players=(p, s.players[1]), current_player=0)
    return with_pending_stack(s, (PendingPlayMinor(
        player_idx=0, initiated_by_id="space:meeting_place_cards"),))


def _play_commits(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


def test_exactly_cost_wood_not_playable():
    # Exactly 2 wood, nothing else: the pre-correction module wrongly allowed this
    # (>= 1 building resource BEFORE payment) — but paying the 2-wood cost leaves
    # zero building resources, so the corrected post-payment prerequisite fails and
    # the card is NOT playable.
    s = _at_play_frame(wood=2)
    assert CARD_ID not in playable_minors(s, 0)


def test_playable_with_one_building_resource_beyond_the_cost():
    # 2 wood + 1 clay: the 2-wood payment leaves the clay → playable, and only the
    # qualifying payment is offered.
    s = _at_play_frame(wood=2, clay=1)
    assert CARD_ID in playable_minors(s, 0)
    commits = _play_commits(s)
    assert [c.payment for c in commits] == [Resources(wood=2)]
    out = step(s, commits[0])
    p = out.players[0]
    assert CARD_ID in p.minor_improvements
    assert (p.resources.wood, p.resources.clay) == (0, 1)
    # n = 1 building resource post-payment → field on round 1 + 1 = 2 (slot 1).
    assert CARD_ID in p.future_rewards[1].effect_card_ids


def test_playable_with_three_wood():
    # 3 wood: pay 2, 1 remains → playable.
    s = _at_play_frame(wood=3)
    assert CARD_ID in playable_minors(s, 0)
    commits = _play_commits(s)
    assert [c.payment for c in commits] == [Resources(wood=2)]
    out = step(s, commits[0])
    p = out.players[0]
    assert p.resources.wood == 1
    assert CARD_ID in p.future_rewards[1].effect_card_ids      # n = 1 → round 2


def test_wood_expert_food_route_only_qualifying_payment_offered():
    # With Wood Expert (2 wood -> 1 food) and 2 wood + 1 grain + 0 food: the bare
    # 2-wood payment would leave zero building resources — filtered out — while the
    # 1-food payment (raised by cooking the grain) keeps both wood → playable ONLY
    # via the food route, and the gate's food-short probe / the frame agree.
    s = _at_play_frame(occupations=("wood_expert", "_occ1"), wood=2, grain=1)
    assert CARD_ID in playable_minors(s, 0)
    commits = _play_commits(s)
    assert [c.payment for c in commits] == [Resources(food=1)]
    s = step(s, commits[0])

    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1
    bundles = legal_actions(s)
    assert bundles == [CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0)]
    s = step(s, bundles[0])                                    # cook the grain

    p = s.players[0]
    assert CARD_ID in p.minor_improvements
    assert p.resources.wood == 2       # both wood survive
    assert (p.resources.grain, p.resources.food) == (0, 0)     # raised 1, debited 1
    # n = 2 building resources post-payment → field on round 1 + 2 = 3 (slot 2).
    assert CARD_ID in p.future_rewards[2].effect_card_ids


# ---------------------------------------------------------------------------
# Round-start optional plow (the deferred effect firing)
# ---------------------------------------------------------------------------

def _prep_with_scheduled(idx=0, prev_round=1):
    """A PREPARATION state where player `idx` owns Grassland Harrow with its plow
    scheduled for the round `_complete_preparation` is about to enter (prev_round+1)."""
    state = setup(0)
    entered = prev_round + 1
    p = state.players[idx]
    rewards = list(p.future_rewards)
    rewards[entered - 1] = FutureReward(effect_card_ids=frozenset({CARD_ID}))
    p = fast_replace(p,
                     minor_improvements=p.minor_improvements | {CARD_ID},
                     future_rewards=tuple(rewards))
    state = fast_replace(state,
                         players=tuple(p if i == idx else state.players[i] for i in range(2)),
                         round_number=prev_round, phase=Phase.PREPARATION)
    return state, entered


def test_offers_optional_plow_at_round_start():
    s, entered = _prep_with_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    assert s.round_number == entered
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "round_space_collection" and top.player_idx == 0
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la                            # optional → declinable
    s2 = step(s, FireTrigger(card_id=CARD_ID))
    assert isinstance(s2.pending_stack[-1], PendingPlow)
    # Grant consumed so it fires at most once.
    assert CARD_ID not in s2.players[0].future_rewards[entered - 1].effect_card_ids


def test_can_be_declined():
    s, _ = _prep_with_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    s = step(s, Proceed())
    assert all(not isinstance(f, PendingPlow) for f in s.pending_stack)
    # Declining resumes the ladder, which completes into WORK.
    assert s.pending_stack == ()
    assert s.phase == Phase.WORK


def test_not_offered_when_unplowable():
    # Scheduled but no plowable cell → the trigger is not eligible, so no window
    # frame is pushed at all: the ladder completes straight into WORK.
    s, _ = _prep_with_scheduled(idx=0, prev_round=1)
    s = _fill_grid_fields(s, 0)
    assert not _can_plow(s.players[0])
    s = _complete_preparation(s)
    assert s.pending_stack == ()
    assert s.phase == Phase.WORK


def test_owner_not_hosted_on_unscheduled_round():
    # Owning the card does NOT surface a window frame on rounds its plow isn't due
    # (eligibility is gated on the schedule, not card ownership).
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
    state = fast_replace(state, players=(p, state.players[1]),
                         round_number=3, phase=Phase.PREPARATION)
    out = _complete_preparation(state)
    assert out.pending_stack == ()                    # no frame pushed


def test_scoped_to_owner_only():
    # The opponent (no schedule) is not offered the plow on the entered round:
    # the only window frame belongs to player 0 (the owner).
    s, entered = _prep_with_scheduled(idx=0, prev_round=1)
    s = _complete_preparation(s)
    assert [f.player_idx for f in s.pending_stack
            if isinstance(f, PendingHarvestWindow)] == [0]
    for f in s.pending_stack:
        assert getattr(f, "player_idx", 0) == 0
