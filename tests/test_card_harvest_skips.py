"""Tests for the harvest-skip cards and the skip machinery.

- Lunchtime Beer (minor, E58): "At the start of each harvest, you can choose to
  skip the field and breeding phase of that harvest and get exactly 1 food
  instead." Optional; skips BOTH phases with their boundaries (ruling 1);
  feeding and the harvest's outer instants still run.
- Layabout (occupation, C108): "When you play this card, you must skip the next
  harvest. (You also do not have to feed your family that harvest.)"
  Automatic; the cancellation is TOTAL per ruling 14 (2026-07-05): every
  harvest-relative instant including the outer boundaries, feeding, breeding.

Also covers the feeding-income seam (`register_auto("feeding", …)`): income
fires at FEED entry, before the payment decision, so the food is payable.
"""
from __future__ import annotations

import agricola.cards.layabout  # noqa: F401
import agricola.cards.lunchtime_beer  # noqa: F401

from agricola.actions import FireTrigger, Proceed
from agricola.cards.harvest_windows import HARVEST_SKIP_CARDS
from agricola.cards.triggers import register_auto
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingHarvestBreed,
    PendingHarvestFeed,
    PendingHarvestWindow,
)
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import setup
from agricola.state import GameState

from tests.factories import with_phase, with_round, with_sown_fields

LB = "lunchtime_beer"
LA = "layabout"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx, card_id, *, minor=False):
    p = state.players[idx]
    if minor:
        return _edit_player(state, idx,
                            minor_improvements=p.minor_improvements | {card_id})
    return _edit_player(state, idx, occupations=p.occupations | {card_id})


def _harvest_state(seed=0, food=10):
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = _edit_player(state, idx, resources=fast_replace(
            state.players[idx].resources, food=food))
    return state


def _run_harvest(state, pick=lambda acts: acts[0]):
    """Drive the whole harvest into PREPARATION, picking `pick` at each stop."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        state = step(state, pick(legal_actions(state)))
    return state


def _fire_lb_then_default(acts):
    """Pick Lunchtime Beer's skip when offered, else the first action."""
    for a in acts:
        if isinstance(a, FireTrigger) and a.card_id == LB:
            return a
    return acts[0]


# A fake feeding-income card: +2 food at the FEED entry (ownership-gated, so it
# is inert everywhere else in the suite).
FEED_INCOME = "_test_feed_income"
register_auto("feeding", FEED_INCOME, lambda s, i: True,
              lambda s, i: fast_replace(s, players=tuple(
                  fast_replace(p, resources=p.resources + Resources(food=2))
                  if j == i else p
                  for j, p in enumerate(s.players))))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_skip_cards_registered():
    assert LB in HARVEST_SKIP_CARDS and LA in HARVEST_SKIP_CARDS


# ---------------------------------------------------------------------------
# Lunchtime Beer
# ---------------------------------------------------------------------------

def test_lb_skip_no_take_no_breed_but_still_feeds():
    state = _own(_harvest_state(), 0, LB, minor=True)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = _edit_player(state, 0, animals=Animals(sheep=2))
    # Give the farm room so the sheep COULD breed if the phase ran.
    f0 = state.players[0].resources.food
    saw_feed = []

    def pick(acts):
        top_types = {type(f).__name__ for f in []}
        for a in acts:
            if isinstance(a, FireTrigger) and a.card_id == LB:
                return a
        return acts[0]

    state2 = _advance_until_decision(state)
    fed_frames = 0
    breed_frames = 0
    while state2.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                           Phase.HARVEST_BREED):
        top = state2.pending_stack[-1] if state2.pending_stack else None
        if isinstance(top, PendingHarvestFeed) and top.player_idx == 0:
            fed_frames += 1
        if isinstance(top, PendingHarvestBreed) and top.player_idx == 0:
            breed_frames += 1
        state2 = step(state2, pick(legal_actions(state2)))

    assert state2.players[0].farmyard.grid[0][0].grain == 3   # NO take
    assert fed_frames >= 1                                    # still fed
    assert breed_frames == 0                                  # no breeding frame
    assert state2.players[0].animals.sheep == 2               # no newborn
    # +1 food from the card; feeding then cost 4 (2 adults).
    assert state2.players[0].resources.food == f0 + 1 - 4


def test_lb_decline_is_a_normal_harvest():
    state = _own(_harvest_state(), 0, LB, minor=True)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])

    def decline(acts):
        # Prefer Proceed (decline the skip choice); else the first action.
        for a in acts:
            if isinstance(a, Proceed):
                return a
        return acts[0]

    after = _run_harvest(state, decline)
    assert after.players[0].farmyard.grid[0][0].grain == 2    # take happened


def test_lb_field_phase_cards_do_not_fire_for_skipper():
    """Ruling 1: a skipped phase has no boundaries — the skipper's own
    field-phase card (Land Surveyor: food by field count IN the field phase)
    stays silent; the opponent is untouched."""
    state = _own(_own(_harvest_state(), 0, LB, minor=True), 0, "land_surveyor")
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    f0 = state.players[0].resources.food
    after = _run_harvest(state, _fire_lb_then_default)
    # +1 (Lunchtime Beer) − 4 (feeding, 2 adults); Land Surveyor's +1 (2 fields)
    # did NOT fire.
    assert after.players[0].resources.food == f0 + 1 - 4


def test_lb_outer_windows_still_fire():
    """The harvest's own instants are not part of the skipped phases: Raised
    Bed's start-of-harvest +4 food still pays a skipping player."""
    state = _own(_own(_harvest_state(), 0, LB, minor=True), 0, "raised_bed",
                 minor=True)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    f0 = state.players[0].resources.food
    after = _run_harvest(state, _fire_lb_then_default)
    # +4 (Raised Bed) +1 (Lunchtime Beer) − 4 (feeding).
    assert after.players[0].resources.food == f0 + 4 + 1 - 4


def test_lb_rearms_next_harvest():
    """The latch stores the round, so a declined/spent skip re-offers at the
    NEXT harvest."""
    state = _own(_harvest_state(), 0, LB, minor=True)
    after = _run_harvest(state, _fire_lb_then_default)   # skipped round-1 harvest
    assert after.phase == Phase.PREPARATION
    # A later harvest offers the choice again (fresh round, stale latch).
    # Clear the post-harvest reveal frame before forcing the new phase.
    from tests.factories import with_pending_stack
    again = with_pending_stack(after, [])
    again = with_phase(with_round(again, 7), Phase.HARVEST_FIELD)
    again = _advance_until_decision(again)
    offered = any(isinstance(a, FireTrigger) and a.card_id == LB
                  for a in legal_actions(again))
    assert offered


def test_lb_opponent_unaffected():
    state = _own(_harvest_state(), 0, LB, minor=True)
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)])
    after = _run_harvest(state, _fire_lb_then_default)
    assert after.players[1].farmyard.grid[0][0].grain == 2    # their take ran


# ---------------------------------------------------------------------------
# Layabout
# ---------------------------------------------------------------------------

def test_layabout_on_play_latches_next_harvest():
    from agricola.cards.specs import OCCUPATIONS
    state = with_round(setup(0), 5)                    # next harvest: round 7
    after = OCCUPATIONS[LA].on_play(state, 0)
    assert after.players[0].card_state.get("layabout_skip_round") == 7


def test_layabout_total_cancellation():
    """Ruling 14: during the skipped harvest NOTHING harvest-relative happens
    for the skipper — no windows (outer included: Raised Bed at the start,
    Winter Caretaker's end-of-harvest buy), no take, no feeding (no cost, no
    begging even at 0 food), no breeding."""
    state = _harvest_state(food=0)                     # 0 food: begging bait
    state = _own(state, 0, LA)
    state = _own(state, 0, "raised_bed", minor=True)
    state = _own(state, 0, "winter_caretaker")
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = _edit_player(state, 0, animals=Animals(sheep=2),
                         card_state=state.players[0].card_state.set(
                             "layabout_skip_round", state.round_number))
    # Opponent needs food to feed painlessly.
    state = _edit_player(state, 1, resources=fast_replace(
        state.players[1].resources, food=10))

    after = _run_harvest(state)
    p0 = after.players[0]
    assert p0.farmyard.grid[0][0].grain == 3           # no take
    assert p0.resources.food == 0                      # no Raised Bed, no feeding cost
    assert p0.begging_markers == 0                     # exempt, not begging
    assert p0.animals.sheep == 2                       # no breeding
    assert after.phase == Phase.PREPARATION


def test_layabout_next_harvest_is_normal():
    state = _harvest_state()
    state = _own(state, 0, LA)
    state = _edit_player(state, 0, card_state=state.players[0].card_state.set(
        "layabout_skip_round", 1))                     # skipped round 1's harvest
    state = with_round(state, 7)                       # ...but this is round 7's
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    after = _run_harvest(state)
    assert after.players[0].farmyard.grid[0][0].grain == 2   # take ran normally


# ---------------------------------------------------------------------------
# The feeding-income seam
# ---------------------------------------------------------------------------

def test_feeding_income_arrives_before_payment():
    """A card paying food "in the feeding phase" delivers BEFORE the payment
    decision: a player with 2 food + the fake +2 income feeds 2 adults (4 food)
    with no begging."""
    state = _own(_harvest_state(food=2), 0, FEED_INCOME)
    state = _edit_player(state, 1, resources=fast_replace(
        state.players[1].resources, food=10))
    after = _run_harvest(state)
    assert after.players[0].resources.food == 0        # 2 + 2 − 4
    assert after.players[0].begging_markers == 0


def test_feeding_income_not_paid_to_a_layabout_skipper():
    """A whole-harvest skipper does not feed — and gets no feeding income."""
    state = _own(_own(_harvest_state(food=0), 0, FEED_INCOME), 0, LA)
    state = _edit_player(state, 0, card_state=state.players[0].card_state.set(
        "layabout_skip_round", state.round_number))
    state = _edit_player(state, 1, resources=fast_replace(
        state.players[1].resources, food=10))
    after = _run_harvest(state)
    assert after.players[0].resources.food == 0        # no income, no cost
