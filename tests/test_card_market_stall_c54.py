"""Tests for Market Stall (minor improvement, C54; Corbarius Expansion) —
card_id `market_stall_c54` (the Base-Revised B8 card owns the `market_stall`
name slug).

Card text: "After the field phase of each harvest, you can exchange 1 grain
plus 1 fence (both from your supply) for 5 food."
Play cost: "1 Stable from Your Supply".

The play cost spends a stable piece from supply without building it: recorded
in the card's own card_state and subtracted by the DERIVED
`helpers.stables_in_supply(player)` through the cost-mod removal seam — no
stored PlayerState field, Family state shape untouched. The recurring exchange
is an `after_field_phase` window trigger; the fence piece is spent from the
stored `fences_in_supply` pile, never placed.
"""
from __future__ import annotations

import agricola.cards.market_stall_c54  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.cost_mods import STABLE_SUPPLY_REMOVALS
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS
from agricola.constants import CellType, Phase
from agricola.engine import _advance_until_decision, step
from agricola.helpers import stables_in_supply
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import with_grid, with_phase

CARD_ID = "market_stall_c54"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_played(state, idx):
    """Put the card in the tableau AND record its paid play cost (the on_play
    stable removal) — the state a real play produces."""
    p = state.players[idx]
    p = fast_replace(
        p,
        minor_improvements=p.minor_improvements | {CARD_ID},
        card_state=p.card_state.set(f"{CARD_ID}_stable_removed", 1),
    )
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _harvest_state(seed=0, food=10, grain=2):
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        p = state.players[idx]
        p = fast_replace(p, resources=fast_replace(p.resources, food=food,
                                                   grain=grain))
        state = fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))
    return state


def _walk_to_window(state):
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow):
            return state
        state = step(state, legal_actions(state)[0])
    return state


# ---------------------------------------------------------------------------
# Registration + the play cost through the derived supply
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("after_field_phase", set())
    assert CARD_ID in STABLE_SUPPLY_REMOVALS
    spec = MINORS[CARD_ID]
    assert spec.prereq is not None       # "1 Stable from Your Supply" payable
    assert spec.vps == 0


def test_play_cost_removes_a_stable_from_the_derived_supply():
    state = setup(0)
    assert stables_in_supply(state.players[0]) == 4
    spec = MINORS[CARD_ID]
    state = _own_played(state, 0)        # tableau + the on_play removal record
    # The piece is spent, not built: supply drops with nothing on the grid.
    assert stables_in_supply(state.players[0]) == 3
    from agricola.helpers import stables_built
    assert stables_built(state.players[0].farmyard) == 0
    # The opponent's supply is untouched (removals are per-owner).
    assert stables_in_supply(state.players[1]) == 4


def test_on_play_records_the_removal():
    state = setup(0)
    after = MINORS[CARD_ID].on_play(state, 0)
    assert after.players[0].card_state.get(f"{CARD_ID}_stable_removed") == 1


def test_prereq_requires_a_stable_in_supply():
    spec = MINORS[CARD_ID]
    state = setup(0)
    assert spec.prereq(state, 0) is True                 # 4 in supply
    # All four stables built -> none in supply -> unplayable.
    state4 = with_grid(state, 0, {
        (0, 4): Cell(cell_type=CellType.STABLE),
        (1, 4): Cell(cell_type=CellType.STABLE),
        (2, 4): Cell(cell_type=CellType.STABLE),
        (2, 3): Cell(cell_type=CellType.STABLE),
    })
    assert stables_in_supply(state4.players[0]) == 0
    assert spec.prereq(state4, 0) is False


def test_removed_piece_caps_future_builds():
    """After paying the stable cost, only 3 pieces remain buildable: with 3
    already built, the build-stable gate reads supply 0."""
    state = _own_played(setup(0), 0)
    state = with_grid(state, 0, {
        (0, 4): Cell(cell_type=CellType.STABLE),
        (1, 4): Cell(cell_type=CellType.STABLE),
        (2, 4): Cell(cell_type=CellType.STABLE),
    })
    assert stables_in_supply(state.players[0]) == 0      # 4 - 3 built - 1 removed


# ---------------------------------------------------------------------------
# The exchange at after_field_phase
# ---------------------------------------------------------------------------

def test_exchange_grain_plus_fence_for_five_food():
    state = _own_played(_harvest_state(), 0)
    state = _walk_to_window(state)
    top = state.pending_stack[-1]
    assert top.window_id == "after_field_phase" and top.player_idx == 0
    g0 = state.players[0].resources.grain
    f0 = state.players[0].resources.food
    n0 = state.players[0].fences_in_supply
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.grain == g0 - 1
    assert state.players[0].resources.food == f0 + 5
    assert state.players[0].fences_in_supply == n0 - 1   # piece spent, not placed


def test_once_per_harvest_then_declinable_next():
    state = _own_played(_harvest_state(), 0)
    state = _walk_to_window(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert legal_actions(state) == [Proceed()]           # spent this harvest
    state = step(state, Proceed())
    assert _advance_until_decision(state).phase == Phase.HARVEST_FEED


def test_not_offered_when_grain_or_fence_short():
    # No grain -> the harvest completes with no window pause.
    state = _own_played(_harvest_state(grain=0), 0)
    assert _walk_to_window(state).phase == Phase.PREPARATION
    # No fence pieces left in supply -> same.
    state = _own_played(_harvest_state(), 0)
    p = state.players[0]
    state = fast_replace(state, players=tuple(
        fast_replace(p, fences_in_supply=0) if i == 0 else state.players[i]
        for i in range(2)))
    assert _walk_to_window(state).phase == Phase.PREPARATION


def test_not_offered_to_non_owner():
    state = _harvest_state()
    assert _walk_to_window(state).phase == Phase.PREPARATION
