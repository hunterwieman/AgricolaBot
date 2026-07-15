"""Tests for Champion Breeder (occupation E133).

Card text: "Each time you place 2 or 3+ newborn animals on your farm during the
breeding phase of the harvest, you get 1 or 2 bonus points, respectively."
Clarification: "You must be able to accommodate each newborn in order to get it."

A breeding-outcome reaction: at each harvest's breeding, 2 placed newborns bank 1
point and 3+ bank 2, accumulating across harvests. Tests drive the real dispatcher
(`apply_breeding_outcome_autos`, called by `_execute_breed`) for the tier logic,
accumulation, round-keying, and owner-gating, plus a full breed-walk end-to-end, and
the scoring readback. The accommodation clarification is inherent — the payload holds
only PLACED newborns.
"""
import dataclasses

import agricola.cards.champion_breeder  # noqa: F401  (registers the card)

from agricola.cards.champion_breeder import CARD_ID
from agricola.cards.harvest_windows import (
    BREEDING_OUTCOME_AUTOS,
    apply_breeding_outcome_autos,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import BreedingOutcome, PendingHarvestBreed
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup

from tests.factories import with_phase, with_resources


def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx):
    return _edit_player(state, idx, occupations=state.players[idx].occupations | {CARD_ID})


def _banked(state, idx):
    return state.players[idx].card_state.get(CARD_ID, (0, 0))[1]


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _fire(state, idx, sheep=0, boar=0, cattle=0):
    outcome = BreedingOutcome(sheep=sheep, boar=boar, cattle=cattle)
    return apply_breeding_outcome_autos(state, idx, outcome)


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert any(e.card_id == CARD_ID for e in BREEDING_OUTCOME_AUTOS)
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_on_play_is_noop():
    s = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) == s


# --- Tier logic (via the real dispatcher) -----------------------------------

def test_two_newborns_bank_one_point():
    s = dataclasses.replace(_own(setup(0), 0), round_number=4)
    out = _fire(s, 0, sheep=1, boar=1)          # total 2
    assert _banked(out, 0) == 1


def test_three_newborns_bank_two_points():
    s = dataclasses.replace(_own(setup(0), 0), round_number=4)
    out = _fire(s, 0, sheep=1, boar=1, cattle=1)   # total 3
    assert _banked(out, 0) == 2


def test_one_newborn_banks_nothing():
    s = dataclasses.replace(_own(setup(0), 0), round_number=4)
    out = _fire(s, 0, sheep=1)                   # total 1 -> ineligible
    assert _banked(out, 0) == 0


def test_zero_newborns_bank_nothing():
    s = dataclasses.replace(_own(setup(0), 0), round_number=4)
    out = _fire(s, 0)                            # total 0
    assert _banked(out, 0) == 0


# --- Accumulation + round-keying --------------------------------------------

def test_accumulates_across_harvests():
    s = dataclasses.replace(_own(setup(0), 0), round_number=4)
    s = _fire(s, 0, sheep=1, boar=1)            # +1 at round 4
    assert _banked(s, 0) == 1
    s = dataclasses.replace(s, round_number=7)
    s = _fire(s, 0, sheep=1, boar=1, cattle=1)  # +2 at round 7
    assert _banked(s, 0) == 3


def test_round_keying_prevents_double_count():
    s = dataclasses.replace(_own(setup(0), 0), round_number=4)
    s = _fire(s, 0, sheep=1, boar=1)            # +1
    s = _fire(s, 0, sheep=1, boar=1, cattle=1)  # same round -> no re-bank
    assert _banked(s, 0) == 1


def test_only_owner_banks():
    s = dataclasses.replace(setup(0), round_number=4)     # nobody owns it
    out = _fire(s, 0, sheep=1, boar=1)
    assert _banked(out, 0) == 0


# --- Scoring ----------------------------------------------------------------

def test_scoring_reads_bank():
    score = _score_fn()
    s = setup(0)
    assert score(s, 0) == 0
    p = fast_replace(s.players[0], card_state=s.players[0].card_state.set(CARD_ID, (13, 5)))
    s = fast_replace(s, players=(p, s.players[1]))
    assert score(s, 0) == 5


# --- End-to-end: a real breeding banks the point ----------------------------

def _add_row_pasture(state, player_idx, row, col_lo, col_hi):
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


def test_two_newborns_bank_one_point_end_to_end():
    """Sheep + boar each breed one newborn in a real harvest -> 2 placed -> +1."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0, round_number=4)
    state = with_resources(state, 0, food=20)
    state = with_resources(state, 1, food=20)
    state = _own(state, 0)
    state = _add_row_pasture(state, 0, 0, 0, 1)      # sheep pasture, cap 4
    state = _add_row_pasture(state, 0, 0, 2, 3)      # boar pasture, cap 4
    state = _edit_player(state, 0, animals=Animals(sheep=2, boar=2))

    # Walk to P0's breed frame, then commit the maximal breed (both newborns).
    state = _advance_until_decision(state)
    from agricola.actions import CommitBreed
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestBreed) and top.player_idx == 0
                and not top.breed_chosen):
            break
        state = step(state, legal_actions(state)[0])
    breed = max((a for a in legal_actions(state) if isinstance(a, CommitBreed)),
                key=lambda a: a.sheep + a.boar + a.cattle)
    assert (breed.sheep, breed.boar) == (3, 3)       # both newborns placeable
    state = step(state, breed)
    assert _banked(state, 0) == 1
