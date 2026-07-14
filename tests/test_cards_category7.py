"""Tests for the Category-7 start-of-round cards + Seasonal Worker (Cat 3).

Category 7 rides the preparation ladder's `start_of_round` window (ruling 54,
2026-07-14; `agricola/cards/preparation.py`): the window's auto-effects
(Small-scale Farmer, Scullery) fire mechanically with NO frame; a
`PendingHarvestWindow(window_id="start_of_round")` choice frame is pushed only
for a player with an eligible registered TRIGGER — optional triggers (Plow
Driver, Groom) surface as FireTrigger, the mandatory-with-choice Childless
gates Proceed, and Scholar is the collapsed play-variant trigger.

Seasonal Worker is the mandatory-with-choice trigger on the Day Laborer space-host.

(Firewood Collector — "+1 wood at the end of that turn" — was deferred: its end-of-turn
timing has no correct anchor until "at any time" card effects define a post-action
turn-end window. See CARD_IMPLEMENTATION_PLAN.md.)

Cards are exercised by driving the engine through a placement turn / a constructed
start_of_round window host (mirroring tests/test_cards_category6.py /
_preparation_hook).
"""
from __future__ import annotations

from agricola.actions import (
    CommitCardChoice,
    CommitFoodPayment,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
)
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import CellType, HouseMaterial, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingCardChoice,
    PendingFoodPayment,
    PendingHarvestWindow,
    PendingPlayMinor,
    PendingPlayOccupation,
    PendingPlow,
    push,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup, setup_env
from agricola.state import Cell


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_house(state, idx, material, extra=Resources()):
    p = state.players[idx]
    p = fast_replace(p, house_material=material, resources=p.resources + extra)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_rooms(state, idx, n):
    """Force player `idx` to have exactly `n` ROOM cells (rows 0, cols 0..n-1)."""
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    # Clear any existing rooms first.
    for r in range(3):
        for c in range(5):
            if grid[r][c].cell_type == CellType.ROOM:
                grid[r][c] = Cell(cell_type=CellType.EMPTY)
    for c in range(n):
        grid[0][c] = Cell(cell_type=CellType.ROOM)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _host(state, idx):
    """A WORK state with a start_of_round window choice host for `idx` on top —
    the synthetic-frame idiom: constructed outside the ladder walk (no
    prep_cursor), so popping the frame ends the turn instead of resuming a
    preparation cursor."""
    return push(fast_replace(state, phase=Phase.WORK),
                PendingHarvestWindow(window_id="start_of_round", player_idx=idx))


def _run_turn(state):
    """Step through forced/singleton actions until the worker-turn's stack empties."""
    steps = 0
    while state.pending_stack and steps < 20:
        la = legal_actions(state)
        state = step(state, la[0])
        steps += 1
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_category7_cards_registered():
    for cid in ("small_scale_farmer", "plow_driver", "groom", "childless",
                "scholar", "seasonal_worker"):
        assert cid in OCCUPATIONS
    assert "scullery" in MINORS
    # Scullery's cost (verbatim "1 Wood,1 Clay"); no VPs/prereq/passing.
    assert MINORS["scullery"].cost == Cost(resources=Resources(wood=1, clay=1))
    assert MINORS["scullery"].vps == 0
    assert MINORS["scullery"].passing_left is False
    # Childless / Seasonal Worker are mandatory-tagged triggers.
    so = {e.card_id: e.mandatory for e in TRIGGERS.get("start_of_round", [])}
    assert so["childless"] is True
    assert so["plow_driver"] is False
    # Small-scale Farmer / Scullery are choice-free AUTOS on start_of_round.
    sor_autos = {e.card_id for e in AUTO_EFFECTS.get("start_of_round", ())}
    assert {"small_scale_farmer", "scullery"} <= sor_autos
    # Seasonal Worker is a mandatory "each time you use [space]" grant → before-phase.
    bas = {e.card_id: e.mandatory for e in TRIGGERS.get("before_action_space", [])}
    assert bas["seasonal_worker"] is True
    # Scholar is the play-variant trigger.
    assert "scholar" in PLAY_VARIANT_TRIGGERS


# ---------------------------------------------------------------------------
# Small-scale Farmer — +1 wood at exactly 2 rooms (auto, fired mechanically)
# ---------------------------------------------------------------------------

def test_small_scale_farmer_two_rooms():
    s = _own_occ(setup(0), 0, "small_scale_farmer")
    s = _set_rooms(s, 0, 2)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    before = s.players[0].resources.wood
    after = _complete_preparation(s)
    assert after.players[0].resources.wood == before + 1
    # An auto-only card produces no frame: the ladder completes straight to WORK.
    assert after.pending_stack == ()
    assert after.phase is Phase.WORK


def test_small_scale_farmer_not_two_rooms_no_income():
    s = _own_occ(setup(0), 0, "small_scale_farmer")
    s = _set_rooms(s, 0, 3)   # three rooms → ineligible
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    before = s.players[0].resources.wood
    after = _complete_preparation(s)
    assert after.players[0].resources.wood == before
    # The auto did nothing and no trigger surfaced: no frame, straight to WORK.
    assert after.pending_stack == ()
    assert after.phase is Phase.WORK


# ---------------------------------------------------------------------------
# Scullery — +1 food in a wooden house (auto, fired mechanically)
# ---------------------------------------------------------------------------

def test_scullery_wooden_house():
    s = _own_minor(setup(0), 0, "scullery")   # default house is WOOD
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before + 1
    assert after.pending_stack == ()   # auto-only → no frame


def test_scullery_non_wooden_no_income():
    s = _own_minor(setup(0), 0, "scullery")
    s = _set_house(s, 0, HouseMaterial.CLAY)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=2)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before


# ---------------------------------------------------------------------------
# Plow Driver — optional pay-1-food-plow trigger
# ---------------------------------------------------------------------------

def test_plow_driver_eligible_in_stone_house():
    s = _own_occ(setup(0), 0, "plow_driver")
    s = _set_house(s, 0, HouseMaterial.STONE, extra=Resources(food=2))
    s = _host(s, 0)
    la = legal_actions(s)
    assert FireTrigger(card_id="plow_driver") in la
    assert Proceed() in la   # optional → decline via Proceed
    before = s.players[0].resources.food
    s = step(s, FireTrigger(card_id="plow_driver"))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[0].resources.food == before - 1


def test_plow_driver_not_offered_in_wooden_house():
    s = _own_occ(setup(0), 0, "plow_driver")
    s = _set_house(s, 0, HouseMaterial.WOOD, extra=Resources(food=2))
    s = _host(s, 0)
    assert legal_actions(s) == [Proceed()]


def test_plow_driver_once_per_round():
    s = _own_occ(setup(0), 0, "plow_driver")
    s = _set_house(s, 0, HouseMaterial.STONE, extra=Resources(food=2))
    p = s.players[0]
    p = fast_replace(p, used_this_round=p.used_this_round | {"plow_driver"})
    s = fast_replace(s, players=(p, s.players[1]))
    s = _host(s, 0)
    assert legal_actions(s) == [Proceed()]   # already fired this round


def test_plow_driver_fires_via_liquidation_when_food_short():
    # 0 food but 1 grain: Plow Driver must still be offered (the 1 food is liquidatable),
    # firing pushes a raise-only PendingFoodPayment, and paying it raises the food and plows.
    s = _own_occ(setup(0), 0, "plow_driver")
    p = fast_replace(s.players[0], house_material=HouseMaterial.STONE,
                     resources=Resources(grain=1))   # 0 food, 1 grain
    s = fast_replace(s, players=(p, s.players[1]))
    s = _host(s, 0)
    assert FireTrigger(card_id="plow_driver") in legal_actions(s)

    s = step(s, FireTrigger(card_id="plow_driver"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment) and top.food_needed == 1
    s = step(s, CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0))
    assert isinstance(s.pending_stack[-1], PendingPlow)   # resume debited the food + plowed
    assert s.players[0].resources.food == 0               # raised 1, paid 1
    assert s.players[0].resources.grain == 0
    assert "plow_driver" in s.players[0].used_this_round   # latched once-per-round


def test_plow_driver_not_offered_when_food_short_and_no_fuel():
    # 0 food, nothing convertible -> truly unaffordable -> not offered (regression guard).
    s = _own_occ(setup(0), 0, "plow_driver")
    p = fast_replace(s.players[0], house_material=HouseMaterial.STONE,
                     resources=Resources())
    s = fast_replace(s, players=(p, s.players[1]))
    s = _host(s, 0)
    assert legal_actions(s) == [Proceed()]


# ---------------------------------------------------------------------------
# Groom — on-play +1 wood + optional stable trigger
# ---------------------------------------------------------------------------

def test_groom_on_play_wood():
    s = setup(0)
    before = s.players[0].resources.wood
    s = OCCUPATIONS["groom"].on_play(s, 0)
    assert s.players[0].resources.wood == before + 1


def test_groom_stable_trigger_in_stone_house():
    s = _own_occ(setup(0), 0, "groom")
    s = _set_house(s, 0, HouseMaterial.STONE, extra=Resources(wood=2))
    s = _host(s, 0)
    la = legal_actions(s)
    assert FireTrigger(card_id="groom") in la
    s = step(s, FireTrigger(card_id="groom"))
    from agricola.pending import PendingBuildStables
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildStables)
    assert top.cost == Resources(wood=1) and top.max_builds == 1


def test_groom_not_offered_in_wooden_house():
    s = _own_occ(setup(0), 0, "groom")
    s = _set_house(s, 0, HouseMaterial.WOOD, extra=Resources(wood=2))
    s = _host(s, 0)
    assert legal_actions(s) == [Proceed()]


# ---------------------------------------------------------------------------
# Childless — mandatory-with-choice (gate + crop pick)
# ---------------------------------------------------------------------------

def test_childless_gates_proceed_and_resolves():
    s = _own_occ(setup(0), 0, "childless")
    s = _set_rooms(s, 0, 3)   # >=3 rooms, default 2 people
    s = _host(s, 0)
    # Mandatory → Proceed withheld, only the FireTrigger is legal.
    assert legal_actions(s) == [FireTrigger(card_id="childless")]
    food0 = s.players[0].resources.food
    s = step(s, FireTrigger(card_id="childless"))
    assert s.players[0].resources.food == food0 + 1
    top = s.pending_stack[-1]
    assert isinstance(top, PendingCardChoice) and top.options == ("grain", "veg")
    assert legal_actions(s) == [CommitCardChoice(index=0), CommitCardChoice(index=1)]
    grain0 = s.players[0].resources.grain
    s = step(s, CommitCardChoice(index=0))   # grain
    assert s.players[0].resources.grain == grain0 + 1
    # Gate reopens.
    assert Proceed() in legal_actions(s)


def test_childless_ineligible_with_three_people():
    s = _own_occ(setup(0), 0, "childless")
    s = _set_rooms(s, 0, 3)
    p = s.players[0]
    p = fast_replace(p, people_total=3)   # not "only 2 people"
    s = fast_replace(s, players=(p, s.players[1]))
    s = _host(s, 0)
    assert legal_actions(s) == [Proceed()]


# ---------------------------------------------------------------------------
# Scholar — collapsed play-variant trigger
# ---------------------------------------------------------------------------

def test_scholar_surfaces_play_variants():
    s = _own_occ(setup(0), 0, "scholar")
    s = _set_house(s, 0, HouseMaterial.STONE, extra=Resources(food=2))
    p = s.players[0]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {"consultant"},
                     hand_minors=p.hand_minors | {"market_stall"},
                     resources=p.resources + Resources(grain=1))
    s = fast_replace(s, players=(p, s.players[1]))
    s = _host(s, 0)
    la = legal_actions(s)
    assert FireTrigger(card_id="scholar", variant="occupation") in la
    assert FireTrigger(card_id="scholar", variant="minor") in la
    assert Proceed() in la   # do-neither
    # Occupation route pushes PendingPlayOccupation with the flat 1-food cost.
    s_occ = step(s, FireTrigger(card_id="scholar", variant="occupation"))
    top = s_occ.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation) and top.cost == Resources(food=1)
    # Minor route pushes PendingPlayMinor.
    s_min = step(s, FireTrigger(card_id="scholar", variant="minor"))
    assert isinstance(s_min.pending_stack[-1], PendingPlayMinor)


def test_scholar_not_offered_in_wooden_house():
    s = _own_occ(setup(0), 0, "scholar")
    p = s.players[0]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {"consultant"},
                     resources=p.resources + Resources(food=2))
    s = fast_replace(s, players=(p, s.players[1]))   # wooden house default
    s = _host(s, 0)
    assert legal_actions(s) == [Proceed()]


def test_scholar_occupation_variant_offered_and_paid_via_liquidation():
    # Stone house, a playable occupation in hand, 0 food but 1 grain: the "occupation"
    # variant must be offered (the flat 1-food cost is liquidatable), and playing the
    # occupation raises the food via _execute_play_occupation's shortfall guard.
    s = _own_occ(setup(0), 0, "scholar")
    p = fast_replace(s.players[0], house_material=HouseMaterial.STONE,
                     hand_occupations=s.players[0].hand_occupations | {"consultant"},
                     resources=Resources(grain=1))   # 0 food, 1 grain
    s = fast_replace(s, players=(p, s.players[1]))
    s = _host(s, 0)
    assert FireTrigger(card_id="scholar", variant="occupation") in legal_actions(s)

    s = step(s, FireTrigger(card_id="scholar", variant="occupation"))
    assert isinstance(s.pending_stack[-1], PendingPlayOccupation)
    s = step(s, CommitPlayOccupation(card_id="consultant"))
    # Food short -> the play-occupation guard raised a PendingFoodPayment; pay 1 grain.
    assert isinstance(s.pending_stack[-1], PendingFoodPayment)
    s = step(s, CommitFoodPayment(grain=1, veg=0, sheep=0, boar=0, cattle=0))
    p0 = s.players[0]
    assert "consultant" in p0.occupations      # the occupation was played
    assert p0.resources.food == 0              # raised 1, paid the flat 1-food cost
    assert p0.resources.grain == 0
    assert p0.resources.clay == 3              # consultant's on-play (+3 clay) ran


# ---------------------------------------------------------------------------
# Seasonal Worker — mandatory-with-choice on Day Laborer
# ---------------------------------------------------------------------------

def test_seasonal_worker_round1_grain_only():
    s, env = setup_env(0)
    ap = s.current_player
    s = _own_occ(s, ap, "seasonal_worker")
    g0 = s.players[ap].resources.grain
    f0 = s.players[ap].resources.food
    s = step(s, PlaceWorker(space="day_laborer"))
    s = _run_turn(s)
    # Day Laborer's +2 food and Seasonal Worker's +1 grain (singleton, auto-resolved).
    assert s.players[ap].resources.grain == g0 + 1
    assert s.players[ap].resources.food == f0 + 2


def test_seasonal_worker_round6_offers_veg_choice():
    s, env = setup_env(0)
    ap = s.current_player
    s = _own_occ(s, ap, "seasonal_worker")
    s = fast_replace(s, round_number=6)
    s = step(s, PlaceWorker(space="day_laborer"))
    # Walk to the PendingCardChoice (the gate withholds Stop until it fires).
    seen = None
    steps = 0
    while s.pending_stack and steps < 12:
        top = s.pending_stack[-1]
        if isinstance(top, PendingCardChoice):
            seen = top.options
            v0 = s.players[ap].resources.veg
            s = step(s, CommitCardChoice(index=1))   # veg
            assert s.players[ap].resources.veg == v0 + 1
        else:
            la = legal_actions(s)
            s = step(s, la[0])
        steps += 1
    assert seen == ("grain", "veg")
