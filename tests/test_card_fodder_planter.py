"""Tests for Fodder Planter (occupation, D115).

Card text (verbatim): "In the breeding phase of each harvest, for each newborn
animal you get, you can sow crops in exactly 1 field."

An outcome-reactive breeding grant (user ruling 20, 2026-07-05: surfaces AFTER
CommitBreed, before Stop, still inside the breeding phase): an AUTO latches
(round, placed-newborn total) in the card's own card_state at CommitBreed; the
"breeding_outcome" trigger then offers a sow capped at that total —
``PendingSow(max_fields=k)``, one commit of 1..k fields (partial use legal;
declining all = not firing; Stop on the breed frame is the decline path).
Eligibility requires a committable sow (>= 1 empty FIELD cell AND grain or veg
in supply) so a fired trigger never lands on a dead frame.

These tests drive REAL harvests through the walk (``_advance_until_decision``
+ ``step``) from Phase.HARVEST_FIELD — an empty-stack HARVEST_BREED state
reads as breeding-already-done, so the walk must enter breeding itself (the
tests/test_harvest_seam_hosts.py convention).
"""
from __future__ import annotations

import dataclasses
import json
import os

import agricola.cards.fodder_planter  # noqa: F401  (register the card)
import agricola.cards

from agricola.actions import CommitBreed, CommitSow, FireTrigger, Stop
from agricola.cards.fodder_planter import CARD_ID
from agricola.cards.harvest_windows import BREEDING_OUTCOME_AUTOS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestBreed, PendingSow
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.setup import setup

from tests.factories import with_phase, with_resources


# ---------------------------------------------------------------------------
# Helpers (the tests/test_harvest_seam_hosts.py drivers, pasture generalized)
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _add_row_pasture(state, player_idx, row, col_lo, col_hi):
    """Fence a 1 x N pasture over cells (row, col_lo..col_hi) — capacity
    2 per cell (no stables)."""
    from agricola.pasture import compute_pastures_from_arrays
    from agricola.state import Farmyard

    p = state.players[player_idx]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    for c in range(col_lo, col_hi + 1):
        h[row][c] = True
        h[row + 1][c] = True
    v[row][col_lo] = True
    v[row][col_hi + 1] = True
    new_h = tuple(tuple(r) for r in h)
    new_v = tuple(tuple(r) for r in v)
    new_pastures = compute_pastures_from_arrays(p.farmyard.grid, new_h, new_v)
    return _edit_player(state, player_idx, farmyard=Farmyard(
        grid=p.farmyard.grid, horizontal_fences=new_h,
        vertical_fences=new_v, pastures=new_pastures))


def _with_empty_fields(state, idx, cells):
    """Turn the given empty cells into EMPTY (unsown) FIELD cells."""
    p = state.players[idx]
    grid = tuple(
        tuple(
            fast_replace(cell, cell_type=CellType.FIELD)
            if (r, c) in cells else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    return _edit_player(state, idx, farmyard=fast_replace(p.farmyard, grid=grid))


def _breed_state(*, sheep=0, boar=0, grain=0, veg=0, fields=frozenset(),
                 own=True):
    """A HARVEST_FIELD-phase state (the walk must ENTER breeding itself),
    both players food-rich (food covers the requirement, so the feed frame's
    frontier is the single convert-nothing point and never consumes P0's
    crops), P0 the starting player, holding the given animals + crops +
    empty fields. Pastures: sheep get a 1x2 at row 0 cols 0-1, boar a 1x2 at
    row 0 cols 2-3 (capacity 4 each — room for the kept newborn)."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=20, grain=grain, veg=veg)
    state = with_resources(state, 1, food=20)
    if own:
        state = _own(state, 0)
    if sheep:
        state = _add_row_pasture(state, 0, 0, 0, 1)
    if boar:
        state = _add_row_pasture(state, 0, 0, 2, 3)
    if sheep or boar:
        state = _edit_player(state, 0, animals=Animals(sheep=sheep, boar=boar))
    if fields:
        state = _with_empty_fields(state, 0, fields)
    return state


def _to_p0_breed_frame(state):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestBreed) and top.player_idx == 0
                and not top.breed_chosen):
            return state
        state = step(state, legal_actions(state)[0])
    raise AssertionError("no P0 breed frame surfaced")


def _max_breed(actions):
    return max((a for a in actions if isinstance(a, CommitBreed)),
               key=lambda a: a.sheep + a.boar + a.cattle)


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON row)
# ---------------------------------------------------------------------------

def test_registration_spec_matches_json():
    path = os.path.join(os.path.dirname(agricola.cards.__file__),
                        "data", "revised_occupations.json")
    with open(path) as f:
        row = next(r for r in json.load(f) if r["name"] == "Fodder Planter")
    assert row["type"] == "Occupation"
    assert row["deck"] == "D" and row["number"] == 115
    # The module docstring quotes the printed text + clarifications verbatim
    # (whitespace-normalized: the docstring wraps lines, the JSON does not).
    doc = " ".join(agricola.cards.fodder_planter.__doc__.split())
    assert " ".join(row["text"].split()) in doc
    assert " ".join(row["clarifications"].split()) in doc
    assert CARD_ID in OCCUPATIONS


def test_registered_as_outcome_auto_and_breeding_outcome_trigger():
    assert any(e.card_id == CARD_ID for e in BREEDING_OUTCOME_AUTOS)
    entry = next(e for e in TRIGGERS.get("breeding_outcome", ())
                 if e.card_id == CARD_ID)
    assert entry.mandatory is False        # "you can" — an optional trigger


def test_on_play_is_a_noop():
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) == state


# ---------------------------------------------------------------------------
# One newborn, end to end
# ---------------------------------------------------------------------------

def test_one_newborn_grants_one_field_sow_end_to_end():
    """Two sheep breed one newborn: the trigger surfaces only AFTER
    CommitBreed (ruling 20), fires into a 1-field-capped PendingSow, and the
    sow lands on the farm."""
    state = _to_p0_breed_frame(_breed_state(
        sheep=2, grain=2, veg=2, fields={(2, 3), (2, 4)}))
    # Pre-commit: no outcome trigger yet.
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in acts
    breed = _max_breed(acts)
    assert breed.sheep == 3                          # the newborn is placeable
    state = step(state, breed)
    assert state.players[0].card_state.get(CARD_ID) == (state.round_number, 1)
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts
    assert Stop() in acts                            # declinable alongside

    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSow)
    assert top.player_idx == 0
    assert top.max_fields == 1
    assert top.initiated_by_id == f"card:{CARD_ID}"
    commits = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert commits and all(a.grain + a.veg == 1 for a in commits)

    grain0 = state.players[0].resources.grain
    state = step(state, CommitSow(grain=1, veg=0))
    assert state.players[0].resources.grain == grain0 - 1
    assert state.players[0].farmyard.grid[2][3].grain == 3   # a normal sow
    state = step(state, Stop())                      # pop the after-phase sow
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestBreed) and top.breed_chosen
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in acts  # once per breeding phase
    assert Stop() in acts
    state = step(state, Stop())
    assert not any(isinstance(f, PendingHarvestBreed) and f.player_idx == 0
                   for f in state.pending_stack)


# ---------------------------------------------------------------------------
# Two newborns: cap 2, partial use legal
# ---------------------------------------------------------------------------

def test_two_newborns_cap_two_and_partial_use():
    """Sheep + boar each breed: cap 2 — the enumerator offers 1..2 fields
    (each granted field individually optional), and sowing just 1 is legal."""
    state = _to_p0_breed_frame(_breed_state(
        sheep=2, boar=2, grain=3, veg=3, fields={(2, 2), (2, 3), (2, 4)}))
    breed = _max_breed(legal_actions(state))
    assert (breed.sheep, breed.boar) == (3, 3)       # both newborns placeable
    state = step(state, breed)
    assert state.players[0].card_state.get(CARD_ID) == (state.round_number, 2)

    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.pending_stack[-1].max_fields == 2
    commits = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    # 3 empty fields + ample crops: the newborn cap (2), not the farm, binds.
    assert all(1 <= a.grain + a.veg <= 2 for a in commits)
    assert any(a.grain + a.veg == 2 for a in commits)
    assert CommitSow(grain=1, veg=0) in commits      # partial use

    state = step(state, CommitSow(grain=1, veg=0))   # sow 1 of the 2 granted
    state = step(state, Stop())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestBreed)
    assert legal_actions(state) == [Stop()]          # no re-offer of the rest


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------

def test_no_newborns_no_trigger():
    """One sheep breeds nothing: the latch stays empty, no trigger."""
    state = _to_p0_breed_frame(_breed_state(
        sheep=1, grain=2, fields={(2, 4)}))
    breed = next(a for a in legal_actions(state) if isinstance(a, CommitBreed))
    state = step(state, breed)
    assert state.players[0].card_state.get(CARD_ID) is None
    assert legal_actions(state) == [Stop()]


def test_stale_latch_from_previous_harvest_is_inert():
    """A latch keyed to a PAST harvest round never matches the current round:
    crops + empty field in place, latch total 2 — still no trigger."""
    state = _breed_state(sheep=1, grain=2, fields={(2, 4)})
    state = dataclasses.replace(state, round_number=7)
    p = state.players[0]
    state = _edit_player(
        state, 0, card_state=p.card_state.set(CARD_ID, (4, 2)))
    state = _to_p0_breed_frame(state)
    breed = next(a for a in legal_actions(state) if isinstance(a, CommitBreed))
    state = step(state, breed)                       # no newborn: latch untouched
    assert state.players[0].card_state.get(CARD_ID) == (4, 2)
    assert legal_actions(state) == [Stop()]


def test_not_offered_without_empty_field():
    """A newborn latched but no EMPTY field (the only field is planted):
    no committable sow, so the trigger is withheld — no dead frame."""
    state = _breed_state(sheep=2, grain=2, fields={(2, 4)})
    p = state.players[0]
    grid = tuple(
        tuple(fast_replace(cell, grain=3) if (r, c) == (2, 4) else cell
              for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    state = _edit_player(state, 0, farmyard=fast_replace(p.farmyard, grid=grid))
    state = _to_p0_breed_frame(state)
    state = step(state, _max_breed(legal_actions(state)))
    assert state.players[0].card_state.get(CARD_ID)[1] == 1   # latched...
    assert legal_actions(state) == [Stop()]                   # ...but withheld


def test_not_offered_without_crops():
    """A newborn latched and an empty field, but no grain/veg in supply:
    no committable sow, so the trigger is withheld."""
    state = _to_p0_breed_frame(_breed_state(sheep=2, fields={(2, 4)}))
    state = step(state, _max_breed(legal_actions(state)))
    assert state.players[0].card_state.get(CARD_ID)[1] == 1
    assert legal_actions(state) == [Stop()]


def test_decline_via_stop():
    """Granted sub-actions are optional: Stop on the breed frame without
    firing declines the whole grant — nothing sown, nothing spent."""
    state = _to_p0_breed_frame(_breed_state(
        sheep=2, grain=2, fields={(2, 4)}))
    state = step(state, _max_breed(legal_actions(state)))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    grain0 = state.players[0].resources.grain
    state = step(state, Stop())
    assert not any(isinstance(f, PendingHarvestBreed) and f.player_idx == 0
                   for f in state.pending_stack)
    assert state.players[0].resources.grain == grain0
    assert state.players[0].farmyard.grid[2][4].grain == 0


def test_unowned_never_fires():
    """Without the occupation, neither the auto (no latch) nor the trigger
    fires, crops and empty fields notwithstanding."""
    state = _to_p0_breed_frame(_breed_state(
        sheep=2, grain=2, fields={(2, 4)}, own=False))
    state = step(state, _max_breed(legal_actions(state)))
    assert state.players[0].card_state.get(CARD_ID) is None
    assert legal_actions(state) == [Stop()]
