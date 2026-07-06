"""Seam tests for the 2026-07-05 harvest-machinery extensions, with dummy
cards (real-card coverage lives in each card's own test file):

- The BREED frame's two trigger stretches: a pre-commit "breeding" trigger
  (Stone Importer's home; ruling 20 — offered before the CommitBreed decision,
  gone after) and a post-commit "breeding_outcome" trigger (the sow grants'
  home — offered between CommitBreed and Stop).
- The breeding-outcome payload event (`register_breeding_outcome_auto`):
  which newborns were actually placed, by the engine's own kept-newborn
  indicator.
- The per-occasion optional-trigger host (`PendingHarvestOccasion`): pushed
  right after an occasion's autos wherever the occasion is emitted; Proceed
  declines.
- The capped granted sow (`PendingSow.max_fields`).
- The feeding-requirement fold (`register_feeding_requirement`).
- The replace-kind take fold (`TakeFold.skipped`/`bonus` through
  `field_take`): a replaced field is untouched and emits NO manifest entry;
  the bonus arrives from the general supply.
"""
import dataclasses

from agricola.actions import (
    CommitBreed,
    CommitSow,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.cards.harvest_windows import (
    TakeFold,
    register_breeding_outcome_auto,
    register_feeding_requirement,
    register_harvest_occasion_trigger,
)
from agricola.cards.triggers import register
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.helpers import feeding_requirement
from agricola.legality import legal_actions
from agricola.pending import (
    PendingHarvestBreed,
    PendingHarvestOccasion,
    PendingSow,
)
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.resources import Animals, Resources
from agricola.setup import setup

from tests.factories import with_phase, with_resources


# ---------------------------------------------------------------------------
# Dummy registrations (ownership-gated: inert unless a test grants the card)
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, cid):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {cid})


# Pre-commit breed trigger: +1 stone, once per breeding phase.
PRE_CARD = "_test_seam_pre_breed"
register("breeding", PRE_CARD,
         lambda s, i, resolved: True,
         lambda s, i: _edit_player(
             s, i, resources=s.players[i].resources + Resources(stone=1)))

# Outcome auto: latch the newborn total; outcome trigger: +1 food per latched.
OUT_CARD = "_test_seam_outcome"
register_breeding_outcome_auto(
    OUT_CARD,
    lambda s, i, outcome: outcome.total > 0,
    lambda s, i, outcome: _edit_player(
        s, i, card_state=s.players[i].card_state.set(OUT_CARD, outcome.total)))
register("breeding_outcome", OUT_CARD,
         lambda s, i, resolved: s.players[i].card_state.get(OUT_CARD, 0) > 0,
         lambda s, i: _edit_player(
             s, i, resources=s.players[i].resources
             + Resources(food=s.players[i].card_state.get(OUT_CARD, 0))))

# Occasion trigger: if the occasion took >= 1 grain, may swap 1 grain -> 2 food.
OCC_CARD = "_test_seam_occasion"
register_harvest_occasion_trigger(
    OCC_CARD,
    lambda s, i, occ: (sum(e.amount for e in occ.entries if e.crop == "grain") >= 1
                       and s.players[i].resources.grain >= 1),
    lambda s, i, occ: _edit_player(
        s, i, resources=s.players[i].resources + Resources(grain=-1, food=2)))

# Feeding fold: newborns cost 2 (the Child's Toy shape).
FEED_CARD = "_test_seam_feed_fold"
register_feeding_requirement(
    FEED_CARD, lambda s, i, need: need + s.players[i].newborns)


# ---------------------------------------------------------------------------
# Drivers
# ---------------------------------------------------------------------------

def _set_pasture_1x1(state, player_idx, row=0, col=0):
    """Add a 1x1 pasture enclosed at (row, col) — capacity 2 (+1 house pet),
    so a 2-sheep holding can keep its newborn."""
    from agricola.pasture import compute_pastures_from_arrays
    from agricola.state import Farmyard

    p = state.players[player_idx]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    h[row][col] = True
    h[row + 1][col] = True
    v[row][col] = True
    v[row][col + 1] = True
    new_h = tuple(tuple(r) for r in h)
    new_v = tuple(tuple(r) for r in v)
    new_pastures = compute_pastures_from_arrays(p.farmyard.grid, new_h, new_v)
    return _edit_player(state, player_idx, farmyard=Farmyard(
        grid=p.farmyard.grid, horizontal_fences=new_h,
        vertical_fences=new_v, pastures=new_pastures))


def _sow_grain(state, idx, cells, amount=3):
    p = state.players[idx]
    grid = tuple(
        tuple(
            fast_replace(cell, cell_type=CellType.FIELD, grain=amount)
            if (r, c) in cells else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    return _edit_player(state, idx, farmyard=fast_replace(p.farmyard, grid=grid))


def _breed_state(sheep=0, boar=0, cattle=0):
    """A HARVEST_FIELD-phase state (the walk must ENTER breeding itself — a
    bare empty-stack BREED state reads as breeding-already-done), both players
    food-rich, P0 holding the given animals. Keep counts small enough that
    the two starting rooms' house capacity questions stay away from what
    these tests pin (a newborn sheep fits the house pet slot)."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in (0, 1):
        state = with_resources(state, i, food=20)
    if sheep or boar or cattle:
        state = _set_pasture_1x1(state, 0)       # room for a kept newborn
        state = _edit_player(state, 0, animals=Animals(
            sheep=sheep, boar=boar, cattle=cattle))
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


# ---------------------------------------------------------------------------
# Breed frame: the two trigger stretches
# ---------------------------------------------------------------------------

def test_pre_breed_trigger_before_commit_only():
    """Ruling 20: the 'breeding' trigger is offered BEFORE CommitBreed, and
    gone after (only outcome triggers + Stop remain)."""
    state = _to_p0_breed_frame(_own_occ(_breed_state(), 0, PRE_CARD))
    acts = legal_actions(state)
    assert FireTrigger(card_id=PRE_CARD) in acts
    assert any(isinstance(a, CommitBreed) for a in acts)
    assert Stop() not in acts
    # Fire it: the frame stays up, CommitBreed still to come, no re-offer.
    state = step(state, FireTrigger(card_id=PRE_CARD))
    assert state.players[0].resources.stone == 1
    acts = legal_actions(state)
    assert FireTrigger(card_id=PRE_CARD) not in acts
    assert any(isinstance(a, CommitBreed) for a in acts)
    # After the commit the pre-commit event is closed.
    state = step(state, next(a for a in acts if isinstance(a, CommitBreed)))
    assert all(not isinstance(a, CommitBreed) for a in legal_actions(state))


def test_outcome_event_and_post_commit_trigger():
    """Two sheep breed a newborn: the outcome auto latches total=1, the
    'breeding_outcome' trigger surfaces AFTER CommitBreed and pays off it."""
    state = _to_p0_breed_frame(_own_occ(_breed_state(sheep=2), 0, OUT_CARD))
    # Pre-commit: the outcome trigger is NOT offered yet.
    acts = legal_actions(state)
    assert FireTrigger(card_id=OUT_CARD) not in acts
    breed = max((a for a in acts if isinstance(a, CommitBreed)),
                key=lambda a: a.sheep)
    assert breed.sheep == 3                      # the newborn is placeable
    state = step(state, breed)
    assert state.players[0].card_state.get(OUT_CARD, 0) == 1   # auto latched
    acts = legal_actions(state)
    assert FireTrigger(card_id=OUT_CARD) in acts
    assert Stop() in acts                        # declinable
    food0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=OUT_CARD))
    assert state.players[0].resources.food == food0 + 1
    assert legal_actions(state) == [Stop()]


def test_no_newborn_no_outcome_latch():
    state = _to_p0_breed_frame(_own_occ(_breed_state(sheep=1), 0, OUT_CARD))
    breed = next(a for a in legal_actions(state) if isinstance(a, CommitBreed))
    state = step(state, breed)
    assert state.players[0].card_state.get(OUT_CARD, 0) == 0
    assert legal_actions(state) == [Stop()]


# ---------------------------------------------------------------------------
# The per-occasion optional-trigger host
# ---------------------------------------------------------------------------

def test_occasion_host_from_inline_take():
    """The walk's inline take pushes the occasion host for an owner with an
    eligible occasion trigger; firing applies; Proceed pops and the harvest
    goes on."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in (0, 1):
        state = with_resources(state, i, food=20)
    state = _sow_grain(state, 0, {(0, 1)})
    state = _own_occ(state, 0, OCC_CARD)
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestOccasion)
    assert top.player_idx == 0
    assert top.occasion.source == "take"
    acts = legal_actions(state)
    assert FireTrigger(card_id=OCC_CARD) in acts
    assert Proceed() in acts
    food0 = state.players[0].resources.food
    grain0 = state.players[0].resources.grain
    state = step(state, FireTrigger(card_id=OCC_CARD))
    assert state.players[0].resources.food == food0 + 2
    assert state.players[0].resources.grain == grain0 - 1
    state = step(state, Proceed())
    assert state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED)


def test_occasion_host_not_pushed_when_ineligible():
    """No grain harvested -> the dummy trigger is ineligible -> no host."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    for i in (0, 1):
        state = with_resources(state, i, food=20)
    state = _own_occ(state, 0, OCC_CARD)          # owned, but nothing to take
    state = _advance_until_decision(state)
    assert not any(isinstance(f, PendingHarvestOccasion)
                   for f in state.pending_stack)


# ---------------------------------------------------------------------------
# Capped granted sow
# ---------------------------------------------------------------------------

def test_sow_cap_limits_fields():
    state = setup(seed=0)
    state = _sow_grain(state, 0, set())           # no-op, then blank 3 fields:
    p = state.players[0]
    grid = tuple(
        tuple(
            fast_replace(cell, cell_type=CellType.FIELD)
            if (r, c) in {(0, 1), (0, 2), (0, 3)} else cell
            for c, cell in enumerate(row))
        for r, row in enumerate(p.farmyard.grid))
    state = _edit_player(state, 0, farmyard=fast_replace(p.farmyard, grid=grid))
    state = with_resources(state, 0, grain=5, veg=5)
    frame = PendingSow(player_idx=0, initiated_by_id="card:_test", max_fields=1)
    state = dataclasses.replace(state, pending_stack=(frame,), current_player=0)
    commits = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert commits and all(a.grain + a.veg == 1 for a in commits)
    # Uncapped control: with 3 empty fields, 2-field commits exist.
    frame = PendingSow(player_idx=0, initiated_by_id="card:_test")
    state = dataclasses.replace(state, pending_stack=(frame,))
    commits = [a for a in legal_actions(state) if isinstance(a, CommitSow)]
    assert any(a.grain + a.veg == 3 for a in commits)


# ---------------------------------------------------------------------------
# Feeding-requirement fold
# ---------------------------------------------------------------------------

def test_feeding_fold_applies_for_owner_only():
    state = setup(seed=0)
    state = _edit_player(state, 0, newborns=1, people_total=3)
    base = feeding_requirement(state, 0)
    assert base == 2 * 3 - 1
    owned = _own_occ(state, 0, FEED_CARD)
    assert feeding_requirement(owned, 0) == 2 * 3      # newborn costs 2
    # The opponent (non-owner) is unaffected.
    assert feeding_requirement(owned, 1) == feeding_requirement(state, 1)


# ---------------------------------------------------------------------------
# Replace-kind take fold through field_take
# ---------------------------------------------------------------------------

def test_field_take_skip_and_bonus():
    """A replaced field is untouched and absent from the manifest; the bonus
    arrives from the general supply."""
    state = setup(seed=0)
    state = _sow_grain(state, 0, {(0, 1), (0, 2)}, amount=3)
    grain0 = state.players[0].resources.grain
    state, occasion = field_take(
        state, 0, skip_cells=frozenset({(0, 2)}), bonus=Resources(grain=1))
    # (0,1) harvested 1; (0,2) untouched; +1 bonus grain from the supply.
    assert state.players[0].farmyard.grid[0][1].grain == 2
    assert state.players[0].farmyard.grid[0][2].grain == 3
    assert state.players[0].resources.grain == grain0 + 2
    assert [e.source for e in occasion.entries] == ["cell:0,1"]


def test_take_fold_dataclass_normalization():
    """A bare dict fold return is extras-only shorthand for TakeFold."""
    fold = TakeFold(extras={(0, 1): 1})
    assert fold.skipped == frozenset() and fold.bonus is None
