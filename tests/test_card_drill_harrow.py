"""Focused tests for Drill Harrow (minor D17): the seed-reserving stranding guard.

Card text: "Each time before you take an unconditional 'Sow' action, you can pay 3 food
to plow 1 field." — a `before_sow` pay-food → plow trigger (Ox Goad shape).

The stranding bug these tests pin down (T2): the trigger fires in the before-phase of a
PendingSow whose only legal actions are FireTrigger + CommitSow (no Stop) — so the sow is
MANDATORY and needs >= 1 seed (grain OR veg) left. A plain liquidation-affordability check
would raise the 3 food by burning the player's LAST seed, stranding the forced sow (empty
legal set on a non-empty stack). Eligibility must therefore require the 3 food to be
raisable while RESERVING one seed (grain or veg).
"""
from __future__ import annotations

from agricola.actions import ChooseSubAction, CommitSow, FireTrigger, PlaceWorker, Stop
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlow, PendingSow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("drill_harrow",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _reveal(state, space_id):
    sp = fast_replace(get_space(state.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _to_before_sow(s, cp, *, food, grain=1, veg=0):
    """Place at Grain Utilization, choose sow → PendingSow in its before-phase, with a
    plowable EMPTY cell and a FIELD to sow into. `grain`/`veg` are the TOTAL seeds on hand
    (all of the seed pool, none pre-reserved), `food` the food on hand."""
    p = s.players[cp]
    grid = [[c for c in row] for row in p.farmyard.grid]
    grid[1][0] = Cell(cell_type=CellType.FIELD)   # empty field to sow into
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    s = fast_replace(s, players=tuple(
        fast_replace(p, farmyard=fy) if i == cp else s.players[i] for i in range(2)))
    s = with_resources(s, cp, food=food, grain=grain, veg=veg)
    s = _reveal(s, "grain_utilization")
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, ChooseSubAction(name="sow"))
    assert isinstance(s.pending_stack[-1], PendingSow)
    assert s.pending_stack[-1].phase == "before"
    return s


# ---------------------------------------------------------------------------
# Timing + registration + not-owned coverage
# ---------------------------------------------------------------------------

def test_drill_harrow_registered_on_before_sow():
    assert "drill_harrow" in {e.card_id for e in TRIGGERS.get("before_sow", [])}


def test_drill_harrow_not_offered_when_not_owned():
    s, cp = _card_state()                                   # do NOT own drill_harrow
    s = _to_before_sow(s, cp, food=5, grain=3)
    assert FireTrigger(card_id="drill_harrow") not in legal_actions(s)


# ---------------------------------------------------------------------------
# The stranding guard (T2)
# ---------------------------------------------------------------------------

def test_drill_harrow_not_offered_when_paying_strands_the_sow():
    """3 grain / 0 veg / 0 food, no animals: paying 3 food forces burning ALL 3 grain,
    leaving the mandatory sow with no seed. The trigger must NOT be offered."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=0, grain=3, veg=0)
    # sanity: without the trigger, the sow is legal (>=1 seed on hand)
    assert any(isinstance(a, CommitSow) for a in legal_actions(s))
    # but firing would burn every seed, so the trigger is withheld
    assert FireTrigger(card_id="drill_harrow") not in legal_actions(s)


def test_drill_harrow_not_offered_when_paying_strands_veg_only_sow():
    """3 veg / 0 grain / 0 food, no animals: symmetric — paying 3 food burns all 3 veg,
    stranding a veg-only sow. Not offered."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=0, grain=0, veg=3)
    assert any(isinstance(a, CommitSow) for a in legal_actions(s))
    assert FireTrigger(card_id="drill_harrow") not in legal_actions(s)


def test_drill_harrow_offered_with_food_on_hand_seed_survives():
    """3 food outright + 1 grain: no seed is spent to raise the food, so the sow survives.
    Offered; after firing + plowing, CommitSow(grain=1) is still legal."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=3, grain=1)
    assert FireTrigger(card_id="drill_harrow") in legal_actions(s)
    s = step(s, FireTrigger(card_id="drill_harrow"))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    plows = [a for a in legal_actions(s)]
    s = step(s, next(a for a in plows if a.__class__.__name__ == "CommitPlow"))
    s = step(s, Stop())                                     # pop the plow after-phase
    # back at the (still-mandatory) sow, with the reserved grain seed intact
    assert isinstance(s.pending_stack[-1], PendingSow)
    assert CommitSow(grain=1, veg=0) in legal_actions(s)


def test_drill_harrow_offered_via_liquidation_when_a_seed_is_spare():
    """0 food, 4 grain: 3 grain liquidate to 3 food while RESERVING 1 grain for the sow.
    Offered; after firing + paying + plowing, CommitSow(grain=1) is still legal."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=0, grain=4, veg=0)
    assert FireTrigger(card_id="drill_harrow") in legal_actions(s)
    s = step(s, FireTrigger(card_id="drill_harrow"))
    # a raise-only PendingFoodPayment; pay by burning 3 of the 4 grain
    from agricola.actions import CommitFoodPayment
    pay = CommitFoodPayment(grain=3, veg=0, sheep=0, boar=0, cattle=0)
    assert pay in legal_actions(s), f"{pay!r} not in {legal_actions(s)!r}"
    s = step(s, pay)
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[cp].resources.grain == 1              # reserved seed intact
    s = step(s, next(a for a in legal_actions(s) if a.__class__.__name__ == "CommitPlow"))
    s = step(s, Stop())                                     # pop the plow after-phase
    assert isinstance(s.pending_stack[-1], PendingSow)
    assert CommitSow(grain=1, veg=0) in legal_actions(s)


def test_drill_harrow_offered_via_liquidation_reserving_veg():
    """0 food, 3 grain + 1 veg: raise 3 food from the 3 grain while reserving the 1 veg for
    the sow. Offered; the veg seed survives, so CommitSow(veg=1) is still legal."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=0, grain=3, veg=1)
    assert FireTrigger(card_id="drill_harrow") in legal_actions(s)
    s = step(s, FireTrigger(card_id="drill_harrow"))
    from agricola.actions import CommitFoodPayment
    pay = CommitFoodPayment(grain=3, veg=0, sheep=0, boar=0, cattle=0)
    assert pay in legal_actions(s), f"{pay!r} not in {legal_actions(s)!r}"
    s = step(s, pay)
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[cp].resources.veg == 1                # reserved seed intact
    s = step(s, next(a for a in legal_actions(s) if a.__class__.__name__ == "CommitPlow"))
    s = step(s, Stop())                                     # pop the plow after-phase
    assert isinstance(s.pending_stack[-1], PendingSow)
    assert CommitSow(grain=0, veg=1) in legal_actions(s)


def test_drill_harrow_not_offered_when_truly_unaffordable():
    """0 food, 1 grain: even burning the only seed makes 1 food < 3 — unaffordable AND
    would strand. Not offered."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=0, grain=1, veg=0)
    assert FireTrigger(card_id="drill_harrow") not in legal_actions(s)
