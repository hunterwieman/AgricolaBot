"""Tests for Asparagus Knife (minor improvement, A58; Artifex Expansion).

Card text (verbatim): "In the returning home phase of rounds 8, 10, and 12, you
can take 1 vegetable from exactly 1 vegetable field. You can immediately exchange
it for 3 food and 1 bonus point." Cost: 1 Wood. VPs 0 (the bonus points are BANKED
via a scoring term, not printed VPs).

User ruling (2026-07-15): the take and exchange are two options of one optional
play-variant trigger on the round-end ladder's ``returning_home`` window (the rung
Silage uses) — "convert" (take 1 veg + exchange for 3 food + 1 banked point) and
"take_only" (take 1 veg to supply) — plus the window's Proceed = decline. The veg
is taken from ANY grid vegetable field tile (first row-major, no field choice).
Rounds 8/10/12 are all non-harvest, so the window fires normally. These tests
drive the REAL round-end walk (`_advance_until_decision` from a drained WORK
state), mirroring the Silage tests.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.asparagus_knife  # noqa: F401  (register the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.asparagus_knife import CARD_ID, _apply, _eligible, _score, _variants
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup
from agricola.state import Cell, CellType

from tests.factories import with_grid, with_minors, with_resources


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _drained_work_state(seed=0, round_number=8):
    """A WORK state with every person placed — the round-end ladder runs next."""
    state = setup(seed)
    state = dataclasses.replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _knife_state(*, veg_fields=None, round_number=8, owned=True):
    """A drained WORK state; P0 (optionally) owns Asparagus Knife with the given
    grid veg fields: {(r, c): veg held}."""
    state = _drained_work_state(round_number=round_number)
    if owned:
        state = with_minors(state, 0, frozenset({CARD_ID}))
    if veg_fields:
        state = with_grid(state, 0, {
            rc: Cell(cell_type=CellType.FIELD, veg=v) for rc, v in veg_fields.items()})
    return state


def _walk_to_window(state):
    """Advance to P0's returning_home window frame (the ladder pauses there)."""
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow), (
        f"no returning_home window surfaced (top={top!r}, phase={state.phase})")
    assert top.window_id == "returning_home" and top.player_idx == 0
    return state


def _knife_fires(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _no_returning_home_pause(state):
    """Advance and assert the walk never pauses at a returning_home window
    (the trigger was ineligible / unowned, so no frame was ever pushed)."""
    state = _advance_until_decision(state)
    assert not any(
        isinstance(f, PendingHarvestWindow) and f.window_id == "returning_home"
        for f in state.pending_stack)
    return state


def _strip_bank(state, idx=0):
    """The same state with P`idx`'s Asparagus Knife bank removed — used to isolate
    the banked points' contribution to the score."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.remove(CARD_ID))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0                          # none printed (banked instead)
    assert spec.prereq is None                    # no prerequisite
    entry = CARDS[CARD_ID]
    assert entry.event == "returning_home"        # ruling 49's rung
    assert entry.mandatory is False               # "you can"
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)   # banked-point term


# --- The variants + eligibility (unit) --------------------------------------

def test_variants_two_options_with_veg_field():
    state = _knife_state(veg_fields={(1, 1): 2}, round_number=8)
    assert _variants(state, 0) == ["convert", "take_only"]


def test_variants_empty_without_veg_field():
    # No fields at all.
    assert _variants(_knife_state(round_number=8), 0) == []
    # An empty (veg == 0) field is not a veg source.
    assert _variants(_knife_state(veg_fields={(1, 1): 0}, round_number=8), 0) == []


def test_eligible_only_on_rounds_8_10_12():
    veg = {(1, 1): 2}
    for r in (8, 10, 12):
        assert _eligible(_knife_state(veg_fields=veg, round_number=r), 0, frozenset())
    for r in (7, 9, 11, 13, 6):
        assert not _eligible(_knife_state(veg_fields=veg, round_number=r), 0, frozenset())
    # Right round but no veg field → ineligible.
    assert not _eligible(_knife_state(round_number=8), 0, frozenset())


# --- Real-walk fires ---------------------------------------------------------

def test_convert_fire():
    """"convert": take 1 veg off the field, +3 food, +1 banked point (the veg is
    consumed by the exchange, not added to supply). Once per round: only Proceed
    remains, and the banked point shows in the score."""
    state = _walk_to_window(_knife_state(veg_fields={(1, 1): 2}, round_number=8))
    fires = _knife_fires(state)
    assert FireTrigger(card_id=CARD_ID, variant="convert") in fires
    assert FireTrigger(card_id=CARD_ID, variant="take_only") in fires

    food0 = state.players[0].resources.food
    veg0 = state.players[0].resources.veg
    state = step(state, FireTrigger(card_id=CARD_ID, variant="convert"))
    p = state.players[0]
    assert p.farmyard.grid[1][1].veg == 1         # field 2 -> 1
    assert p.resources.food == food0 + 3          # +3 food
    assert p.resources.veg == veg0                # veg consumed, NOT to supply
    assert p.card_state.get(CARD_ID) == 1         # +1 banked point
    assert legal_actions(state) == [Proceed()]    # once per round
    # The banked point flows into the score.
    assert score(state, 0)[0] == score(_strip_bank(state), 0)[0] + 1


def test_take_only_fire():
    """"take_only": take 1 veg off the field to supply — no food, no point."""
    state = _walk_to_window(_knife_state(veg_fields={(1, 1): 2}, round_number=8))
    food0 = state.players[0].resources.food
    veg0 = state.players[0].resources.veg
    state = step(state, FireTrigger(card_id=CARD_ID, variant="take_only"))
    p = state.players[0]
    assert p.farmyard.grid[1][1].veg == 1         # field 2 -> 1
    assert p.resources.veg == veg0 + 1            # +1 veg to supply
    assert p.resources.food == food0              # no food
    assert p.card_state.get(CARD_ID) is None      # no banked point
    assert legal_actions(state) == [Proceed()]    # once per round


def test_proceed_declines_leaves_everything_unchanged():
    state = _walk_to_window(_knife_state(veg_fields={(1, 1): 2}, round_number=8))
    assert _knife_fires(state) != []              # it was on offer
    food0 = state.players[0].resources.food
    veg0 = state.players[0].resources.veg
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    p = state.players[0]
    assert p.farmyard.grid[1][1].veg == 2         # untouched
    assert p.resources.food == food0
    assert p.resources.veg == veg0
    assert p.card_state.get(CARD_ID) is None      # nothing banked


# --- Not offered off-round / without a veg field -----------------------------

def test_off_round_no_window_host():
    """Round 6 is non-harvest but not in {8,10,12}: the trigger is ineligible,
    the window never hosts, and the veg field is left untouched."""
    state = _knife_state(veg_fields={(1, 1): 2}, round_number=6)
    out = _no_returning_home_pause(state)
    assert out.players[0].farmyard.grid[1][1].veg == 2


def test_no_veg_field_no_window_host():
    state = _knife_state(round_number=8)               # right round, no veg field
    assert not _eligible(state, 0, frozenset())
    out = _no_returning_home_pause(state)              # window never hosts
    assert out.players[0].card_state.get(CARD_ID) is None


def test_unowned_never_hosts():
    state = _knife_state(veg_fields={(1, 1): 2}, round_number=8, owned=False)
    out = _no_returning_home_pause(state)              # window never hosts
    assert out.players[0].farmyard.grid[1][1].veg == 2  # untouched


# --- The bank accumulates across rounds 8 and 10 -----------------------------

def test_bank_accumulates_across_rounds_8_and_10():
    """A round-8 convert banks 1; a round-10 convert (the bank carried on the
    persistent CardStore, which is not round-scoped) banks a second — 2 total,
    and the score reflects +2."""
    state = _walk_to_window(_knife_state(veg_fields={(1, 1): 2}, round_number=8))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="convert"))
    assert state.players[0].card_state.get(CARD_ID) == 1
    bank = state.players[0].card_state              # carry the persistent bank

    r10 = _knife_state(veg_fields={(1, 1): 2}, round_number=10)
    r10 = _edit_player(r10, 0, card_state=bank)     # same player's bank persists
    r10 = _walk_to_window(r10)
    r10 = step(r10, FireTrigger(card_id=CARD_ID, variant="convert"))
    assert r10.players[0].card_state.get(CARD_ID) == 2
    assert _score(r10, 0) == 2
    assert score(r10, 0)[0] == score(_strip_bank(r10), 0)[0] + 2


def test_apply_increments_are_cumulative():
    """`_apply("convert")` twice increments the same counter (unit view of the
    accumulation, independent of the once-per-round window guard)."""
    state = _knife_state(veg_fields={(1, 1): 2, (1, 2): 2}, round_number=8)
    state = _apply(state, 0, "convert")
    assert state.players[0].card_state.get(CARD_ID) == 1
    state = _apply(state, 0, "convert")
    assert state.players[0].card_state.get(CARD_ID) == 2
