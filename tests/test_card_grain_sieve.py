"""Tests for Grain Sieve (minor improvement, D65; Dulcinaria).

Card text: "In the field phase of each harvest, if you harvest at least 2 grain,
you get 1 additional grain from the general supply."

Grain Sieve is a per-occasion consequence: it reads the field-phase TAKE
occasion's manifest and grants +1 grain when that take removed >= 2 grain.

Governing user ruling 9 (2026-07-03): a take-once card fires once, with the take
occasion, and keys off the specifics of what that action took. So Grain Sieve
gates on `occasion.source == "take"` and counts the grain in that occasion's
entries — never a separate card-granted additional-harvest occasion.

The take emits one grain entry (amount 1) per grain-bearing field, so:
  - one field (however many grain sown) harvests 1 grain -> NO bonus,
  - two grain fields harvest 2 grain                     -> +1 bonus grain.
"""
from __future__ import annotations

import agricola.cards.grain_sieve  # noqa: F401  (registers the card)

from agricola.cards.harvest_windows import (
    HARVEST_OCCASION_AUTOS,
    apply_harvest_occasion_autos,
)
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision
from agricola.pending import HarvestEntry, HarvestOccasion
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from agricola.state import GameState

from tests.factories import with_phase, with_sown_fields


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id="grain_sieve"):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state, everyone fed (so feeding is painless)."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        p = state.players[idx]
        p = fast_replace(p, resources=fast_replace(p.resources, food=food))
        state = fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))
    return state


def _run_harvest(state):
    """Drive the harvest field-phase (into feeding) via the real walk."""
    return _advance_until_decision(state)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_grain_sieve_registered():
    assert "grain_sieve" in MINORS
    assert "grain_sieve" not in OCCUPATIONS
    # It registered a per-occasion auto (not the legacy harvest_field hook).
    assert any(e.card_id == "grain_sieve" for e in HARVEST_OCCASION_AUTOS)


def test_cost_is_one_wood():
    spec = MINORS["grain_sieve"]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.prereq is None
    assert spec.passing_left is False
    assert spec.vps == 0
    assert spec.min_occupations == 0


def test_on_play_is_noop():
    state = setup(0)
    before = state.players[0].resources
    after = MINORS["grain_sieve"].on_play(state, 0)
    assert after.players[0].resources == before
    assert after == state


# ---------------------------------------------------------------------------
# Eligibility boundary, driven through a real harvest (the take occasion)
# ---------------------------------------------------------------------------

def test_two_grain_fields_grants_bonus():
    # Two grain fields -> take removes 2 grain -> +1 bonus.
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             grain_fields=[(0, 0), (0, 1)])
    g0 = state.players[0].resources.grain
    after = _run_harvest(state)
    assert after.phase == Phase.HARVEST_FEED
    # +2 from the take (1 per field) +1 bonus = +3.
    assert after.players[0].resources.grain == g0 + 3


def test_one_grain_field_no_bonus():
    # A single grain field harvests only 1 grain -> below threshold, no bonus.
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             grain_fields=[(0, 0)])
    g0 = state.players[0].resources.grain
    after = _run_harvest(state)
    assert after.players[0].resources.grain == g0 + 1   # take only, no bonus


def test_single_field_with_three_grain_no_bonus():
    # The crux: ONE field (sown to 3 grain) harvests only 1 grain this phase,
    # so the take occasion holds a single grain entry (amount 1) -> no bonus.
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             grain_fields=[(0, 0)])
    g0 = state.players[0].resources.grain
    after = _run_harvest(state)
    assert after.players[0].resources.grain == g0 + 1   # take only
    # The 3-grain field dropped to 2 (only 1 taken this phase).
    assert after.players[0].farmyard.grid[0][0].grain == 2


def test_three_grain_fields_still_only_one_bonus():
    # Threshold is "at least 2"; the bonus is a flat +1 regardless of how many.
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             grain_fields=[(0, 0), (0, 1), (0, 2)])
    g0 = state.players[0].resources.grain
    after = _run_harvest(state)
    # +3 from the take, +1 (not +3) bonus.
    assert after.players[0].resources.grain == g0 + 4


def test_no_grain_fields_no_bonus():
    state = _own_minor(_harvest_state(), 0)  # no fields
    g0 = state.players[0].resources.grain
    after = _run_harvest(state)
    assert after.players[0].resources.grain == g0


def test_veg_fields_do_not_count():
    # Two veg fields harvest veg, not grain, so the grain threshold isn't reached.
    state = with_sown_fields(_own_minor(_harvest_state(), 0), 0,
                             veg_fields=[(0, 0), (0, 1)])
    g0 = state.players[0].resources.grain
    v0 = state.players[0].resources.veg
    after = _run_harvest(state)
    assert after.players[0].resources.grain == g0   # no grain bonus
    assert after.players[0].resources.veg == v0 + 2  # veg still harvested


# ---------------------------------------------------------------------------
# Owner-gating: fires only for the owner
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    # P0 owns the sieve and has 2 grain fields; P1 also has 2 grain fields but
    # no card -> only P0 gets the bonus.
    state = _own_minor(_harvest_state(), 0)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0), (0, 1)])
    state = with_sown_fields(state, 1, grain_fields=[(0, 0), (0, 1)])
    g0 = state.players[0].resources.grain
    g1 = state.players[1].resources.grain
    after = _run_harvest(state)
    assert after.players[0].resources.grain == g0 + 3   # take(2) + bonus(1)
    assert after.players[1].resources.grain == g1 + 2   # take only, no bonus


def test_both_owners_each_get_their_own_bonus():
    # Both own the card; each is judged on their own take occasion.
    state = _own_minor(_own_minor(_harvest_state(), 0), 1)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])                 # 1 grain
    state = with_sown_fields(state, 1, grain_fields=[(0, 0), (0, 1)])        # 2 grain
    g0 = state.players[0].resources.grain
    g1 = state.players[1].resources.grain
    after = _run_harvest(state)
    assert after.players[0].resources.grain == g0 + 1   # take only, below threshold
    assert after.players[1].resources.grain == g1 + 3   # take + bonus


# ---------------------------------------------------------------------------
# Ruling 9: fires ONLY on the take occasion, not a card-granted extra harvest
# ---------------------------------------------------------------------------

def test_does_not_fire_on_non_take_occasion():
    # A SEPARATE harvesting occasion (source != "take") that removes 3 grain must
    # NOT trigger Grain Sieve — it reads the take (ruling 9). Under ruling 11
    # (2026-07-05) no during-phase card creates such an occasion any more (their
    # extras fold INTO the take and DO count — see the fold-in tests below); a
    # non-take occasion now means an out-of-phase event (a future Bumper-Crop
    # played field phase), which "in the field phase of each harvest" excludes.
    state = _own_minor(setup(0), 0)
    g0 = state.players[0].resources.grain
    occ = HarvestOccasion(
        source="card:some_extra_harvest",
        entries=(
            HarvestEntry(source="cell:0,0", crop="grain", amount=1, emptied=False),
            HarvestEntry(source="cell:0,1", crop="grain", amount=1, emptied=False),
            HarvestEntry(source="cell:0,2", crop="grain", amount=1, emptied=False),
        ),
    )
    after = apply_harvest_occasion_autos(state, 0, occ)
    assert isinstance(after, GameState)
    assert after.players[0].resources.grain == g0   # no bonus off a non-take occasion


def test_fires_on_a_hand_built_take_occasion():
    # Sanity mirror of the negative test: the same >=2-grain manifest DOES grant
    # the bonus when its source is the field-phase take.
    state = _own_minor(setup(0), 0)
    g0 = state.players[0].resources.grain
    occ = HarvestOccasion(
        source="take",
        entries=(
            HarvestEntry(source="cell:0,0", crop="grain", amount=1, emptied=False),
            HarvestEntry(source="cell:0,1", crop="grain", amount=1, emptied=False),
        ),
    )
    after = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.grain == g0 + 1


# ---------------------------------------------------------------------------
# Ruling 11 (2026-07-05): take-modifier extras are IN the take — and count
# ---------------------------------------------------------------------------

def test_scythe_worker_extra_counts_toward_threshold():
    """One 2-grain field alone yields 1 grain (no bonus) — but with Scythe
    Worker, its folded-in extra makes the one take event yield 2, meeting the
    threshold. Grain Sieve treats Scythe Worker's extras as part of the take
    (ruling 11), end-to-end through the walk: +2 taken +1 bonus = +3."""
    state = _own_minor(_harvest_state(), 0)
    p = state.players[0]
    state = fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {"scythe_worker"})
        if i == 0 else state.players[i] for i in range(2)))
    from tests.factories import with_grid
    from agricola.state import Cell
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2)})
    g0 = state.players[0].resources.grain
    after = _run_harvest(state)
    assert after.players[0].resources.grain == g0 + 3
    assert after.players[0].farmyard.grid[0][0].grain == 0


def test_stable_manure_extra_counts_toward_threshold():
    """Same shape via the CHOICE-bearing modifier: one 2-grain field + Stable
    Manure's folded-in extra = a 2-grain take event -> the bonus fires (ruling
    11 explicitly: Grain Sieve treats Stable Manure exactly as Scythe Worker)."""
    from agricola.actions import CommitFieldTake, Proceed
    from agricola.engine import step
    from agricola.legality import legal_actions
    from agricola.pending import PendingFieldPhase
    from agricola.state import Cell
    from tests.factories import with_grid
    state = _own_minor(_own_minor(_harvest_state(), 0), 0, "stable_manure")
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=2),
        (0, 4): Cell(cell_type=CellType.STABLE),
    })
    g0 = state.players[0].resources.grain
    state = _advance_until_decision(state)
    assert isinstance(state.pending_stack[-1], PendingFieldPhase)
    take = next(a for a in legal_actions(state)
                if isinstance(a, CommitFieldTake) and a.modifiers)
    assert take.modifiers == (("stable_manure", "grain2:1"),)
    state = step(state, take)
    # +2 taken (base + extra, one event) +1 Grain Sieve bonus.
    assert state.players[0].resources.grain == g0 + 3
    state = step(state, Proceed())
    after = _advance_until_decision(state)
    assert after.phase == Phase.HARVEST_FEED
