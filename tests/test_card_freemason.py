"""Tests for Freemason (occupation, C123; Consul Dirigens Expansion).

Card text: "As long as you live in a clay/stone house with exactly 2 rooms, at the
start of each work phase, you get 2 clay/stone."

A choice-free automatic effect on the preparation ladder's `start_of_work`
window (ruling 54, 2026-07-14 — "at the start of each work phase" is the
ladder's last rung, after replenishment), fired mechanically with no frame.
Material-conditioned: a CLAY house grants +2 clay, a STONE house grants +2
stone, a WOOD house nothing. Income is driven through the real
`_complete_preparation` round-boundary transition, mirroring
tests/test_card_pavior.py / tests/test_cards_category7.py.
"""
from __future__ import annotations

import agricola.cards.freemason  # noqa: F401  (registers the card)

from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import CellType, HouseMaterial, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup, setup_env
from agricola.state import Cell

CARD_ID = "freemason"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_house(state, idx, material):
    p = state.players[idx]
    p = fast_replace(p, house_material=material)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_rooms(state, idx, n):
    """Force player `idx` to have exactly `n` ROOM cells (row 0, cols 0..n-1)."""
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.ROOM:
                grid[r][c] = Cell(cell_type=CellType.EMPTY)
    for c in range(n):
        grid[0][c] = Cell(cell_type=CellType.ROOM)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    p = fast_replace(p, farmyard=fy)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _enter_round(state, idx, *, from_round: int):
    """Set round_number=from_round and run the real `_complete_preparation` to
    enter round from_round+1, walking the whole preparation ladder (the
    `start_of_work` window fires the player's autos mechanically)."""
    state = fast_replace(state, round_number=from_round, phase=Phase.PREPARATION)
    return _complete_preparation(state)


def _num_rooms(p):
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation():
    assert CARD_ID in OCCUPATIONS
    # No on-play effect: playing it leaves resources untouched.
    s = setup(0)
    before = s.players[0].resources
    s2 = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert s2.players[0].resources == before


def test_registered_on_start_of_work_window():
    # "At the start of each work phase" → the ladder's start_of_work window
    # (re-tagged from the pre-ladder "start_of_round" event, ruling 54).
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("start_of_work", ())}
    assert CARD_ID in auto_ids
    # Choice-free auto (MANDATORY income, not a declinable FireTrigger): it lives in
    # AUTO_EFFECTS, not TRIGGERS.
    trigger_ids = {e.card_id for e in TRIGGERS.get("start_of_work", ())}
    assert CARD_ID not in trigger_ids


# ---------------------------------------------------------------------------
# Income — clay house with exactly 2 rooms -> +2 clay
# ---------------------------------------------------------------------------

def test_clay_house_two_rooms_grants_two_clay():
    s = _own_occ(setup(0), 0)
    s = _set_house(s, 0, HouseMaterial.CLAY)
    s = _set_rooms(s, 0, 2)
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=2)
    assert out.round_number == 3
    gained = out.players[0].resources - before
    assert gained == Resources(clay=2)
    # The auto fired mechanically during the walk — no window frame is pushed for
    # an auto-only card, so the ladder completed straight into WORK.
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


# ---------------------------------------------------------------------------
# Income — stone house with exactly 2 rooms -> +2 stone
# ---------------------------------------------------------------------------

def test_stone_house_two_rooms_grants_two_stone():
    s = _own_occ(setup(0), 0)
    s = _set_house(s, 0, HouseMaterial.STONE)
    s = _set_rooms(s, 0, 2)
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=5)
    assert out.round_number == 6
    gained = out.players[0].resources - before
    assert gained == Resources(stone=2)
    assert gained.clay == 0


# ---------------------------------------------------------------------------
# Eligibility boundary — wood house never grants (excluded by _eligible)
# ---------------------------------------------------------------------------

def test_wood_house_two_rooms_no_income():
    s = _own_occ(setup(0), 0)
    # default house is WOOD; force exactly 2 rooms so only the material gates it
    s = _set_rooms(s, 0, 2)
    assert s.players[0].house_material is HouseMaterial.WOOD
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=4)
    assert out.players[0].resources == before  # nothing gained
    # No eligible auto, no trigger → no frame; the ladder completes into WORK.
    assert out.pending_stack == ()
    assert out.phase is Phase.WORK


# ---------------------------------------------------------------------------
# Eligibility boundary — wrong room count gives no income (1 and 3 rooms)
# ---------------------------------------------------------------------------

def test_clay_house_one_room_no_income():
    s = _own_occ(setup(0), 0)
    s = _set_house(s, 0, HouseMaterial.CLAY)
    s = _set_rooms(s, 0, 1)   # fewer than 2 rooms -> ineligible
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=2)
    assert out.players[0].resources == before


def test_clay_house_three_rooms_no_income():
    s = _own_occ(setup(0), 0)
    s = _set_house(s, 0, HouseMaterial.CLAY)
    s = _set_rooms(s, 0, 3)   # more than 2 rooms -> ineligible
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=2)
    assert out.players[0].resources == before


# ---------------------------------------------------------------------------
# Re-checked each round — renovating to stone changes the grant type
# ---------------------------------------------------------------------------

def test_eligibility_rechecked_each_round():
    s = _own_occ(setup(0), 0)
    s = _set_house(s, 0, HouseMaterial.CLAY)
    s = _set_rooms(s, 0, 2)
    # Round R+1: clay house -> +2 clay.
    out = _enter_round(s, 0, from_round=6)
    assert out.round_number == 7
    assert out.players[0].resources - s.players[0].resources == Resources(clay=2)
    # Renovate to stone, advance another round: now grants +2 stone, not clay.
    before = out.players[0].resources
    out = _set_house(out, 0, HouseMaterial.STONE)
    out = _enter_round(out, 0, from_round=7)
    assert out.round_number == 8
    assert out.players[0].resources - before == Resources(stone=2)


# ---------------------------------------------------------------------------
# Owner-gating — only the owner gets the income
# ---------------------------------------------------------------------------

def test_only_owner_gains():
    # P0 owns Freemason + clay house + 2 rooms; P1 has the same house/rooms but no card.
    s = _own_occ(setup(0), 0)
    s = _set_house(s, 0, HouseMaterial.CLAY)
    s = _set_rooms(s, 0, 2)
    s = _set_house(s, 1, HouseMaterial.CLAY)
    s = _set_rooms(s, 1, 2)
    p1_before = s.players[1].resources
    out = _enter_round(s, 0, from_round=2)
    assert out.players[0].resources - s.players[0].resources == Resources(clay=2)
    assert out.players[1].resources == p1_before  # P1 owns nothing -> unchanged


# ---------------------------------------------------------------------------
# Full real-game round boundary (drive via `step`, not _complete_preparation)
# ---------------------------------------------------------------------------

def test_fires_across_a_real_round_boundary():
    """Drive a real game from round 1 into round 2 via `step` and confirm the +2-clay
    income lands during the preparation transition. Random play also gathers clay in
    round 1, so isolate the boundary by measuring P0's clay on the last round-1 state
    vs the first round-2 state — the delta across that single transition is the +2."""
    import numpy as np

    from agricola.agents.base import decider_of

    s, env = setup_env(0)
    s = _own_occ(s, 0)
    s = _set_house(s, 0, HouseMaterial.CLAY)
    s = _set_rooms(s, 0, 2)
    assert _num_rooms(s.players[0]) == 2
    rng = np.random.default_rng(0)
    steps = 0
    clay_before_boundary = s.players[0].resources.clay
    while s.round_number == 1 and s.phase != Phase.BEFORE_SCORING and steps < 4000:
        d = decider_of(s)
        if d is None:
            s = step(s, env.resolve(s))
        else:
            la = legal_actions(s)
            s = step(s, la[int(rng.integers(len(la)))])
        if s.round_number == 1:
            clay_before_boundary = s.players[0].resources.clay
        steps += 1
    assert s.round_number >= 2
    # The house/rooms were not changed by random round-1 play (no renovate/build-room
    # action reaches exactly-2-rooms-clay here), so P0 is still eligible at the boundary.
    assert s.players[0].house_material is HouseMaterial.CLAY
    assert _num_rooms(s.players[0]) == 2
    assert s.players[0].resources.clay == clay_before_boundary + 2
