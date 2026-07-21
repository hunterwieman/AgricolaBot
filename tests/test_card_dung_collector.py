import agricola.cards.dung_collector  # noqa: F401
"""Tests for Dung Collector (occupation, E90).

Card text (verbatim): "Each time you get 2 or more newborn animals, you can
pay 1 food to plow 1 field."

User ruling 74 (2026-07-21): fires ONLY on harvest breeding outcomes — the
``BreedingOutcome`` payload with >= 2 newborns placed (at most 1 per type, so
>= 2 means >= 2 types bred). An AUTO latches (round, placed-newborn total) in
the card's own card_state at CommitBreed when >= 2 were placed; the optional
"breeding_outcome" trigger (post-commit, before Stop, still inside the
breeding phase) then offers pay-1-food-plow-1-field, gated on food >= 1 AND a
plowable cell (never a dead end). Firing debits the food and pushes
``PendingPlow``; Stop on the breed frame declines.

These tests drive REAL harvests through the walk (``_advance_until_decision``
+ ``step``) from Phase.HARVEST_FIELD — an empty-stack HARVEST_BREED state
reads as breeding-already-done, so the walk must enter breeding itself (the
tests/test_harvest_seam_hosts.py convention, via test_card_fodder_planter.py).
"""

import dataclasses
import json
import os

import agricola.cards

from agricola.actions import CommitBreed, CommitPlow, FireTrigger, Stop
from agricola.cards.dung_collector import CARD_ID
from agricola.cards.harvest_windows import BREEDING_OUTCOME_AUTOS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestBreed, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.setup import setup

from tests.factories import with_phase, with_resources


# ---------------------------------------------------------------------------
# Helpers (the test_card_fodder_planter.py drivers)
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


def _make_fields(state, idx, cells):
    """Turn the given cells into (empty) FIELD cells."""
    p = state.players[idx]
    grid = tuple(
        tuple(
            fast_replace(cell, cell_type=CellType.FIELD)
            if (r, c) in cells else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    return _edit_player(state, idx, farmyard=fast_replace(p.farmyard, grid=grid))


def _breed_state(*, sheep=0, boar=0, food=20, own=True):
    """A HARVEST_FIELD-phase state (the walk must ENTER breeding itself),
    P0 the starting player holding the given animals + food (P1 food-rich, so
    their feed frame is the single pay-food point). Pastures: sheep get a 1x2
    at row 0 cols 0-1, boar a 1x2 at row 0 cols 2-3 (capacity 4 each — room
    for the kept newborn). P0 holds no crops, so their feed frontier is the
    single pay-food point too (food covers the 4-food requirement in every
    test here)."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=food)
    state = with_resources(state, 1, food=20)
    if own:
        state = _own(state, 0)
    if sheep:
        state = _add_row_pasture(state, 0, 0, 0, 1)
    if boar:
        state = _add_row_pasture(state, 0, 0, 2, 3)
    if sheep or boar:
        state = _edit_player(state, 0, animals=Animals(sheep=sheep, boar=boar))
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
        row = next(r for r in json.load(f) if r["name"] == "Dung Collector")
    assert row["type"] == "Occupation"
    assert row["deck"] == "E" and row["number"] == 90
    # The module docstring quotes the printed text + clarification verbatim
    # (whitespace-normalized: the docstring wraps lines, the JSON does not).
    doc = " ".join(agricola.cards.dung_collector.__doc__.split())
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
# Two newborns, end to end: latch -> fire -> pay 1 food -> plow -> Stop
# ---------------------------------------------------------------------------

def test_two_newborns_pay_food_and_plow_end_to_end():
    """Sheep + boar each breed (2 newborns placed): the trigger surfaces only
    AFTER CommitBreed (the post-commit "breeding_outcome" stretch), fires into
    a 1-food debit + a PendingPlow, and the plow commits onto a real cell."""
    state = _to_p0_breed_frame(_breed_state(sheep=2, boar=2))
    # Pre-commit "breeding" stretch: no outcome trigger yet.
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in acts
    breed = _max_breed(acts)
    assert (breed.sheep, breed.boar) == (3, 3)       # both newborns placeable
    state = step(state, breed)
    assert state.players[0].card_state.get(CARD_ID) == (state.round_number, 2)
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts
    assert Stop() in acts                            # declinable alongside

    food0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == food0 - 1
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPlow)
    assert top.player_idx == 0
    assert top.initiated_by_id == f"card:{CARD_ID}"
    commits = [a for a in legal_actions(state) if isinstance(a, CommitPlow)]
    assert CommitPlow(row=2, col=4) in commits       # a real, un-enclosed cell

    state = step(state, CommitPlow(row=2, col=4))
    assert state.players[0].farmyard.grid[2][4].cell_type == CellType.FIELD
    state = step(state, Stop())                      # pop the after-phase plow
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestBreed) and top.breed_chosen
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) not in acts  # once per breeding event
    assert Stop() in acts
    state = step(state, Stop())
    assert not any(isinstance(f, PendingHarvestBreed) and f.player_idx == 0
                   for f in state.pending_stack)


# ---------------------------------------------------------------------------
# Threshold boundary: exactly 1 newborn never latches, never offers
# ---------------------------------------------------------------------------

def test_one_newborn_below_threshold_no_trigger():
    """Two sheep breed exactly 1 newborn (1 type): "2 or more" is not met —
    the latch stays empty and no trigger surfaces, food + plowable cells
    notwithstanding."""
    state = _to_p0_breed_frame(_breed_state(sheep=2))
    breed = _max_breed(legal_actions(state))
    assert breed.sheep == 3                          # the newborn IS placed
    state = step(state, breed)
    assert state.players[0].card_state.get(CARD_ID) is None
    assert legal_actions(state) == [Stop()]


# ---------------------------------------------------------------------------
# Eligibility gates: food and a plowable cell
# ---------------------------------------------------------------------------

def test_not_offered_without_food():
    """2 newborns latched, but feeding consumed all the food (4 food covers
    exactly the 4-food requirement): food 0 < 1, so the trigger is withheld —
    a fired trigger could not pay."""
    state = _to_p0_breed_frame(_breed_state(sheep=2, boar=2, food=4))
    state = step(state, _max_breed(legal_actions(state)))
    assert state.players[0].resources.food == 0
    assert state.players[0].card_state.get(CARD_ID)[1] == 2   # latched...
    assert legal_actions(state) == [Stop()]                   # ...but withheld


def test_not_offered_without_plowable_cell():
    """2 newborns latched and food on hand, but every EMPTY cell is enclosed
    or already a field: no legal plow, so the trigger is withheld — no dead
    frame."""
    state = _breed_state(sheep=2, boar=2)
    # Fill every non-room, non-pasture cell with a FIELD: rooms sit at (1,0)
    # and (2,0), the pastures cover row 0 cols 0-3 (enclosed EMPTY cells are
    # not plowable), so these 9 cells are the only plow targets.
    state = _make_fields(state, 0, {(0, 4),
                                    (1, 1), (1, 2), (1, 3), (1, 4),
                                    (2, 1), (2, 2), (2, 3), (2, 4)})
    state = _to_p0_breed_frame(state)
    state = step(state, _max_breed(legal_actions(state)))
    assert state.players[0].card_state.get(CARD_ID)[1] == 2   # latched...
    assert legal_actions(state) == [Stop()]                   # ...but withheld


# ---------------------------------------------------------------------------
# Decline, staleness, ownership
# ---------------------------------------------------------------------------

def test_decline_via_stop():
    """"You can": Stop on the breed frame without firing declines — no food
    debited, no plow frame, nothing plowed."""
    state = _to_p0_breed_frame(_breed_state(sheep=2, boar=2))
    state = step(state, _max_breed(legal_actions(state)))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    food0 = state.players[0].resources.food
    state = step(state, Stop())
    assert not any(isinstance(f, PendingHarvestBreed) and f.player_idx == 0
                   for f in state.pending_stack)
    assert state.players[0].resources.food == food0
    assert all(cell.cell_type != CellType.FIELD
               for row in state.players[0].farmyard.grid for cell in row)


def test_stale_latch_from_previous_harvest_is_inert():
    """A latch keyed to a PAST harvest round never matches the current round:
    food + plowable cells in place, latch total 2 — still no trigger."""
    state = _breed_state(sheep=1)
    state = dataclasses.replace(state, round_number=7)
    p = state.players[0]
    state = _edit_player(
        state, 0, card_state=p.card_state.set(CARD_ID, (4, 2)))
    state = _to_p0_breed_frame(state)
    breed = next(a for a in legal_actions(state) if isinstance(a, CommitBreed))
    state = step(state, breed)                       # no newborns: latch untouched
    assert state.players[0].card_state.get(CARD_ID) == (4, 2)
    assert legal_actions(state) == [Stop()]


def test_unowned_never_fires():
    """Without the occupation, neither the auto (no latch) nor the trigger
    fires, 2 placed newborns notwithstanding."""
    state = _to_p0_breed_frame(_breed_state(sheep=2, boar=2, own=False))
    state = step(state, _max_breed(legal_actions(state)))
    assert state.players[0].card_state.get(CARD_ID) is None
    assert legal_actions(state) == [Stop()]
