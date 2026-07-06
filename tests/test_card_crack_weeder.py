"""Tests for Crack Weeder (minor improvement, B58; Bubulcus Expansion).

Card text: "When you play this card, you immediately get 1 food. For each
vegetable you take from a field in the field phase of a harvest, you also get
1 food."

Two effects:
  - on-play +1 food (a minor `on_play`).
  - a per-occasion harvest AUTO (`register_harvest_occasion_auto`): +1 food per
    vegetable UNIT harvested in the FIELD PHASE (ruling 6, unit counting), scoped
    on `state.phase == Phase.HARVEST_FIELD` ("in the field phase of a harvest"
    scopes the window — so a card-granted extra veg harvest during the field phase
    counts too; a WORK-phase Bumper Crop take does not).

The harvest tests drive a real harvest through the walk (`_advance_until_decision`
over a `Phase.HARVEST_FIELD` state) so the occasion auto fires off the actual take
manifest, not a pre-take grid snapshot; the on-play test drives a real
PendingPlayMinor -> CommitPlayMinor engine flow.
"""
from __future__ import annotations

import agricola.cards.crack_weeder  # noqa: F401  (registers the card)

import pytest

from agricola.cards.harvest_windows import (
    HARVEST_OCCASION_AUTOS,
    apply_harvest_occasion_autos,
)
from agricola.cards.specs import MINORS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.pending import HarvestEntry, HarvestOccasion, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_grid, with_pending_stack, with_phase
from tests.test_utils import sole_play_minor

CARD_ID = "crack_weeder"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    """Put the (played) minor in player `idx`'s tableau."""
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10):
    """A HARVEST_FIELD-phase state with both players fed (feeding painless)."""
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        state = fast_replace(state, players=tuple(
            fast_replace(state.players[i],
                         resources=fast_replace(state.players[i].resources, food=food))
            if i == idx else state.players[i] for i in range(2)))
    return state


def _run_field_phase(state):
    """Advance from HARVEST_FIELD until the field phase completes. The three
    cards are occasion AUTOS (no choice frame), so the take runs inline inside
    `_advance_until_decision`, which lands at the HARVEST_FEED feeding decision
    with the field-phase income applied and feeding food NOT yet spent."""
    state = _advance_until_decision(state)
    assert state.phase in (Phase.HARVEST_FEED, Phase.HARVEST_BREED,
                           Phase.PREPARATION, Phase.WORK), state.phase
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_crack_weeder_registered():
    assert CARD_ID in MINORS
    assert any(e.card_id == CARD_ID for e in HARVEST_OCCASION_AUTOS)
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.prereq is None
    assert spec.passing_left is False
    assert spec.vps == 0


# ---------------------------------------------------------------------------
# On-play: immediate +1 food (driven through a real play-minor engine flow)
# ---------------------------------------------------------------------------

def test_on_play_gives_one_food_via_engine():
    pool = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)))
    cs, _env = setup_env(5, card_pool=pool)
    cp = cs.current_player
    # Give the active player the card in hand + the 1 wood it costs.
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     resources=Resources(wood=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp,
                              initiated_by_id="space:meeting_place_cards"),))

    f0 = cs.players[cp].resources.food
    w0 = cs.players[cp].resources.wood
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    after = cs.players[cp]
    assert after.resources.food == f0 + 1          # immediate +1 food
    assert after.resources.wood == w0 - 1          # 1 wood cost paid
    assert CARD_ID in after.minor_improvements     # kept in tableau (not passing)


def test_on_play_spec_fn_directly():
    state = setup(0)
    f0 = state.players[0].resources.food
    after = MINORS[CARD_ID].on_play(state, 0)
    assert after.players[0].resources.food == f0 + 1


# ---------------------------------------------------------------------------
# Field-phase income (the core effect) — driven through a real harvest walk
# ---------------------------------------------------------------------------

def test_single_veg_field_gives_one_food():
    """A veg-sown field yields +1 food (and the mechanical take removes 1 veg)."""
    state = _own_minor(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    f0 = state.players[0].resources.food
    v0 = state.players[0].resources.veg
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 1     # +1 food bonus
    assert after.players[0].resources.veg == v0 + 1      # mechanical take of the veg
    assert after.players[0].farmyard.grid[0][0].veg == 0


def test_multi_veg_field_still_only_one_food():
    """A 2-veg field yields only ONE vegetable per harvest -> +1 food (not +2),
    and the field is depleted by exactly 1 (the take removes one crop per field)."""
    state = _own_minor(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=2)})
    f0 = state.players[0].resources.food
    v0 = state.players[0].resources.veg
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 1     # one vegetable -> +1 food
    assert after.players[0].resources.veg == v0 + 1      # only 1 veg taken
    assert after.players[0].farmyard.grid[0][0].veg == 1  # 2 -> 1, not 2 -> 0


def test_multiple_veg_fields_sum():
    """Three veg-sown fields, one veg unit each in the take -> +3 food (unit
    counting over the take manifest's veg entries)."""
    state = _own_minor(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, veg=1),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),
        (1, 0): Cell(cell_type=CellType.FIELD, veg=1),
    })
    f0 = state.players[0].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 3


# ---------------------------------------------------------------------------
# Unit counting on the occasion manifest (direct)
# ---------------------------------------------------------------------------

def _field_phase(state):
    return fast_replace(state, phase=Phase.HARVEST_FIELD)


def test_unit_counts_multiple_veg_entries_in_one_occasion():
    """A single take occasion carrying THREE veg entries pays +3 (ruling 6: units
    within an occasion), while grain entries pay nothing."""
    state = _field_phase(_own_minor(setup(0), 0, CARD_ID))
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:0,0", crop="veg", amount=1, emptied=True),
        HarvestEntry(source="cell:0,1", crop="veg", amount=1, emptied=False),
        HarvestEntry(source="cell:1,0", crop="veg", amount=1, emptied=True),
        HarvestEntry(source="cell:1,1", crop="grain", amount=1, emptied=False),
    ))
    f0 = state.players[0].resources.food
    after, _fired = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.food == f0 + 3


def test_card_granted_field_phase_occasion_earns_food():
    """"in the field phase of a harvest" scopes the window, not the take: a
    card-granted extra veg harvest DURING the field phase (Stable Manure) is still
    "a vegetable you take from a field in the field phase" -> it counts."""
    state = _field_phase(_own_minor(setup(0), 0, CARD_ID))
    occ = HarvestOccasion(source="card:stable_manure", entries=(
        HarvestEntry(source="cell:0,0", crop="veg", amount=2, emptied=False),
    ))
    f0 = state.players[0].resources.food
    after, _fired = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.food == f0 + 2


def test_occasion_outside_field_phase_earns_nothing():
    """The phase gate models user ruling 4: a Bumper Crop take fires the field-phase
    EFFECT during WORK, not the field phase, so Crack Weeder earns nothing there."""
    state = _own_minor(setup(0), 0, CARD_ID)   # setup() is Phase.WORK
    occ = HarvestOccasion(source="take", entries=(
        HarvestEntry(source="cell:0,0", crop="veg", amount=1, emptied=True),
    ))
    f0 = state.players[0].resources.food
    after, _fired = apply_harvest_occasion_autos(state, 0, occ)
    assert after.players[0].resources.food == f0     # not the field phase -> nothing


# ---------------------------------------------------------------------------
# End-to-end interaction: Stable Manure's extra veg counts (through the walk)
# ---------------------------------------------------------------------------

def test_stable_manure_extra_veg_counts_end_to_end():
    """Owning Crack Weeder AND Stable Manure, a 2-veg field yielding BOTH veg in
    the one take event (base + Stable Manure's folded-in extra — user ruling 11)
    pays Crack Weeder for both, through the real walk: the manifest's veg amount
    is 2 and the unit counter reads it. (The original source=="take" gate paired
    with the separate-occasion model paid only the base veg — the fidelity bug
    this test guards.)"""
    from agricola.actions import CommitFieldTake, Proceed
    from agricola.legality import legal_actions
    from agricola.pending import PendingFieldPhase
    state = _own_minor(_own_minor(_harvest_state(), 0, CARD_ID), 0, "stable_manure")
    # A 2-veg field + one unfenced stable → Stable Manure may fold in 1 extra veg.
    state = with_grid(state, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, veg=2),
        (0, 4): Cell(cell_type=CellType.STABLE),
    })
    f0, v0 = state.players[0].resources.food, state.players[0].resources.veg

    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    # Commit the take WITH Stable Manure's extra folded in (the sole veg variant).
    take = next(a for a in legal_actions(state)
                if isinstance(a, CommitFieldTake) and a.modifiers)
    assert take.modifiers == (("stable_manure", "veg2:1"),)
    state = step(state, take)
    state = step(state, Proceed())
    state = _advance_until_decision(state)

    # Both veg reached the supply in the one event, and Crack Weeder paid for each.
    assert state.players[0].resources.veg == v0 + 2
    assert state.players[0].resources.food == f0 + 2


# ---------------------------------------------------------------------------
# Eligibility boundaries — only vegetable takes earn food
# ---------------------------------------------------------------------------

def test_grain_field_gives_no_food():
    """A grain-sown field has its grain (not a vegetable) taken -> no food."""
    state = _own_minor(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3)})
    f0 = state.players[0].resources.food
    g0 = state.players[0].resources.grain
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0          # no food bonus
    assert after.players[0].resources.grain == g0 + 1     # mechanical grain take


def test_empty_or_unsown_field_gives_no_food():
    state = _own_minor(_harvest_state(), 0, CARD_ID)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD)})  # empty
    f0 = state.players[0].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0


def test_no_fields_at_all_gives_no_food():
    state = _own_minor(_harvest_state(), 0, CARD_ID)
    f0 = state.players[0].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0


# ---------------------------------------------------------------------------
# Owner-gating — fires only for the player who owns it
# ---------------------------------------------------------------------------

def test_fires_only_for_owner():
    state = _own_minor(_harvest_state(), 0, CARD_ID)   # P0 owns, P1 does not
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    state = with_grid(state, 1, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    f0, f1 = state.players[0].resources.food, state.players[1].resources.food
    after = _run_field_phase(state)
    assert after.players[0].resources.food == f0 + 1   # owner gets the bonus
    assert after.players[1].resources.food == f1       # non-owner unchanged


# ---------------------------------------------------------------------------
# Family byte-identity — no income without the card
# ---------------------------------------------------------------------------

def test_no_income_without_card():
    state = _harvest_state(seed=3)
    state = with_grid(state, 0, {(0, 0): Cell(cell_type=CellType.FIELD, veg=1)})
    f0 = state.players[0].resources.food
    after = _run_field_phase(state)
    # Mechanical take only; no Crack Weeder food.
    assert after.players[0].resources.food == f0


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
