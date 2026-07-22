"""Tests for Slurry (minor improvement, C71; Corbarius Expansion) —
card_id `slurry_spreader_c71`. The id is legacy: the card's JSON name used to
read "Slurry Spreader" (matching the Artifex A106 occupation, which owns the
`slurry_spreader` slug) and was later corrected to just "Slurry".

Card text: "In the breeding phase of each harvest, if you get newborn animals
of at least two types, you also get a "Sow" action."
Clarification: "You must be able to accommodate each newborn in order to get
it." No cost, no prerequisite, no VPs.

The grant rides the breed frame's post-commit stretch (user ruling 20,
2026-07-05): a `register_breeding_outcome_auto` latches the two-types
qualification round-keyed at CommitBreed (the outcome payload holds only
PLACED newborns, so the accommodation clarification is inherent), and a
"breeding_outcome" trigger — offered AFTER CommitBreed, before Stop — pushes
an UNCAPPED PendingSow (the full standard "Sow" action). Declining is Stop on
the breed frame without firing; once per harvest via `triggers_resolved`.

All harvest walks here start from Phase.HARVEST_FIELD — an empty-stack
HARVEST_BREED state reads as breeding-already-done (the seam-test pattern).
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import agricola.cards.slurry_spreader_c71  # noqa: F401  (registers the card)
import agricola.cards.slurry_spreader      # noqa: F401  (the A106 occupation)

from agricola.actions import CommitBreed, CommitSow, FireTrigger, Stop
from agricola.cards.harvest_windows import (
    BREEDING_OUTCOME_AUTOS,
    HARVEST_OCCASION_AUTOS,
)
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.cards.triggers import CARDS as TRIGGER_CARDS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestBreed, PendingSow
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost
from agricola.setup import setup

from tests.factories import with_phase, with_resources

CARD_ID = "slurry_spreader_c71"


# ---------------------------------------------------------------------------
# Helpers (the seam-test drivers, adapted)
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, cid=CARD_ID):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {cid})


def _set_pasture(state, player_idx, row, col, width=1):
    """Fence a 1 x `width` pasture at (row, col..col+width-1) — capacity
    2 per cell, one animal type per pasture (+ the 1 house-pet flexible slot
    farm-wide)."""
    from agricola.pasture import compute_pastures_from_arrays
    from agricola.state import Farmyard

    p = state.players[player_idx]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    for c in range(col, col + width):
        h[row][c] = True
        h[row + 1][c] = True
    v[row][col] = True
    v[row][col + width] = True
    new_h = tuple(tuple(r) for r in h)
    new_v = tuple(tuple(r) for r in v)
    new_pastures = compute_pastures_from_arrays(p.farmyard.grid, new_h, new_v)
    return _edit_player(state, player_idx, farmyard=Farmyard(
        grid=p.farmyard.grid, horizontal_fences=new_h,
        vertical_fences=new_v, pastures=new_pastures))


def _add_empty_fields(state, idx, cells):
    """Turn `cells` into empty (sowable) FIELD cells."""
    p = state.players[idx]
    grid = tuple(
        tuple(
            fast_replace(cell, cell_type=CellType.FIELD)
            if (r, c) in cells else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    return _edit_player(state, idx, farmyard=fast_replace(p.farmyard, grid=grid))


_FIELD_CELLS = {(2, 2), (2, 3), (2, 4)}


def _breed_state(*, sheep=0, boar=0, grain=0, veg=0, fields=True, owned=True):
    """A HARVEST_FIELD-phase state (the walk must ENTER breeding itself — a
    bare empty-stack BREED state reads as breeding-already-done), both players
    food-rich, P0 holding the given animals with room to place BOTH newborns:
    a 2-cell pasture at (0,0)-(0,1) (cap 4) + a 1x1 at (1,1) (cap 2) + the
    house-pet slot. Empty FIELD cells at (2,2)-(2,4) unless fields=False."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 1, food=20)
    state = with_resources(state, 0, food=20, grain=grain, veg=veg)
    if fields:
        state = _add_empty_fields(state, 0, _FIELD_CELLS)
    if sheep or boar:
        state = _set_pasture(state, 0, 0, 0, width=2)   # cap 4
        state = _set_pasture(state, 0, 1, 1, width=1)   # cap 2
        state = _edit_player(state, 0, animals=Animals(sheep=sheep, boar=boar))
    if owned:
        state = _own_minor(state, 0)
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


def _walk_out_of_harvest(state, max_steps=40):
    for _ in range(max_steps):
        if state.phase not in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                               Phase.HARVEST_BREED):
            return state
        state = step(state, legal_actions(state)[0])
    raise AssertionError("harvest did not finish")


# ---------------------------------------------------------------------------
# Registration / spec vs the JSON row
# ---------------------------------------------------------------------------

def test_registered_and_spec_matches_json_row():
    rows = json.loads(
        (Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
         / "revised_minor_improvements.json").read_text())
    row = next(r for r in rows if r["deck"] == "C" and r["number"] == 71)
    assert row["name"] == "Slurry"
    assert row["cost"] is None
    assert row["prerequisites"] is None
    assert row["vps"] is None
    # The module docstring quotes the printed text verbatim.
    import agricola.cards.slurry_spreader_c71 as mod
    assert row["text"] in " ".join(mod.__doc__.split())

    spec = MINORS[CARD_ID]
    assert spec.cost == Cost() and spec.alt_costs == ()
    assert spec.prereq is None and spec.min_occupations == 0
    assert spec.vps == 0
    # The two seams: the outcome auto + the post-commit trigger.
    assert any(e.card_id == CARD_ID for e in BREEDING_OUTCOME_AUTOS)
    assert TRIGGER_CARDS[CARD_ID].event == "breeding_outcome"


def test_coexists_with_the_a106_occupation():
    """The A106 occupation "Slurry Spreader" (slug `slurry_spreader`) and this
    minor (`slurry_spreader_c71`) are distinct registrations side by side."""
    assert "slurry_spreader" in OCCUPATIONS
    assert "slurry_spreader" not in MINORS
    assert CARD_ID in MINORS
    assert CARD_ID not in OCCUPATIONS
    # A106 is a harvest-occasion auto; C71 is a breeding-outcome auto.
    assert any(e.card_id == "slurry_spreader" for e in HARVEST_OCCASION_AUTOS)
    assert all(e.card_id != CARD_ID for e in HARVEST_OCCASION_AUTOS)
    assert any(e.card_id == CARD_ID for e in BREEDING_OUTCOME_AUTOS)
    assert all(e.card_id != "slurry_spreader" for e in BREEDING_OUTCOME_AUTOS)


# ---------------------------------------------------------------------------
# The grant: two newborn types -> an uncapped sow, once per harvest
# ---------------------------------------------------------------------------

def test_two_types_grants_uncapped_sow_once():
    state = _to_p0_breed_frame(_breed_state(sheep=2, boar=2, grain=5, veg=5))
    acts = legal_actions(state)
    # Pre-commit: the outcome trigger is NOT offered yet (ruling 20 stretch).
    assert FireTrigger(card_id=CARD_ID) not in acts
    # Both newborns are placeable (2-cell pasture: 3 sheep; 1x1 + pet: 3 boar).
    breed = CommitBreed(sheep=3, boar=3, cattle=0)
    assert breed in acts
    state = step(state, breed)
    # The auto latched this round's qualification.
    assert state.players[0].card_state.get(CARD_ID) == state.round_number
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts
    assert Stop() in acts                        # declinable
    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSow)
    assert top.player_idx == 0
    assert top.initiated_by_id == f"card:{CARD_ID}"
    assert top.max_fields == 0                   # UNCAPPED — the full "Sow"
    commits = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    # 3 empty fields, ample crops: a 3-field commit exists (uncapped).
    assert any(a.grain + a.veg == 3 for a in commits)
    state = step(state, CommitSow(grain=2, veg=1))
    assert state.players[0].resources.grain == 3
    assert state.players[0].resources.veg == 4
    planted = [state.players[0].farmyard.grid[r][c] for (r, c) in _FIELD_CELLS]
    assert all(cell.grain > 0 or cell.veg > 0 for cell in planted)
    state = step(state, Stop())                  # pop the sow's after-phase
    # Back on the breed frame: once per harvest — no re-offer, only Stop.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestBreed) and top.player_idx == 0
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert _walk_out_of_harvest(state).phase == Phase.PREPARATION


def test_decline_via_stop():
    state = _to_p0_breed_frame(_breed_state(sheep=2, boar=2, grain=5, veg=5))
    state = step(state, CommitBreed(sheep=3, boar=3, cattle=0))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    grain0 = state.players[0].resources.grain
    state = step(state, Stop())                  # decline: never fire
    assert not any(isinstance(f, PendingSow) for f in state.pending_stack)
    assert state.players[0].resources.grain == grain0
    assert _walk_out_of_harvest(state).phase == Phase.PREPARATION


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------

def test_one_type_of_newborn_not_offered():
    state = _to_p0_breed_frame(_breed_state(sheep=2, grain=5, veg=5))
    breed = max((a for a in legal_actions(state) if isinstance(a, CommitBreed)),
                key=lambda a: a.sheep)
    assert breed.sheep == 3                      # the newborn IS placed
    state = step(state, breed)
    assert state.players[0].card_state.get(CARD_ID) is None   # no latch
    assert legal_actions(state) == [Stop()]


def test_zero_newborns_not_offered():
    state = _to_p0_breed_frame(_breed_state(sheep=1, boar=1, grain=5, veg=5))
    # One of each: no pair, no newborn of any type.
    state = step(state, next(a for a in legal_actions(state)
                             if isinstance(a, CommitBreed)))
    assert state.players[0].card_state.get(CARD_ID) is None
    assert legal_actions(state) == [Stop()]


def test_no_empty_field_not_offered():
    """Two types latched, but no empty field cell -> the sow is not
    committable -> the trigger is withheld (never a dead frame)."""
    state = _to_p0_breed_frame(
        _breed_state(sheep=2, boar=2, grain=5, veg=5, fields=False))
    state = step(state, CommitBreed(sheep=3, boar=3, cattle=0))
    assert state.players[0].card_state.get(CARD_ID) == state.round_number
    assert legal_actions(state) == [Stop()]


def test_no_crops_not_offered():
    """Two types latched, empty fields present, but no grain/veg in supply."""
    state = _to_p0_breed_frame(_breed_state(sheep=2, boar=2))
    state = step(state, CommitBreed(sheep=3, boar=3, cattle=0))
    assert state.players[0].card_state.get(CARD_ID) == state.round_number
    assert legal_actions(state) == [Stop()]


def test_unowned_never_fires():
    state = _to_p0_breed_frame(
        _breed_state(sheep=2, boar=2, grain=5, veg=5, owned=False))
    state = step(state, CommitBreed(sheep=3, boar=3, cattle=0))
    assert state.players[0].card_state.get(CARD_ID) is None   # auto is gated
    assert legal_actions(state) == [Stop()]
