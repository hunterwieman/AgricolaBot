"""Tests for Sample Stable Maker (occupation, D #102; Dulcinaria Expansion).

Card text (verbatim): "At the start of each returning home phase, you can
return a built stable to your supply to get 1 wood, 1 grain, 1 food, and a
\"Minor Improvement\" action."

The effect rides the round-end ladder's ``start_of_returning_home`` window
(ruling 49, 2026-07-12; round_end.py assigns this card to that rung) as an
optional play-variant trigger — one FireTrigger per built-stable cell, encoded
"r,c" (which stable matters: fenced halves a pasture, unfenced frees a cell
and its flexible slot). A fire returns the stable (cell -> EMPTY; the supply
count is derived, so it rises automatically), flags the accommodation barrier
(the Milking Place capacity-reduction idiom), grants 1 wood + 1 grain +
1 food, and — iff a hand minor is playable on the post-goods state — pushes
the optional PendingGrantedSubAction("play_minor") wrapper (Dwelling Plan
idiom; Stop declines the minor alone). These tests drive the REAL round-end
walk (`_advance_until_decision` from a drained WORK state — the Silage idiom).
"""
from __future__ import annotations

import dataclasses

import agricola.cards.sample_stable_maker   # noqa: F401  (register the card)

from contextlib import contextmanager

from agricola.actions import (
    ChooseSubAction,
    CommitAccommodate,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.cards.sample_stable_maker import CARD_ID, _variants
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, _complete_preparation, step
from agricola.helpers import stables_built, stables_in_supply
from agricola.legality import legal_actions, playable_minors
from agricola.pending import (
    PendingAccommodate,
    PendingGrantedSubAction,
    PendingHarvestWindow,
    PendingPlayMinor,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_animals, with_grid, with_resources
from tests.test_utils import sole_play_minor

_MINOR = "test_ssm_minor"   # test-scoped filler minor, cost 1 food


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _drained_work_state(seed=0, round_number=1):
    """A WORK state with every person placed — the round-end ladder runs next."""
    state = setup(seed)
    state = dataclasses.replace(
        state, phase=Phase.WORK, round_number=round_number, starting_player=0)
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)
    return state


def _with_stables(state, idx, cells):
    return with_grid(state, idx,
                     {rc: Cell(cell_type=CellType.STABLE) for rc in cells})


def _fence_1x1(state, idx, row=0, col=0):
    """Fence the single cell (row, col) into a 1x1 pasture (mineral_feeder
    idiom), recomputing the pasture cache from the arrays."""
    from agricola.pasture import compute_pastures_from_arrays
    from agricola.state import Farmyard

    p = state.players[idx]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    h[row][col] = True
    h[row + 1][col] = True
    v[row][col] = True
    v[row][col + 1] = True
    h_t = tuple(tuple(r) for r in h)
    v_t = tuple(tuple(r) for r in v)
    return _edit_player(state, idx, farmyard=Farmyard(
        grid=p.farmyard.grid, horizontal_fences=h_t, vertical_fences=v_t,
        pastures=compute_pastures_from_arrays(p.farmyard.grid, h_t, v_t)))


def _ssm_state(*, stables=((0, 3), (0, 4)), round_number=1, owned=True,
               hand_minors=(), **resources):
    """A drained WORK state; P0 (optionally) owns Sample Stable Maker in the
    tableau, with the given standalone stables, hand minors, and EXACT
    resources (unnamed kinds zero)."""
    state = _drained_work_state(round_number=round_number)
    p = state.players[0]
    if owned:
        state = _edit_player(state, 0, occupations=p.occupations | {CARD_ID})
    if hand_minors:
        state = _edit_player(state, 0, hand_minors=frozenset(hand_minors))
    state = with_resources(state, 0, **resources)
    if stables:
        state = _with_stables(state, 0, stables)
    return state


def _walk_to_window(state):
    """Advance to P0's start_of_returning_home window frame."""
    state = _advance_until_decision(state)
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow), (
        f"no start_of_returning_home window surfaced "
        f"(top={top!r}, phase={state.phase})")
    assert top.window_id == "start_of_returning_home" and top.player_idx == 0
    return state


def _ssm_fires(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def _no_window_pause(state):
    """Advance and assert the walk never pauses at a start_of_returning_home
    window (trigger ineligible / unowned, so no frame was ever pushed)."""
    state = _advance_until_decision(state)
    assert not any(
        isinstance(f, PendingHarvestWindow)
        and f.window_id == "start_of_returning_home"
        for f in state.pending_stack)
    return state


@contextmanager
def _filler_minor():
    """A test-scoped 1-food minor as the granted play's target (the
    Beneficiary try/finally pattern)."""
    from agricola.cards.specs import MINORS, register_minor

    register_minor(_MINOR, cost=Cost(resources=Resources(food=1)))
    try:
        yield
    finally:
        MINORS.pop(_MINOR, None)


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    entry = CARDS[CARD_ID]
    assert entry.event == "start_of_returning_home"   # ruling 49's rung
    assert entry.mandatory is False                   # "you can"
    assert CARD_ID in PLAY_VARIANT_TRIGGERS


# --- The variants encoding (unit) --------------------------------------------

def test_variants_one_per_built_stable_row_major():
    state = _ssm_state(stables=((1, 2), (0, 4), (2, 0)))
    assert _variants(state, 0) == ["0,4", "1,2", "2,0"]


def test_variants_empty_without_stables():
    state = _ssm_state(stables=())
    assert _variants(state, 0) == []


# --- The unfenced return, end-to-end ------------------------------------------

def test_unfenced_return_goods_and_supply():
    """Firing "0,3" returns that stable (cell EMPTY, built -1, supply +1 —
    derived), grants 1 wood + 1 grain + 1 food, pushes no wrapper (no hand
    minor), and is once per round (only Proceed remains); the opponent is
    untouched and declining onward reaches PREPARATION."""
    state = _walk_to_window(_ssm_state(food=0))
    p1_before = state.players[1]
    assert _ssm_fires(state) == [
        FireTrigger(card_id=CARD_ID, variant="0,3"),
        FireTrigger(card_id=CARD_ID, variant="0,4"),
    ]

    state = step(state, FireTrigger(card_id=CARD_ID, variant="0,3"))
    p = state.players[0]
    assert p.farmyard.grid[0][3].cell_type is CellType.EMPTY   # returned
    assert p.farmyard.grid[0][4].cell_type is CellType.STABLE  # the other stays
    assert stables_built(p.farmyard) == 1
    assert stables_in_supply(p) == 3                           # derived: rose
    assert p.resources.wood == 1
    assert p.resources.grain == 1
    assert p.resources.food == 1
    # The barrier ran at the decision boundary: flag cleared, no frame (no
    # animals held), no wrapper (no hand minor).
    assert not p.animals_need_accommodation
    assert not any(isinstance(f, (PendingAccommodate, PendingGrantedSubAction))
                   for f in state.pending_stack)
    assert state.players[1] == p1_before                       # opponent untouched
    # Once per round: the frame's triggers_resolved swallows a re-offer even
    # though a second stable remains.
    assert legal_actions(state) == [Proceed()]

    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION                    # round 1: no harvest
    assert state.round_end_cursor is None


# --- The minor rider -----------------------------------------------------------

def test_minor_rider_offered_after_goods_and_declinable():
    """With 0 food and a 1-food hand minor, the minor is NOT playable before
    the fire — the granted food is what pays it — so the wrapper appearing
    proves the rider is gated on the POST-goods state. Stop declines the
    minor alone; the goods stay."""
    with _filler_minor():
        state = _walk_to_window(_ssm_state(food=0, hand_minors=(_MINOR,)))
        assert playable_minors(state, 0) == []        # unaffordable pre-goods

        state = step(state, FireTrigger(card_id=CARD_ID, variant="0,3"))
        top = state.pending_stack[-1]
        assert isinstance(top, PendingGrantedSubAction)
        assert top.player_idx == 0
        assert top.initiated_by_id == "card:sample_stable_maker"
        assert top.subactions == ("play_minor",)
        assert legal_actions(state) == [
            ChooseSubAction(name="play_minor"), Stop()]

        state = step(state, Stop())                   # decline the minor alone
        p = state.players[0]
        assert p.resources.food == 1                  # the goods stayed
        assert _MINOR in p.hand_minors                # the minor was not played
        assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
        assert legal_actions(state) == [Proceed()]


def test_minor_rider_playable_end_to_end():
    with _filler_minor():
        state = _walk_to_window(_ssm_state(food=0, hand_minors=(_MINOR,)))
        state = step(state, FireTrigger(card_id=CARD_ID, variant="0,3"))
        state = step(state, ChooseSubAction(name="play_minor"))
        top = state.pending_stack[-1]
        assert isinstance(top, PendingPlayMinor)
        # SSM grants the named "Minor Improvement" action -> flag threaded True
        # through the wrapper (so it chains Merchant / would enable Blueprint).
        assert top.minor_improvement_action is True

        state = step(state, sole_play_minor(state, _MINOR))
        p = state.players[0]
        assert _MINOR in p.minor_improvements         # played into the tableau
        assert _MINOR not in p.hand_minors
        assert p.resources.food == 0                  # granted food paid the cost
        assert p.resources.wood == 1 and p.resources.grain == 1

        # The play host's after-phase (after-triggers + Stop) pops first, then
        # the wrapper — its play_minor spent, only Stop remains — then the
        # window's Proceed, and onward to PREPARATION.
        top = state.pending_stack[-1]
        assert isinstance(top, PendingPlayMinor) and top.phase == "after"
        state = step(state, Stop())
        top = state.pending_stack[-1]
        assert isinstance(top, PendingGrantedSubAction)
        assert legal_actions(state) == [Stop()]
        state = step(state, Stop())
        assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
        state = step(state, Proceed())
        state = _advance_until_decision(state)
        assert state.phase == Phase.PREPARATION


def test_no_playable_minor_goods_only():
    """A hand minor the granted goods still can't pay for: no wrapper, the
    goods land regardless."""
    from agricola.cards.specs import MINORS, register_minor

    expensive = "test_ssm_expensive_minor"
    register_minor(expensive, cost=Cost(resources=Resources(stone=5)))
    try:
        state = _walk_to_window(_ssm_state(food=0, hand_minors=(expensive,)))
        state = step(state, FireTrigger(card_id=CARD_ID, variant="0,3"))
        p = state.players[0]
        assert p.resources.wood == 1 and p.resources.grain == 1
        assert p.resources.food == 1
        assert not any(isinstance(f, PendingGrantedSubAction)
                       for f in state.pending_stack)
        assert legal_actions(state) == [Proceed()]
    finally:
        MINORS.pop(expensive, None)


# --- The capacity guard ----------------------------------------------------------

def test_fenced_stable_return_surfaces_accommodation():
    """A 1x1 pasture with a stable houses 4; with 4 sheep held (they fit:
    4 + the house pet slot), returning that stable halves the pasture to 2
    (+ pet = 3 total) — the barrier surfaces the keep-which choice at the
    next decision boundary, and the excess sheep is released."""
    state = _ssm_state(stables=((0, 0),), food=0)
    state = _fence_1x1(state, 0, 0, 0)
    state = with_animals(state, 0, sheep=4)
    state = _walk_to_window(state)

    state = step(state, FireTrigger(card_id=CARD_ID, variant="0,0"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingAccommodate) and top.player_idx == 0
    p = state.players[0]
    assert p.farmyard.grid[0][0].cell_type is CellType.EMPTY   # stable returned
    assert p.resources.wood == 1 and p.resources.grain == 1
    assert p.resources.food == 1

    # Capacity is now 3 (pasture 2 + house pet 1): the sole frontier keep.
    assert legal_actions(state) == [
        CommitAccommodate(sheep=3, boar=0, cattle=0)]
    state = step(state, CommitAccommodate(sheep=3, boar=0, cattle=0))
    assert state.players[0].animals.sheep == 3
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION


# --- Eligibility boundaries --------------------------------------------------------

def test_no_built_stables_no_trigger():
    state = _ssm_state(stables=(), food=0)
    out = _no_window_pause(state)
    assert out.phase == Phase.PREPARATION
    assert out.players[0].resources.wood == 0


def test_hand_only_inert():
    """In hand but not played: the ownership gate keeps the window frameless."""
    state = _ssm_state(owned=False, food=0)
    state = _edit_player(
        state, 0,
        hand_occupations=state.players[0].hand_occupations | {CARD_ID})
    out = _no_window_pause(state)
    assert out.phase == Phase.PREPARATION
    assert out.players[0].resources.wood == 0
    assert stables_built(out.players[0].farmyard) == 2


def test_decline_via_proceed_leaves_everything_unchanged():
    state = _walk_to_window(_ssm_state(food=0))
    assert _ssm_fires(state) != []                    # it was on offer
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    p = state.players[0]
    assert stables_built(p.farmyard) == 2
    assert p.resources.wood == 0 and p.resources.grain == 0
    assert p.resources.food == 0
    assert state.phase == Phase.PREPARATION


# --- Once per round, fresh next round -------------------------------------------

def test_fresh_offer_next_round():
    """After the round-1 fire (latched by that window frame's
    triggers_resolved), entering round 2 and draining again re-hosts the
    window with the remaining stable on offer — the latch does not persist."""
    state = _walk_to_window(_ssm_state(food=0))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="0,3"))
    state = step(state, Proceed())
    state = _advance_until_decision(state)
    assert state.phase == Phase.PREPARATION

    # Enter round 2 via the engine's preparation walk (the Nest Site idiom:
    # the reveal is assumed done for legacy fixtures), then drain the workers.
    state = fast_replace(state, pending_stack=(),
                         phase=Phase.PREPARATION, round_number=1)
    state = _complete_preparation(state)
    assert state.round_number == 2 and state.phase == Phase.WORK
    for idx in (0, 1):
        state = _edit_player(state, idx, people_home=0)

    state = _walk_to_window(state)
    assert _ssm_fires(state) == [
        FireTrigger(card_id=CARD_ID, variant="0,4")]   # the remaining stable


# --- Labels ----------------------------------------------------------------------

def test_action_labels():
    from agricola.cards.display import variant_label

    assert (variant_label(CARD_ID, "0,3")
            == "Return stable (row 1, col 4) → 1 wood, 1 grain, 1 food (+ minor)")
    assert (variant_label(CARD_ID, "2,0")
            == "Return stable (row 3, col 1) → 1 wood, 1 grain, 1 food (+ minor)")
