"""Tests for Carpenter's Axe (minor improvement, A15; Artifex Expansion).

Card text: "Each time after you use a wood accumulation space, if you then have at
least 7 wood in your supply, you can build exactly 1 stable for 1 wood."
Cost: 1 Wood. No prerequisite. No VPs. Not passing.

Shape: an OPTIONAL `after_action_space` FireTrigger on the atomic-hosted Forest
(the only wood accumulation space on the 2-player board). The atomic Forest host
runs its +3 wood pickup on Proceed FIRST, then flips to the after-phase where this
trigger is surfaced — so the "≥ 7 wood" test reads the POST-pickup supply. Firing
grants exactly 1 stable for 1 wood (a PendingBuildStables, max_builds=1); declining
is not firing (the host's Proceed exits without building).
"""
from __future__ import annotations

import agricola.cards.carpenters_axe  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitBuildStable,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingBuildStables
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_resources

CARD_ID = "carpenters_axe"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, "market_stall") + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _count_stables(p):
    return sum(c.cell_type == CellType.STABLE
               for row in p.farmyard.grid for c in row)


def _fill_grid_no_stable(state, idx):
    """Make every empty cell a FIELD so no stable cell is legal (_can_build_stable
    false on the cell-availability leg)."""
    p = state.players[idx]
    grid = [[c for c in row] for row in p.farmyard.grid]
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.EMPTY:
                grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return fast_replace(state, players=tuple(
        fast_replace(p, farmyard=fy) if i == idx else state.players[i] for i in range(2)))


def _place_forest_to_after(state):
    """Place P0 at the (already-revealed) Forest and Proceed past the pickup so the
    host frame is in its after-phase (where the trigger is surfaced). Returns the
    after-phase state. Forest accrues +3 wood on Proceed."""
    state = step(state, PlaceWorker(space="forest"))
    # Forest is atomic-hosted (P0 owns the card) → before-phase, only Proceed legal.
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())                 # +3 wood, flip to after-phase
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_carpenters_axe_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.prereq is None
    assert spec.vps == 0
    assert not spec.passing_left
    # Optional after_action_space trigger + an atomic Forest host.
    aas = {e.card_id for e in TRIGGERS.get("after_action_space", [])}
    assert CARD_ID in aas
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("forest", set())


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_offered_when_seven_wood_after_pickup():
    # 4 wood + Forest's 3 = 7 (the threshold, AFTER pickup) → offered.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=4)
    s = _place_forest_to_after(s)
    assert s.players[cp].resources.wood == 7        # post-pickup
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_not_offered_when_six_wood_after_pickup():
    # 3 wood + 3 = 6 < 7 → the threshold is read AFTER the pickup and fails.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=3)
    s = _place_forest_to_after(s)
    assert s.players[cp].resources.wood == 6        # post-pickup, just under
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_offered_with_abundant_wood():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=10)
    s = _place_forest_to_after(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_not_offered_when_no_stable_cell():
    # ≥ 7 wood but no empty cell to place a stable → eligibility's _can_build_stable
    # is false, so the trigger is not a dead-end fire.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=10)
    s = _fill_grid_no_stable(s, cp)
    s = _place_forest_to_after(s)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_without_card():
    # Without the card, Forest is NOT hosted (atomic fast path): placing resolves
    # immediately, no host frame, no trigger.
    s, cp = _card_state()
    s = with_resources(s, cp, wood=10)
    s = step(s, PlaceWorker(space="forest"))
    assert not s.pending_stack                      # resolved atomically
    assert s.players[cp].resources.wood == 13       # 10 + 3 pickup, no stable built


# ---------------------------------------------------------------------------
# The effect via the real engine flow
# ---------------------------------------------------------------------------

def test_fire_builds_exactly_one_stable_for_one_wood():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=4)
    stables0 = _count_stables(s.players[cp])
    s = _place_forest_to_after(s)
    assert s.players[cp].resources.wood == 7
    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildStables)
    assert top.cost == Resources(wood=1)
    assert top.max_builds == 1
    assert top.num_built == 0
    # At num_built=0 the granted build is mandatory (no Proceed/Stop yet) — only
    # CommitBuildStable cells are offered.
    la = legal_actions(s)
    commits = [a for a in la if isinstance(a, CommitBuildStable)]
    assert commits
    assert Proceed() not in la and Stop() not in la
    s = step(s, commits[0])
    assert s.players[cp].resources.wood == 6        # 7 - 1
    assert _count_stables(s.players[cp]) == stables0 + 1
    # Single build saturates max_builds=1: the multi-shot host stays in before-phase
    # with num_built=1, and Proceed (the work-complete signal) is the only exit.
    assert s.pending_stack[-1].num_built == 1
    la = legal_actions(s)
    assert not [a for a in la if isinstance(a, CommitBuildStable)]   # cap saturated
    assert Proceed() in la
    s = step(s, Proceed())                          # flip the build host to after-phase
    assert s.pending_stack[-1].phase == "after"


def test_fires_once_per_use():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=4)
    s = _place_forest_to_after(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    commits = [a for a in legal_actions(s) if isinstance(a, CommitBuildStable)]
    s = step(s, commits[0])                         # build the 1 stable
    s = step(s, Proceed())                          # flip build host to after-phase
    s = step(s, Stop())                             # pop PendingBuildStables
    # Back at the Forest host's after-phase; already fired -> not re-offered.
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Optionality — declining = not firing
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_stop():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=8)
    stables0 = _count_stables(s.players[cp])
    s = _place_forest_to_after(s)
    la = legal_actions(s)
    # Both firing AND declining (the host's Stop, which exits the after-phase) are
    # available — the optionality lives at the FireTrigger, not in the build host.
    assert FireTrigger(card_id=CARD_ID) in la
    assert Stop() in la
    s = step(s, Stop())                             # decline → host exits, turn ends
    assert not s.pending_stack                      # Forest use complete
    assert s.players[cp].resources.wood == 11       # 8 + 3 pickup, no 1 wood spent
    assert _count_stables(s.players[cp]) == stables0  # no stable built


# ---------------------------------------------------------------------------
# Wrong space / wrong event does not fire
# ---------------------------------------------------------------------------

def test_clay_pit_does_not_fire():
    # Clay Pit is an accumulation space, but CLAY not wood — Carpenter's Axe is not
    # hooked on it, so the space stays atomic (no host) and nothing fires.
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = with_resources(s, cp, wood=10)
    sp = fast_replace(get_space(s.board, "clay_pit"), revealed=True, workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "clay_pit", sp))
    s = step(s, PlaceWorker(space="clay_pit"))
    # Not hosted for this card → resolves atomically, no FireTrigger anywhere.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s) if s.pending_stack else True
    assert not s.pending_stack
