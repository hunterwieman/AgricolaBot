"""Tests for Plowman (occupation, D91).

Card text: "Add 4, 7, and 10 to the current round and place a field tile on each
corresponding round space. At the start of these rounds, you can plow the field for
1 food."

Plowman fuses Handplow's deferred-plow SCHEDULE (the three due rounds ride on
`future_rewards`, and consuming the round's slot is the once-per-round guard) with Plow
Driver's pay-1-food-to-plow body (the 1 food flows through the shared food-payment
path; eligibility is liquidation-aware). Verified here: registration, the on-play
schedule (R+4/7/10, with rounds > 14 dropped), the optional FireTrigger at the
preparation ladder's round_space_collection (collection) window frame (a PendingHarvestWindow, ruling
53, 2026-07-14) with Proceed as the decline, the 1-food debit + plow, eligibility
boundaries (unplowable / unaffordable / unscheduled round — an ineligible trigger
gets NO frame at all), the liquidation path when food is short, and that firing
consumes the slot so it never re-qualifies.
"""
import agricola.cards.plowman  # noqa: F401

from agricola.actions import CommitFoodPayment, FireTrigger, Proceed
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import _can_plow, legal_actions
from agricola.pending import PendingFoodPayment, PendingHarvestWindow, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import Cell, FutureReward


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _give(state, idx, resources):
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + resources)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_resources(state, idx, resources):
    p = state.players[idx]
    p = fast_replace(p, resources=resources)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _fill_grid_fields(state, idx):
    """Fill every non-room cell with FIELD so no plowable (empty) cell remains."""
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


def _prep_with_plowman_scheduled(idx=0, prev_round=1):
    """A PREPARATION state where player `idx` owns Plowman with its plow scheduled for
    the round `_complete_preparation` is about to enter (prev_round + 1)."""
    state = setup(0)
    entered = prev_round + 1
    p = state.players[idx]
    rewards = list(p.future_rewards)
    rewards[entered - 1] = FutureReward(effect_card_ids=frozenset({"plowman"}))
    p = fast_replace(p,
                     occupations=p.occupations | {"plowman"},
                     future_rewards=tuple(rewards))
    state = fast_replace(
        state,
        players=tuple(p if i == idx else state.players[i] for i in range(2)),
        round_number=prev_round, phase=Phase.PREPARATION)
    return state, entered


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_plowman_registered():
    assert "plowman" in OCCUPATIONS
    # A bare on-play occupation (occupations carry no printed cost in this engine).
    assert OCCUPATIONS["plowman"].card_id == "plowman"
    # The deferred plow is an OPTIONAL round_space_collection trigger (not a forced auto).
    assert "plowman" in {e.card_id for e in TRIGGERS.get("round_space_collection", [])}
    # The 1-food price flows through the shared food-payment resume registry.
    assert "plowman" in FOOD_PAYMENT_RESUMES


# ---------------------------------------------------------------------------
# On-play schedule
# ---------------------------------------------------------------------------

def test_on_play_schedules_three_rounds():
    s = setup(0)   # R = 1 → due rounds 5, 8, 11 (slots 4, 7, 10)
    out = OCCUPATIONS["plowman"].on_play(s, 0)
    fr = out.players[0].future_rewards
    for due in (5, 8, 11):
        assert "plowman" in fr[due - 1].effect_card_ids
    assert sum(1 for r in fr if "plowman" in r.effect_card_ids) == 3
    # No goods scheduled — Plowman schedules an EFFECT, not resources.
    assert all(r.food == 0 for r in out.players[0].future_resources)


def test_on_play_drops_rounds_past_14():
    # Played late: R = 8 → due rounds 12, 15, 18; only round 12 survives the 14-round game.
    s = fast_replace(setup(0), round_number=8)
    out = OCCUPATIONS["plowman"].on_play(s, 0)
    fr = out.players[0].future_rewards
    assert "plowman" in fr[12 - 1].effect_card_ids
    assert sum(1 for r in fr if "plowman" in r.effect_card_ids) == 1


# ---------------------------------------------------------------------------
# The optional plow at round start
# ---------------------------------------------------------------------------

def test_offers_optional_plow_and_debits_food():
    # The scheduled round is entered → the round_space_collection (collection) window pushes a choice
    # frame surfacing the plow as an OPTIONAL FireTrigger alongside Proceed (the
    # decline). Firing debits 1 food, pushes the plow, and consumes the slot.
    s, entered = _prep_with_plowman_scheduled(idx=0, prev_round=1)
    s = _give(s, 0, Resources(food=2))
    s = _complete_preparation(s)
    assert s.round_number == entered
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.player_idx == 0
    assert top.window_id == "round_space_collection"
    assert s.phase is Phase.PREPARATION   # the ladder is paused at the window
    la = legal_actions(s)
    assert FireTrigger(card_id="plowman") in la
    assert Proceed() in la                       # optional → declinable
    before = s.players[0].resources.food
    s2 = step(s, FireTrigger(card_id="plowman"))
    assert isinstance(s2.pending_stack[-1], PendingPlow)
    assert s2.players[0].resources.food == before - 1
    # The slot is consumed → cannot re-qualify.
    assert "plowman" not in s2.players[0].future_rewards[entered - 1].effect_card_ids


def test_can_be_declined():
    # Proceed declines the plow — no PendingPlow is pushed, no food spent.
    s, _ = _prep_with_plowman_scheduled(idx=0, prev_round=1)
    s = _give(s, 0, Resources(food=2))
    s = _complete_preparation(s)
    before = s.players[0].resources.food
    s = step(s, Proceed())
    assert all(not isinstance(f, PendingPlow) for f in s.pending_stack)
    assert s.players[0].resources.food == before


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_when_unplowable():
    # Scheduled + food on hand, but the farm has no plowable cell → Plowman is not
    # eligible, so NO window frame is pushed (frames appear exactly when a trigger
    # is eligible) and the ladder runs straight through to WORK.
    s, _ = _prep_with_plowman_scheduled(idx=0, prev_round=1)
    s = _give(s, 0, Resources(food=2))
    s = _fill_grid_fields(s, 0)
    assert not _can_plow(s.players[0])
    s = _complete_preparation(s)
    assert s.pending_stack == ()
    assert s.phase is Phase.WORK
    assert FireTrigger(card_id="plowman") not in legal_actions(s)


def test_not_offered_when_food_short_and_no_fuel():
    # 0 food, nothing convertible → truly unaffordable → not offered (regression
    # guard): no frame, straight to WORK.
    s, _ = _prep_with_plowman_scheduled(idx=0, prev_round=1)
    s = _set_resources(s, 0, Resources())   # 0 food, no liquidatable goods
    s = _complete_preparation(s)
    assert s.pending_stack == ()
    assert s.phase is Phase.WORK
    assert FireTrigger(card_id="plowman") not in legal_actions(s)


def test_owner_not_hosted_on_unscheduled_round():
    # Owning Plowman does NOT produce a window frame on rounds its plow isn't due
    # (eligibility is gated on the schedule slot, not card ownership).
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, occupations=p.occupations | {"plowman"})
    state = fast_replace(state, players=(p, state.players[1]),
                         round_number=3, phase=Phase.PREPARATION)
    out = _complete_preparation(state)
    assert out.pending_stack == ()   # no frame pushed
    assert out.phase is Phase.WORK


# ---------------------------------------------------------------------------
# The food-payment (liquidation) path
# ---------------------------------------------------------------------------

def test_fires_via_liquidation_when_food_short():
    # 0 food but 1 grain: Plowman must still be offered (the 1 food is liquidatable);
    # firing pushes a raise-only PendingFoodPayment, and paying it raises the food + plows.
    s, entered = _prep_with_plowman_scheduled(idx=0, prev_round=1)
    s = _set_resources(s, 0, Resources(grain=1))   # 0 food, 1 grain
    s = _complete_preparation(s)
    assert FireTrigger(card_id="plowman") in legal_actions(s)

    s = step(s, FireTrigger(card_id="plowman"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment) and top.food_needed == 1
    # The slot was already consumed in the guard — no re-qualifying during the raise.
    assert "plowman" not in s.players[0].future_rewards[entered - 1].effect_card_ids

    s = step(s, CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0))
    assert isinstance(s.pending_stack[-1], PendingPlow)   # resume debited the food + plowed
    assert s.players[0].resources.food == 0               # raised 1, paid 1
    assert s.players[0].resources.grain == 0
