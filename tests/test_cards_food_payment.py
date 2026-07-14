"""Tests for the card-game food-payment / at-any-time liquidation slice
(FOOD_PAYMENT_DESIGN.md): paying a food cost by converting crops/animals to food
mid-turn, via the PendingFoodPayment frame pushed at execution when food is short.

Covered:
  - Affordability gate: a food-cost card playable ONLY via liquidation is offered;
    a food-short-and-truly-unaffordable one is not (`_liquidatable_to`).
  - reserved_animals: liquidation does not double-spend an animal the cost needs.
  - Gate↔frontier agreement: the offered card yields a non-empty CommitFoodPayment
    frontier at PendingFoodPayment.
  - Skip-when-sufficient: a food-rich play debits food directly, no frame pushed.
  - Execution + banking (§7): grain-exact, animal-with-banked-overshoot.
  - Resume integrity: Shifting Cultivation's pushed plow lands after a
    liquidation-paid play; a traveling minor still passes; an occupation plays.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitAccommodate,
    CommitFoodPayment,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.constants import HouseMaterial
from agricola.cost import CostCtx
from agricola.engine import step
from agricola.legality import (
    can_pay, legal_actions, legal_placements, playable_minors,
)
from agricola.pending import (
    PendingCattleMarket, PendingFoodPayment, PendingPlayMinor, PendingPlow,
)
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_animals, with_majors, with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=("consultant", "priest", "roof_ballaster")
    + tuple(f"o{i}" for i in range(20)),
    minors=("shifting_cultivation", "market_stall", "ox_goad")
    + tuple(f"m{i}" for i in range(20)),
)


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type.name == "FIELD")

_HEARTH_IDX = 2   # a Cooking Hearth (sheep -> 2 food); see cooking_rates


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return cs, cs.current_player


def _give_minor(state, cp, card_id):
    p = fast_replace(state.players[cp],
                     hand_minors=state.players[cp].hand_minors | {card_id})
    return fast_replace(state, players=tuple(
        p if i == cp else state.players[i] for i in range(2)))


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _drive_to_play_minor(state, cp, card_id):
    """Place at the improvement space and choose play-minor, leaving PendingPlayMinor on
    top (the commit not yet taken)."""
    state = _reveal_improvement_space(_give_minor(state, cp, card_id))
    state = step(state, PlaceWorker(space="major_improvement"))
    state = step(state, ChooseSubAction(name="improvement"))
    state = step(state, ChooseSubAction(name="play_minor"))
    assert isinstance(state.pending_stack[-1], PendingPlayMinor)
    return state


def _commit_food_payment(state, **consumed):
    """Step the unique CommitFoodPayment matching the given consumed goods."""
    want = CommitFoodPayment(
        grain=consumed.get("grain", 0), veg=consumed.get("veg", 0),
        sheep=consumed.get("sheep", 0), boar=consumed.get("boar", 0),
        cattle=consumed.get("cattle", 0),
    )
    opts = [a for a in legal_actions(state) if a == want]
    assert opts, f"{want!r} not among {legal_actions(state)!r}"
    return step(state, want)


# ---------------------------------------------------------------------------
# Affordability gate
# ---------------------------------------------------------------------------

def test_food_minor_offered_only_when_liquidatable():
    # Shifting Cultivation costs 2 food. With 0 food + 2 grain it is playable
    # (liquidate 2 grain); with 0 food + 1 grain it is NOT (max 1 < 2).
    cs, cp = _card_state()
    cs = _give_minor(cs, cp, "shifting_cultivation")

    cs2 = with_resources(cs, cp, grain=2)
    assert "shifting_cultivation" in playable_minors(cs2, cp)

    cs1 = with_resources(cs, cp, grain=1)
    assert "shifting_cultivation" not in playable_minors(cs1, cp)

    cs0 = with_resources(cs, cp, food=0)   # nothing convertible
    assert "shifting_cultivation" not in playable_minors(cs0, cp)


def test_animals_count_as_liquidation_fuel_only_with_a_hearth():
    # 0 food, 1 sheep, no grain/veg. Sheep convert to food only with a cooking
    # improvement (cooking_rates), so Shifting Cultivation (2 food) is playable WITH a
    # hearth (1 sheep -> 2 food) and NOT without one.
    cs, cp = _card_state()
    cs = with_animals(_give_minor(cs, cp, "shifting_cultivation"), cp, sheep=1)
    cs = with_resources(cs, cp, food=0)
    cs_for = with_resources(cs, cp, food=0)  # reset already-zero resources for clarity

    assert "shifting_cultivation" not in playable_minors(cs_for, cp)   # no hearth
    cs_hearth = with_majors(cs_for, owner_by_idx={_HEARTH_IDX: cp})
    assert "shifting_cultivation" in playable_minors(cs_hearth, cp)


def test_reserved_goods_excluded_from_conversion_frontier():
    # The execution-time no-double-spend: a PendingFoodPayment that reserves 1 grain (a good
    # the resumed action will itself debit) must NOT offer to convert that grain, even though
    # 1 grain could make the 1 food owed. With 0 food / 1 grain / 1 sheep + a hearth, the only
    # legal conversion cooks the sheep; the reserved grain is never offered as fuel.
    cs, cp = _card_state()
    cs = with_majors(with_animals(cs, cp, sheep=1), owner_by_idx={_HEARTH_IDX: cp})
    cs = with_resources(cs, cp, food=0, grain=1)
    frame = PendingFoodPayment(
        player_idx=cp, food_needed=1, resume_kind="rerun",
        reserved=Cost(resources=Resources(grain=1)),
    )
    cs = fast_replace(cs, pending_stack=(frame,))
    opts = legal_actions(cs)
    assert opts and all(isinstance(a, CommitFoodPayment) for a in opts)
    assert all(a.grain == 0 for a in opts)      # reserved grain never spent
    assert any(a.sheep == 1 for a in opts)      # the sheep is the only fuel


def test_reserved_animals_not_double_spent_as_liquidation_fuel():
    # A hypothetical minor costing 1 food + 1 sheep, paid by a player with 0 food and
    # exactly 1 sheep + a hearth. The sheep is needed for the cost, so it CANNOT also be
    # cooked to raise the 1 food: reserving it makes the cost unpayable. Without the
    # reservation (no animal cost) the same sheep IS liquidation fuel and it is payable.
    cs, cp = _card_state()
    cs = with_majors(with_animals(cs, cp, sheep=1), owner_by_idx={_HEARTH_IDX: cp})
    cs = with_resources(cs, cp, food=0)

    reserved = CostCtx("play_minor", Resources(food=1),
                       reserved_animals=Animals(sheep=1))
    free = CostCtx("play_minor", Resources(food=1))
    assert not can_pay(cs, cp, reserved)   # sheep reserved for the cost -> no fuel left
    assert can_pay(cs, cp, free)           # sheep free -> cook it for the food


# ---------------------------------------------------------------------------
# Skip-when-sufficient
# ---------------------------------------------------------------------------

def test_skip_when_food_sufficient_pushes_no_frame():
    # 5 food: Shifting Cultivation pays food directly; on_play's PendingPlow is on top,
    # never a PendingFoodPayment.
    cs, cp = _card_state()
    cs = with_resources(cs, cp, food=5)
    cs = _drive_to_play_minor(cs, cp, "shifting_cultivation")
    cs = step(cs, sole_play_minor(cs, "shifting_cultivation"))
    assert isinstance(cs.pending_stack[-1], PendingPlow)
    assert not any(isinstance(f, PendingFoodPayment) for f in cs.pending_stack)
    assert cs.players[cp].resources.food == 3


# ---------------------------------------------------------------------------
# Execution + banking + resume
# ---------------------------------------------------------------------------

def test_grain_liquidation_pays_exact_and_resumes_plow():
    # 0 food, 2 grain. Playing Shifting Cultivation pushes PendingFoodPayment(2); the only
    # frontier point consumes 2 grain; paying lands the pushed plow and passes the card.
    cs, cp = _card_state()
    cs = with_resources(cs, cp, grain=2)
    fields0 = sum(1 for r in range(3) for c in range(5)
                  if cs.players[cp].farmyard.grid[r][c].cell_type.name == "FIELD")
    cs = _drive_to_play_minor(cs, cp, "shifting_cultivation")
    cs = step(cs, sole_play_minor(cs, "shifting_cultivation"))

    # Gate↔frontier agreement: a non-empty CommitFoodPayment frontier.
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 2 and top.resume_kind == "rerun"
    assert top.action.card_id == "shifting_cultivation"
    opts = legal_actions(cs)
    assert opts and all(isinstance(a, CommitFoodPayment) for a in opts)

    cs = _commit_food_payment(cs, grain=2)
    # Food raised (2) then debited (2) -> 0; grain spent; plow pushed (resume); card passed.
    assert cs.players[cp].resources.food == 0
    assert cs.players[cp].resources.grain == 0
    assert isinstance(cs.pending_stack[-1], PendingPlow)
    assert isinstance(cs.pending_stack[-2], PendingPlayMinor)
    # Deferred after-flip (user ruling 2026-07-14): the host flips only once the
    # resumed plow resolves.
    assert cs.pending_stack[-2].phase == "before"
    assert cs.pending_stack[-2].effect_initiated

    cs = step(cs, legal_actions(cs)[0])   # commit the granted plow
    fields1 = sum(1 for r in range(3) for c in range(5)
                  if cs.players[cp].farmyard.grid[r][c].cell_type.name == "FIELD")
    assert fields1 == fields0 + 1
    assert "shifting_cultivation" in cs.players[1 - cp].hand_minors


def test_animal_liquidation_banks_overshoot_on_occupation():
    # 2nd occupation costs 1 food. With 0 food + 1 sheep + a hearth (sheep -> 2), the only
    # frontier point cooks the sheep: produced 2, pay 1, BANK 1 (§7 animal-with-banking).
    cs, cp = _card_state()
    p = fast_replace(cs.players[cp],
                     occupations=frozenset({"priest"}),
                     hand_occupations=frozenset({"consultant"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_majors(with_animals(cs, cp, sheep=1), owner_by_idx={_HEARTH_IDX: cp})
    cs = with_resources(cs, cp, food=0)
    # (resources reset zeroed food; sheep/hearth set above survive — animals/board untouched)

    assert "lessons" in {a.space for a in legal_placements(cs)}
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))

    top = cs.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == "rerun"
    assert top.action.card_id == "consultant"

    cs = _commit_food_payment(cs, sheep=1)
    p = cs.players[cp]
    assert p.resources.food == 1          # produced 2, paid 1, banked 1
    assert p.animals.sheep == 0
    assert p.resources.clay == 3          # consultant on_play ran (resume body)
    assert "consultant" in p.occupations


# ---------------------------------------------------------------------------
# Roof Ballaster — surcharge on the variant (FOOD_PAYMENT_DESIGN.md §8)
# ---------------------------------------------------------------------------

def _play_roof_ballaster_setup(seed, *, occupations, food, grain=0):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     occupations=frozenset(occupations),
                     hand_occupations=frozenset({"roof_ballaster"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_resources(cs, cp, food=food, grain=grain)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    return cs, cp


def test_roof_ballaster_pay_not_offered_when_total_unaffordable():
    # 2nd occupation: base play cost 1 food. "pay" adds a 1-food surcharge -> 2 food total.
    # With exactly 1 food and nothing convertible, "pay" must NOT be offered — the fix for
    # the latent "offer pay (food>=1), then on_play debits another food -> negative" bug.
    cs, cp = _play_roof_ballaster_setup(5, occupations={"priest"}, food=1)
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="roof_ballaster", variant="decline") in la
    assert CommitPlayOccupation(card_id="roof_ballaster", variant="pay") not in la


def test_roof_ballaster_pay_via_liquidation_banks_nothing():
    # 2nd occupation (1 food) + pay surcharge (1 food) = 2 food, paid from 1 food + 1 grain:
    # PendingFoodPayment raises the shortfall, the stone is granted, food ends at 0.
    cs, cp = _play_roof_ballaster_setup(5, occupations={"priest"}, food=1, grain=1)
    rooms = sum(1 for r in range(3) for c in range(5)
                if cs.players[cp].farmyard.grid[r][c].cell_type.name == "ROOM")
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="roof_ballaster", variant="pay") in la

    cs = step(cs, CommitPlayOccupation(card_id="roof_ballaster", variant="pay"))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 2 and top.resume_kind == "rerun"
    assert top.action.variant == "pay"

    cs = _commit_food_payment(cs, grain=1)            # owe 1: 1 grain -> 1 food
    p = cs.players[cp]
    assert p.resources.food == 0                      # 1 + 1 produced - 2 debited
    assert p.resources.grain == 0
    assert p.resources.stone == rooms                 # benefit granted (no extra food debit)
    assert "roof_ballaster" in p.occupations


def test_roof_ballaster_pay_still_direct_when_food_sufficient():
    # Regression: with ample food the pay variant debits directly (base 0 for the 1st
    # occupation + 1 surcharge = 1), grants stone, pushes no PendingFoodPayment.
    cs, cp = _play_roof_ballaster_setup(5, occupations=set(), food=3)
    rooms = sum(1 for r in range(3) for c in range(5)
                if cs.players[cp].farmyard.grid[r][c].cell_type.name == "ROOM")
    cs = step(cs, CommitPlayOccupation(card_id="roof_ballaster", variant="pay"))
    assert not any(isinstance(f, PendingFoodPayment) for f in cs.pending_stack)
    p = cs.players[cp]
    assert p.resources.food == 2                      # 3 - 1 surcharge
    assert p.resources.stone == rooms


# ---------------------------------------------------------------------------
# Ox Goad — pay 2 food from a TRIGGER, then plow (FOOD_PAYMENT_DESIGN.md §8)
# ---------------------------------------------------------------------------

def _cattle_market_after_phase(seed=5, *, food=0, grain=0, own_ox_goad=True):
    """Card-mode state: Cattle Market revealed + stocked with 1 cattle, P0 active and
    (optionally) owning Ox Goad, driven to the market's after-phase (post-accommodate),
    where any after_action_space trigger (Ox Goad) is surfaced."""
    s, _env = setup_env(seed, card_pool=_POOL)
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, "cattle_market")
    s = fast_replace(s, board=with_space(s.board, "cattle_market",
                                         fast_replace(sp, revealed=True, accumulated_amount=1)))
    mins = s.players[0].minor_improvements | ({"ox_goad"} if own_ox_goad else set())
    p = fast_replace(s.players[0], minor_improvements=mins)
    s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    s = with_resources(s, 0, food=food, grain=grain)
    s = step(s, PlaceWorker(space="cattle_market"))
    s = step(s, CommitAccommodate(sheep=0, boar=0, cattle=1))   # keep the cattle (house pet)
    assert isinstance(s.pending_stack[-1], PendingCattleMarket)
    return s


def test_ox_goad_offered_when_food_on_hand_and_plow_legal():
    s = _cattle_market_after_phase(food=2)
    assert FireTrigger(card_id="ox_goad") in legal_actions(s)


def test_ox_goad_offered_via_liquidation():
    s = _cattle_market_after_phase(food=0, grain=2)
    assert FireTrigger(card_id="ox_goad") in legal_actions(s)


def test_ox_goad_not_offered_when_two_food_unaffordable():
    s = _cattle_market_after_phase(food=1, grain=0)   # owe 1, nothing convertible
    assert FireTrigger(card_id="ox_goad") not in legal_actions(s)


def test_ox_goad_direct_pay_then_plow():
    s = _cattle_market_after_phase(food=3)
    fields0 = _num_fields(s, 0)
    s = step(s, FireTrigger(card_id="ox_goad"))
    assert isinstance(s.pending_stack[-1], PendingPlow)   # no food-payment frame needed
    assert s.players[0].resources.food == 1               # 3 - 2
    s = step(s, legal_actions(s)[0])                      # commit a plow
    assert _num_fields(s, 0) == fields0 + 1


def test_ox_goad_liquidation_pay_then_plow():
    s = _cattle_market_after_phase(food=0, grain=2)
    fields0 = _num_fields(s, 0)
    s = step(s, FireTrigger(card_id="ox_goad"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 2 and top.resume_kind == "ox_goad"

    s = _commit_food_payment(s, grain=2)                  # raise 2 food from 2 grain
    assert isinstance(s.pending_stack[-1], PendingPlow)   # resume granted the plow
    assert s.players[0].resources.food == 0               # 0 + 2 - 2
    assert s.players[0].resources.grain == 0
    s = step(s, legal_actions(s)[0])                      # commit a plow
    assert _num_fields(s, 0) == fields0 + 1


def test_ox_goad_fires_once_per_use():
    s = _cattle_market_after_phase(food=3)
    s = step(s, FireTrigger(card_id="ox_goad"))           # pushes PendingPlow
    s = step(s, legal_actions(s)[0])                      # CommitPlow -> PendingPlow after-phase
    s = step(s, Stop())                                   # pop PendingPlow
    assert isinstance(s.pending_stack[-1], PendingCattleMarket)
    # Already fired this use: not re-offered, only Stop remains.
    assert FireTrigger(card_id="ox_goad") not in legal_actions(s)
    assert Stop() in legal_actions(s)
