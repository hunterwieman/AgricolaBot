"""Regression — Drill Harrow's raise-frame preserve filter (ruling 87, 2026-07-29).

The executed soft-lock this pins (found by red-team probe, reproduced on the real
engine 2026-07-29): eligibility's seed-reservation was an EXISTS check ("some
seed-preserving bundle can raise the 3 food") but the raise frame filtered NOTHING,
so with 1 grain / 2 sheep / a Fireplace / 0 food the menu offered BOTH Pareto
bundles — {2 sheep} (keeps the seed) and {grain + 1 sheep} (burns it). Picking the
burning one paid the fee, plowed, and returned to the mandatory no-exit sow frame
with zero seeds: an empty legal set on a non-empty stack.

The fix is the preserve pair: `register_food_payment_preserve("drill_harrow",
_preserve_sow)` — the same check eligibility runs — so the menu offers exactly the
sow-preserving bundles.
"""
from __future__ import annotations

import agricola.cards  # noqa: F401  -- populate the registries

from agricola.actions import (
    ChooseSubAction,
    CommitFoodPayment,
    FireTrigger,
    PlaceWorker,
)
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment, PendingSow
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_majors, with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("drill_harrow",) + tuple(f"m{i}" for i in range(20)),
)


def _sow_frame_state(*, food, grain, veg, sheep):
    """A Cards-mode state paused in PendingSow's before-phase at Grain Utilization:
    Drill Harrow owned, one empty field to sow into, empty cells to plow, a
    Fireplace (sheep cookable at 2), and the given goods."""
    s, _env = setup_env(5, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    p = s.players[0]
    s = fast_replace(s, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {"drill_harrow"})
        if i == 0 else s.players[i] for i in range(2)))
    p = s.players[0]
    grid = [[c for c in row] for row in p.farmyard.grid]
    grid[1][0] = Cell(cell_type=CellType.FIELD)          # empty field to sow into
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    s = fast_replace(s, players=tuple(
        fast_replace(p, farmyard=fy) if i == 0 else s.players[i] for i in range(2)))
    s = with_resources(s, 0, food=food, grain=grain, veg=veg)
    p = s.players[0]
    s = fast_replace(s, players=tuple(
        fast_replace(p, animals=fast_replace(p.animals, sheep=sheep))
        if i == 0 else s.players[i] for i in range(2)))
    s = with_majors(s, owner_by_idx={0: 0})              # Fireplace
    sp = fast_replace(get_space(s.board, "grain_utilization"),
                      revealed=True, workers=(0, 0))
    s = fast_replace(s, board=with_space(s.board, "grain_utilization", sp))
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, ChooseSubAction(name="sow"))
    assert isinstance(s.pending_stack[-1], PendingSow)
    return s


def test_seed_burning_bundle_is_filtered_and_the_sow_survives():
    """The repro scenario: the {grain + sheep} bundle must NOT be offered; the
    {2 sheep} bundle must be; taking it leaves the mandatory sow completable."""
    s = _sow_frame_state(food=0, grain=1, veg=0, sheep=2)
    fire = [a for a in legal_actions(s)
            if isinstance(a, FireTrigger) and a.card_id == "drill_harrow"]
    assert fire, "Drill Harrow not offered (a preserving bundle exists — {2 sheep})"
    s = step(s, fire[0])
    assert isinstance(s.pending_stack[-1], PendingFoodPayment)
    menu = [a for a in legal_actions(s) if isinstance(a, CommitFoodPayment)]
    assert menu, "raise frame offered no bundles"
    assert all(b.grain == 0 and b.veg == 0 for b in menu), (
        f"a seed-burning bundle survived the preserve filter: {menu}")
    s = step(s, menu[0])                                  # the sheep-only bundle
    # The resume plowed; walk the plow frame to its Stop, back onto the sow frame.
    while not isinstance(s.pending_stack[-1], PendingSow):
        s = step(s, legal_actions(s)[0])
    acts = legal_actions(s)
    assert acts, "mandatory sow stranded — the preserve filter failed"
    assert any(getattr(a, "grain", 0) >= 1 for a in acts), (
        f"the surviving seed is not sowable: {acts}")


def test_not_offered_when_every_bundle_burns_the_seed():
    """1 grain, 1 sheep, 0 food: raising 3 needs grain(1)+sheep(2) — the only
    bundle burns the last seed, so no preserving route exists and the trigger
    must not be offered (the pre-fix eligibility verdict, preserved)."""
    s = _sow_frame_state(food=0, grain=1, veg=0, sheep=1)
    fire = [a for a in legal_actions(s)
            if isinstance(a, FireTrigger) and a.card_id == "drill_harrow"]
    assert not fire, "offered a fire whose every payment strands the sow"
