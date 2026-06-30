"""Tests for the pay-food → plow card cluster (PAY_FOOD_PLOW_CARDS.md): cards that
grant an optional plow, paid for (or, for Mole Plow, free) via a trigger, in the Ox Goad
shape (FOOD_PAYMENT_DESIGN.md §8).

Cards covered:
  - Plow Maker (occ D90): before_action_space on Farmland/Cultivation, 1 food.
  - Shifting Cultivator (occ A91): before_action_space on the Forest (atomic, hooked)
    wood-accumulation space, 3 food.
  - Drill Harrow (minor D17): before_sow (every sow unconditional), 3 food.
  - Plow Hero (occ C91): like Plow Maker but only with the FIRST worker placed in a
    round (people_home == people_total − 1), 1 food.
  - Mole Plow (minor C20): the FREE-plow outlier — before_action_space on
    Farmland/Cultivation, no food in the grant; prereq round ≥ 9.

For each pay-food card the checklist (PAY_FOOD_PLOW_CARDS.md): registered; offered with
food on hand; offered via liquidation (0 food + convertible goods → PendingFoodPayment →
pay → plow); NOT offered when no plowable cell; NOT offered when truly unaffordable;
direct-pay path; wrong space/event doesn't fire; once-per-use.
"""
from __future__ import annotations

from agricola.actions import (
    ChooseSubAction,
    CommitFoodPayment,
    CommitPlow,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import MINORS, OCCUPATIONS, FOOD_PAYMENT_RESUMES
from agricola.cards.triggers import TRIGGERS, OWN_ACTION_HOOK_CARDS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingFoodPayment,
    PendingPlow,
    PendingSow,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_animals, with_majors, with_resources

_POOL = CardPool(
    occupations=("plow_maker", "shifting_cultivator", "plow_hero")
    + tuple(f"o{i}" for i in range(20)),
    minors=("drill_harrow", "mole_plow", "market_stall")
    + tuple(f"m{i}" for i in range(20)),
)

_HEARTH_IDX = 2   # a Cooking Hearth (sheep -> 2 food); see cooking_rates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type == CellType.FIELD)


def _fill_grid_no_plow(state, idx):
    """Make every empty cell a FIELD so no plow is legal (`_can_plow` false)."""
    p = state.players[idx]
    grid = [[c for c in row] for row in p.farmyard.grid]
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.EMPTY:
                grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return fast_replace(state, players=tuple(
        fast_replace(p, farmyard=fy) if i == idx else state.players[i] for i in range(2)))


def _reveal(state, space_id):
    sp = fast_replace(get_space(state.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _place_at(state, space_id):
    """Place P0's worker at `space_id` (revealing it first) and return the resulting
    state. For Farmland/Cultivation/Forest, the before_action_space host is now on top."""
    state = _reveal(state, space_id)
    return step(state, PlaceWorker(space=space_id))


def _commit_food_payment(state, **consumed):
    want = CommitFoodPayment(
        grain=consumed.get("grain", 0), veg=consumed.get("veg", 0),
        sheep=consumed.get("sheep", 0), boar=consumed.get("boar", 0),
        cattle=consumed.get("cattle", 0),
    )
    assert want in legal_actions(state), f"{want!r} not among {legal_actions(state)!r}"
    return step(state, want)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_pay_food_plow_cards_registered():
    for cid in ("plow_maker", "shifting_cultivator", "plow_hero"):
        assert cid in OCCUPATIONS
    assert "drill_harrow" in MINORS
    assert MINORS["drill_harrow"].cost == Cost(resources=Resources(wood=1))
    assert "mole_plow" in MINORS
    assert MINORS["mole_plow"].cost == Cost(resources=Resources(wood=3, food=1))
    assert MINORS["mole_plow"].prereq is not None

    bas = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert {"plow_maker", "shifting_cultivator", "plow_hero", "mole_plow"} <= bas
    bsow = {e.card_id for e in TRIGGERS.get("before_sow", [])}
    assert "drill_harrow" in bsow

    # Pay-food cards register a resume; Mole Plow (free) does not.
    for cid in ("plow_maker", "shifting_cultivator", "drill_harrow", "plow_hero"):
        assert cid in FOOD_PAYMENT_RESUMES
    assert "mole_plow" not in FOOD_PAYMENT_RESUMES

    # Forest is atomic → Shifting Cultivator hooks it; the others ride non-atomic spaces.
    assert "shifting_cultivator" in OWN_ACTION_HOOK_CARDS.get("forest", set())


# ---------------------------------------------------------------------------
# Plow Maker — before_action_space on Farmland / Cultivation, 1 food
# ---------------------------------------------------------------------------

def test_plow_maker_offered_with_food_on_hand_and_plow_legal():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_maker")
    s = with_resources(s, cp, food=2)
    s = _place_at(s, "farmland")
    la = legal_actions(s)
    assert FireTrigger(card_id="plow_maker") in la


def test_plow_maker_offered_on_cultivation_too():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_maker")
    s = with_resources(s, cp, food=2, grain=1)   # grain so cultivation has a sow path too
    s = _place_at(s, "cultivation")
    assert FireTrigger(card_id="plow_maker") in legal_actions(s)


def test_plow_maker_offered_via_liquidation():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_maker")
    s = with_resources(s, cp, food=0, grain=1)   # 0 food, 1 grain liquidatable -> 1 food
    s = _place_at(s, "farmland")
    assert FireTrigger(card_id="plow_maker") in legal_actions(s)


def test_plow_maker_not_offered_when_no_plowable_cell():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_maker")
    s = with_resources(s, cp, food=5)
    s = _fill_grid_no_plow(s, cp)                # no EMPTY cell -> _can_plow false
    s = _place_at(s, "farmland")
    # The space's own plow is also impossible, so Farmland auto-resolves to nothing
    # plowable; whatever is legal, the Plow Maker trigger is not.
    assert FireTrigger(card_id="plow_maker") not in legal_actions(s)


def test_plow_maker_not_offered_when_unaffordable():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_maker")
    s = with_resources(s, cp, food=0)            # 0 food, nothing convertible
    s = _place_at(s, "farmland")
    assert FireTrigger(card_id="plow_maker") not in legal_actions(s)


def test_plow_maker_direct_pay_then_plow():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_maker")
    s = with_resources(s, cp, food=3)
    fields0 = _num_fields(s, cp)
    s = _place_at(s, "farmland")
    s = step(s, FireTrigger(card_id="plow_maker"))
    assert isinstance(s.pending_stack[-1], PendingPlow)   # no food-payment frame
    assert s.players[cp].resources.food == 2              # 3 - 1
    # Commit the granted (additional) plow; field count rises.
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    assert _num_fields(s, cp) == fields0 + 1


def test_plow_maker_liquidation_pay_then_plow():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_maker")
    s = with_resources(s, cp, food=0, grain=1)
    fields0 = _num_fields(s, cp)
    s = _place_at(s, "farmland")
    s = step(s, FireTrigger(card_id="plow_maker"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == "plow_maker"
    s = _commit_food_payment(s, grain=1)                  # 1 grain -> 1 food
    assert isinstance(s.pending_stack[-1], PendingPlow)   # resume granted the plow
    assert s.players[cp].resources.food == 0              # raised 1, paid 1
    assert s.players[cp].resources.grain == 0
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    assert _num_fields(s, cp) == fields0 + 1


def test_plow_maker_wrong_space_does_not_fire():
    # Day Laborer (also "each time you use") must NOT trigger Plow Maker.
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_maker")
    s = with_resources(s, cp, food=3)
    s = _place_at(s, "day_laborer")
    assert FireTrigger(card_id="plow_maker") not in legal_actions(s)


def test_plow_maker_fires_once_per_use():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_maker")
    s = with_resources(s, cp, food=3)
    s = _place_at(s, "farmland")
    s = step(s, FireTrigger(card_id="plow_maker"))
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])                                 # commit granted plow -> after-phase
    s = step(s, Stop())                                   # pop the PendingPlow
    # Back at the Farmland host; already fired -> not re-offered.
    assert FireTrigger(card_id="plow_maker") not in legal_actions(s)


# ---------------------------------------------------------------------------
# Shifting Cultivator — before_action_space on Forest (atomic, hooked), 3 food
# ---------------------------------------------------------------------------

def test_shifting_cultivator_offered_on_forest_with_food():
    s, cp = _card_state()
    s = _own_occ(s, cp, "shifting_cultivator")
    s = with_resources(s, cp, food=3)
    s = _place_at(s, "forest")
    assert FireTrigger(card_id="shifting_cultivator") in legal_actions(s)


def test_shifting_cultivator_offered_via_liquidation():
    s, cp = _card_state()
    s = _own_occ(s, cp, "shifting_cultivator")
    s = with_resources(s, cp, food=0, grain=3)   # 3 grain -> 3 food
    s = _place_at(s, "forest")
    assert FireTrigger(card_id="shifting_cultivator") in legal_actions(s)


def test_shifting_cultivator_not_offered_when_unaffordable():
    s, cp = _card_state()
    s = _own_occ(s, cp, "shifting_cultivator")
    s = with_resources(s, cp, food=2, grain=0)   # owe 3, only 2 food, nothing convertible
    s = _place_at(s, "forest")
    assert FireTrigger(card_id="shifting_cultivator") not in legal_actions(s)


def test_shifting_cultivator_not_offered_when_no_plow():
    s, cp = _card_state()
    s = _own_occ(s, cp, "shifting_cultivator")
    s = with_resources(s, cp, food=5)
    s = _fill_grid_no_plow(s, cp)
    s = _place_at(s, "forest")
    assert FireTrigger(card_id="shifting_cultivator") not in legal_actions(s)


def test_shifting_cultivator_wrong_space_does_not_fire():
    # Clay Pit (also an accumulation space, but CLAY not wood) must not trigger it.
    s, cp = _card_state()
    s = _own_occ(s, cp, "shifting_cultivator")
    s = with_resources(s, cp, food=5)
    s = _place_at(s, "clay_pit")
    assert FireTrigger(card_id="shifting_cultivator") not in legal_actions(s)


def test_shifting_cultivator_direct_pay_then_plow():
    s, cp = _card_state()
    s = _own_occ(s, cp, "shifting_cultivator")
    s = with_resources(s, cp, food=4)
    fields0 = _num_fields(s, cp)
    s = _place_at(s, "forest")
    s = step(s, FireTrigger(card_id="shifting_cultivator"))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[cp].resources.food == 1              # 4 - 3
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    assert _num_fields(s, cp) == fields0 + 1


def test_shifting_cultivator_liquidation_pay_then_plow():
    s, cp = _card_state()
    s = _own_occ(s, cp, "shifting_cultivator")
    s = with_resources(s, cp, food=0, grain=3)
    fields0 = _num_fields(s, cp)
    s = _place_at(s, "forest")
    s = step(s, FireTrigger(card_id="shifting_cultivator"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 3 and top.resume_kind == "shifting_cultivator"
    s = _commit_food_payment(s, grain=3)
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[cp].resources.food == 0
    assert s.players[cp].resources.grain == 0
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    assert _num_fields(s, cp) == fields0 + 1


def test_shifting_cultivator_fires_once_per_use():
    s, cp = _card_state()
    s = _own_occ(s, cp, "shifting_cultivator")
    s = with_resources(s, cp, food=4)
    s = _place_at(s, "forest")
    s = step(s, FireTrigger(card_id="shifting_cultivator"))
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    s = step(s, Stop())
    assert FireTrigger(card_id="shifting_cultivator") not in legal_actions(s)


def test_shifting_cultivator_not_owned_forest_stays_atomic():
    # Without the card, Forest is NOT hosted (atomic fast path): placing resolves
    # immediately, no PendingActionSpace frame, no trigger.
    s, cp = _card_state()
    s = with_resources(s, cp, food=5)
    s = _place_at(s, "forest")
    assert not s.pending_stack       # resolved atomically (forest grants wood, no host)


# ---------------------------------------------------------------------------
# Drill Harrow — before_sow, 3 food
# ---------------------------------------------------------------------------

def _to_before_sow(s, cp, *, food, grain_for_sow=1, extra_grain=0, veg=0):
    """Place at Grain Utilization, choose sow → PendingSow in its before-phase, with a
    plowable EMPTY cell and a FIELD to sow. `grain_for_sow` is grain on hand to sow; pass
    `veg` to enable a veg-sow path instead (so 0 grain can be a true unaffordable case)."""
    # A FIELD to sow into (row 1 col 0) and keep some EMPTY cells for the plow grant.
    p = s.players[cp]
    grid = [[c for c in row] for row in p.farmyard.grid]
    grid[1][0] = Cell(cell_type=CellType.FIELD)   # empty field to sow
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    s = fast_replace(s, players=tuple(
        fast_replace(p, farmyard=fy) if i == cp else s.players[i] for i in range(2)))
    s = with_resources(s, cp, food=food, grain=grain_for_sow + extra_grain, veg=veg)
    s = _reveal(s, "grain_utilization")
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, ChooseSubAction(name="sow"))
    assert isinstance(s.pending_stack[-1], PendingSow)
    assert s.pending_stack[-1].phase == "before"
    return s


def test_drill_harrow_offered_before_sow_with_food():
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=3)
    assert FireTrigger(card_id="drill_harrow") in legal_actions(s)


def test_drill_harrow_offered_via_liquidation():
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    # 0 food but extra grain beyond the sow grain is liquidatable to food.
    s = _to_before_sow(s, cp, food=0, grain_for_sow=1, extra_grain=3)
    assert FireTrigger(card_id="drill_harrow") in legal_actions(s)


def test_drill_harrow_not_offered_when_unaffordable():
    # owe 3 food; 0 food and only 1 grain on hand. The grain (even fully liquidated, no
    # reservation at the trigger) makes at most 1 food < 3 -> truly unaffordable.
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=0, grain_for_sow=1, extra_grain=0)
    assert FireTrigger(card_id="drill_harrow") not in legal_actions(s)


def test_drill_harrow_not_offered_when_no_plow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = with_resources(s, cp, food=5, grain=1)
    # Fill all empties to FIELDs, but leave one we'll sow into (row1col0 set by helper).
    s = _fill_grid_no_plow(s, cp)
    # Place + sow: the only FIELD-with-no-crop is plenty; ensure no EMPTY remains to plow.
    s = _reveal(s, "grain_utilization")
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, ChooseSubAction(name="sow"))
    assert FireTrigger(card_id="drill_harrow") not in legal_actions(s)


def test_drill_harrow_direct_pay_then_plow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=4)
    fields0 = _num_fields(s, cp)
    s = step(s, FireTrigger(card_id="drill_harrow"))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[cp].resources.food == 1              # 4 - 3
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    assert _num_fields(s, cp) == fields0 + 1


def test_drill_harrow_liquidation_pay_then_plow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=0, grain_for_sow=1, extra_grain=3)
    fields0 = _num_fields(s, cp)
    s = step(s, FireTrigger(card_id="drill_harrow"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 3 and top.resume_kind == "drill_harrow"
    s = _commit_food_payment(s, grain=3)                  # 3 extra grain -> 3 food
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[cp].resources.food == 0
    assert s.players[cp].resources.grain == 1             # the 1 sow-grain reserved, untouched
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    assert _num_fields(s, cp) == fields0 + 1


def test_drill_harrow_fires_once_per_sow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "drill_harrow")
    s = _to_before_sow(s, cp, food=4)
    s = step(s, FireTrigger(card_id="drill_harrow"))
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    s = step(s, Stop())                                   # pop the granted plow
    # Back at PendingSow before-phase; already fired -> not re-offered.
    assert FireTrigger(card_id="drill_harrow") not in legal_actions(s)


# ---------------------------------------------------------------------------
# Plow Hero — first worker placed in a round only
# ---------------------------------------------------------------------------

def test_plow_hero_offered_on_first_placement():
    # Fresh round: P0 has placed nothing; placing at Farmland is the first worker.
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_hero")
    s = with_resources(s, cp, food=2)
    assert s.players[cp].people_home == s.players[cp].people_total   # nothing placed yet
    s = _place_at(s, "farmland")
    assert FireTrigger(card_id="plow_hero") in legal_actions(s)


def test_plow_hero_not_offered_on_second_placement():
    # Simulate a player who has already placed one worker this round (people_home one
    # below people_total BEFORE this placement). Then Farmland is the SECOND worker.
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_hero")
    s = with_resources(s, cp, food=2)
    p = s.players[cp]
    # Round 2+: 3 workers total, one already placed -> people_home 2 (== total - 1).
    p = fast_replace(p, people_total=3, people_home=2)
    s = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    s = _place_at(s, "farmland")
    # After placing, people_home is 1 = people_total - 2 -> not the first placement.
    assert s.players[cp].people_home == s.players[cp].people_total - 2
    assert FireTrigger(card_id="plow_hero") not in legal_actions(s)


def test_plow_hero_offered_first_placement_with_extra_workers():
    # 3 workers home (a later round), all home: Farmland is the first -> offered.
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_hero")
    s = with_resources(s, cp, food=2)
    p = s.players[cp]
    p = fast_replace(p, people_total=3, people_home=3)
    s = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    s = _place_at(s, "farmland")
    assert s.players[cp].people_home == s.players[cp].people_total - 1
    assert FireTrigger(card_id="plow_hero") in legal_actions(s)


def test_plow_hero_offered_via_liquidation_first_placement():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_hero")
    s = with_resources(s, cp, food=0, grain=1)
    s = _place_at(s, "farmland")
    assert FireTrigger(card_id="plow_hero") in legal_actions(s)


def test_plow_hero_not_offered_unaffordable():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_hero")
    s = with_resources(s, cp, food=0)
    s = _place_at(s, "farmland")
    assert FireTrigger(card_id="plow_hero") not in legal_actions(s)


def test_plow_hero_not_offered_no_plow():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_hero")
    s = with_resources(s, cp, food=5)
    s = _fill_grid_no_plow(s, cp)
    s = _place_at(s, "farmland")
    assert FireTrigger(card_id="plow_hero") not in legal_actions(s)


def test_plow_hero_direct_pay_then_plow():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_hero")
    s = with_resources(s, cp, food=3)
    fields0 = _num_fields(s, cp)
    s = _place_at(s, "farmland")
    s = step(s, FireTrigger(card_id="plow_hero"))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[cp].resources.food == 2              # 3 - 1
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    assert _num_fields(s, cp) == fields0 + 1


def test_plow_hero_liquidation_pay_then_plow():
    s, cp = _card_state()
    s = _own_occ(s, cp, "plow_hero")
    s = with_resources(s, cp, food=0, grain=1)
    fields0 = _num_fields(s, cp)
    s = _place_at(s, "farmland")
    s = step(s, FireTrigger(card_id="plow_hero"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == "plow_hero"
    s = _commit_food_payment(s, grain=1)
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[cp].resources.food == 0
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    assert _num_fields(s, cp) == fields0 + 1


# ---------------------------------------------------------------------------
# Mole Plow — FREE plow grant, prereq round >= 9
# ---------------------------------------------------------------------------

def test_mole_plow_prereq_round9():
    from agricola.cards.specs import prereq_met
    s, cp = _card_state()
    s8 = fast_replace(s, round_number=8)
    s9 = fast_replace(s, round_number=9)
    assert not prereq_met(MINORS["mole_plow"], s8, cp)
    assert prereq_met(MINORS["mole_plow"], s9, cp)


def test_mole_plow_offered_free_on_farmland():
    s, cp = _card_state()
    s = _own_minor(s, cp, "mole_plow")
    s = with_resources(s, cp, food=0)            # FREE plow: no food needed
    s = _place_at(s, "farmland")
    la = legal_actions(s)
    assert FireTrigger(card_id="mole_plow") in la
    # Optional: declining = not firing it. Farmland is a delegating single-sub-action
    # host, so the alternative offered alongside is the space's own plow choice.
    assert ChooseSubAction(name="plow") in la


def test_mole_plow_offered_on_cultivation():
    s, cp = _card_state()
    s = _own_minor(s, cp, "mole_plow")
    s = with_resources(s, cp, food=0, grain=1)
    s = _place_at(s, "cultivation")
    assert FireTrigger(card_id="mole_plow") in legal_actions(s)


def test_mole_plow_not_offered_when_no_plow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "mole_plow")
    s = _fill_grid_no_plow(s, cp)
    s = _place_at(s, "farmland")
    assert FireTrigger(card_id="mole_plow") not in legal_actions(s)


def test_mole_plow_wrong_space_does_not_fire():
    s, cp = _card_state()
    s = _own_minor(s, cp, "mole_plow")
    s = with_resources(s, cp, food=5)
    s = _place_at(s, "forest")
    assert FireTrigger(card_id="mole_plow") not in legal_actions(s)


def test_mole_plow_free_plow_then_plow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "mole_plow")
    s = with_resources(s, cp, food=0)
    fields0 = _num_fields(s, cp)
    food0 = s.players[cp].resources.food
    s = _place_at(s, "farmland")
    s = step(s, FireTrigger(card_id="mole_plow"))
    assert isinstance(s.pending_stack[-1], PendingPlow)   # free: no food-payment frame
    assert s.players[cp].resources.food == food0          # no food debited
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    assert _num_fields(s, cp) == fields0 + 1


def test_mole_plow_fires_once_per_use():
    s, cp = _card_state()
    s = _own_minor(s, cp, "mole_plow")
    s = with_resources(s, cp, food=0)
    s = _place_at(s, "farmland")
    s = step(s, FireTrigger(card_id="mole_plow"))
    plows = [a for a in legal_actions(s) if isinstance(a, CommitPlow)]
    s = step(s, plows[0])
    s = step(s, Stop())
    assert FireTrigger(card_id="mole_plow") not in legal_actions(s)
