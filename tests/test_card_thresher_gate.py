"""Thresher's placement-gate extension + the Drill Harrow sow route (ruling 87,
2026-07-29 — the user-ratified rule: an optional before-window purchase counts
toward "can carry out the action" at placement time).

Pins, in order: each enabling route at the Grain Utilization gate (sow via the
bought grain / bake via the bought grain / the raise-bundle payment branch),
the refusals, Cultivation's sow half, Farmland's deliberate non-extension, the
MANDATORY-fire consequence (ext-only admission → the buy is the sole legal
action, emergent from the host's must-take-at-least-one-effect exits), the
Drill Harrow route at the gate, and the two-card composition priced exactly
(3 food refused / 4 food legal, walked end-to-end)."""
from __future__ import annotations

import agricola.cards  # noqa: F401  -- populate the registries

from agricola.actions import (
    ChooseSubAction,
    CommitPlow,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlow, PendingSow
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_majors, with_resources

_POOL = CardPool(
    occupations=("thresher",) + tuple(f"o{i}" for i in range(20)),
    minors=("drill_harrow",) + tuple(f"m{i}" for i in range(20)),
)


def _base(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    for sp_id in ("grain_utilization", "cultivation", "farmland"):
        sp = fast_replace(get_space(s.board, sp_id), revealed=True, workers=(0, 0))
        s = fast_replace(s, board=with_space(s.board, sp_id, sp))
    return s


def _own(s, *, occs=(), minors=()):
    p = s.players[0]
    p = fast_replace(p, occupations=p.occupations | set(occs),
                     minor_improvements=p.minor_improvements | set(minors))
    return fast_replace(s, players=(p, s.players[1]))


def _grid(s, fields=0, fill_rest=False):
    """Give P0 `fields` empty FIELD cells; optionally turn every other EMPTY
    cell into a FIELD too (killing plowability while keeping sow targets)."""
    p = s.players[0]
    grid = [[c for c in row] for row in p.farmyard.grid]
    placed = 0
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.EMPTY:
                if placed < fields:
                    grid[r][c] = Cell(cell_type=CellType.FIELD)
                    placed += 1
                elif fill_rest:
                    grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return fast_replace(s, players=(fast_replace(p, farmyard=fy), s.players[1]))


def _sheep(s, n):
    p = s.players[0]
    return fast_replace(s, players=(
        fast_replace(p, animals=fast_replace(p.animals, sheep=n)), s.players[1]))


def _gu_legal(s):
    return PlaceWorker(space="grain_utilization") in legal_actions(s)


# ---------------------------------------------------------------------------
# Thresher at the Grain Utilization gate
# ---------------------------------------------------------------------------

def test_sow_route_enables_gu_placement():
    # 0 seeds, an empty field, 1 food, Thresher: buy → sow. Legal.
    s = _grid(_own(_base(), occs=("thresher",)), fields=1)
    s = with_resources(s, 0, food=1, grain=0, veg=0)
    assert _gu_legal(s)


def test_bake_route_enables_gu_placement():
    # 0 seeds, NO field, a Fireplace (baker), 1 food: buy → bake. Legal.
    s = with_majors(_own(_base(), occs=("thresher",)), owner_by_idx={0: 0})
    s = with_resources(s, 0, food=1, grain=0, veg=0)
    assert _gu_legal(s)


def test_bundle_branch_pays_the_buy_by_cooking():
    # 0 food but a cookable sheep (Fireplace): the buy is payable by a raise
    # bundle; the simulated post-bundle post-buy state has the grain + field.
    s = _grid(_own(_base(), occs=("thresher",)), fields=1)
    s = with_majors(s, owner_by_idx={0: 0})
    s = _sheep(with_resources(s, 0, food=0, grain=0, veg=0), 1)
    assert _gu_legal(s)


def test_refused_without_a_use_for_the_grain():
    # 1 food + Thresher but NO field and NO baker: the bought grain enables
    # nothing — refused.
    s = _own(_base(), occs=("thresher",))
    s = with_resources(s, 0, food=1, grain=0, veg=0)
    assert not _gu_legal(s)


def test_refused_when_the_buy_is_unpayable():
    # Field but 0 food and nothing cookable: no payment route — refused.
    s = _grid(_own(_base(), occs=("thresher",)), fields=1)
    s = with_resources(s, 0, food=0, grain=0, veg=0)
    assert not _gu_legal(s)


def test_refused_without_thresher():
    s = _grid(_base(), fields=1)
    s = with_resources(s, 0, food=1, grain=0, veg=0)
    assert not _gu_legal(s)


def test_cultivation_sow_half_and_farmland_non_extension():
    # Every cell a field, no seed, 1 food: plow impossible, base sow seedless —
    # Cultivation legal only via the buy; Farmland (plow-only) stays illegal.
    s = _grid(_own(_base(), occs=("thresher",)), fields=0, fill_rest=True)
    s = with_resources(s, 0, food=1, grain=0, veg=0)
    assert PlaceWorker(space="cultivation") in legal_actions(s)
    assert PlaceWorker(space="farmland") not in legal_actions(s)


def test_ext_only_admission_makes_the_buy_mandatory():
    # Admitted ONLY via the buy: after placing, the sole legal action is the
    # Thresher fire (the ruled behavior — no exit before a sub-action, and no
    # sub-action is choosable pre-buy). After the buy, sow appears.
    s = _grid(_own(_base(), occs=("thresher",)), fields=1)
    s = with_resources(s, 0, food=1, grain=0, veg=0)
    s = step(s, PlaceWorker(space="grain_utilization"))
    acts = legal_actions(s)
    assert acts == [FireTrigger(card_id="thresher")], acts
    s = step(s, acts[0])
    assert ChooseSubAction(name="sow") in legal_actions(s)


# ---------------------------------------------------------------------------
# The Drill Harrow route at the gate, and the two-card composition
# ---------------------------------------------------------------------------

def test_drill_harrow_route_enables_gu_placement():
    # 1 grain, NO field, an empty cell, 3 food, Drill Harrow: choose sow →
    # forced pay-and-plow → sow. Legal at the gate; refused without the card
    # or without the 3rd food (nothing cookable).
    s = _own(_base(), minors=("drill_harrow",))
    s = with_resources(s, 0, food=3, grain=1, veg=0)
    assert _gu_legal(s)
    assert not _gu_legal(with_resources(s, 0, food=2, grain=1, veg=0))
    bare = with_resources(_base(), 0, food=3, grain=1, veg=0)
    assert not _gu_legal(bare)


def test_thresher_x_drill_harrow_priced_exactly():
    # No seed, no field, both cards: the chain costs 1 (buy) + 3 (plow).
    s = _own(_base(), occs=("thresher",), minors=("drill_harrow",))
    assert not _gu_legal(with_resources(s, 0, food=3, grain=0, veg=0))
    assert _gu_legal(with_resources(s, 0, food=4, grain=0, veg=0))


def test_thresher_x_drill_harrow_end_to_end_at_four_food():
    s = _own(_base(), occs=("thresher",), minors=("drill_harrow",))
    s = with_resources(s, 0, food=4, grain=0, veg=0)
    s = step(s, PlaceWorker(space="grain_utilization"))
    acts = legal_actions(s)
    assert acts == [FireTrigger(card_id="thresher")], acts   # mandatory buy
    s = step(s, acts[0])                                     # 4→3 food, +1 grain
    s = step(s, ChooseSubAction(name="sow"))                 # via the DH route
    assert isinstance(s.pending_stack[-1], PendingSow)
    acts = legal_actions(s)
    assert acts == [FireTrigger(card_id="drill_harrow")], acts   # forced plow
    s = step(s, acts[0])                                     # 3→0 food, plow pushed
    assert isinstance(s.pending_stack[-1], PendingPlow)
    plow = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plow[0])
    while not isinstance(s.pending_stack[-1], PendingSow):
        s = step(s, Stop())                                  # close the plow frame
    sows = [a for a in legal_actions(s) if isinstance(a, CommitSow)]
    assert sows and sows[0].grain == 1, sows                 # the bought grain
    s = step(s, sows[0])
    p = s.players[0]
    assert p.resources.food == 0 and p.resources.grain == 0
