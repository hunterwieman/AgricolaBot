"""Tests for Rocky Terrain (minor improvement, C80; Corbarius Expansion).

Card text: "Each time you plow a field (tile or card), you can also buy 1 stone
for 1 food."

Implemented as an OPTIONAL, declinable `after_plow` FireTrigger: in the
after-phase of every PendingPlow commit (one per field plowed) the plowing owner
may fire the trigger to buy +1 stone for 1 food, with `Stop` as the decline.
Drives the reward through the real engine plow flow (Farmland / Cultivation
placement -> ChooseSubAction("plow") -> CommitPlow -> after-phase), not by poking
frames. The 1-food cost is liquidation-aware (food may be raised by converting
crops/animals via a PendingFoodPayment).
"""
import agricola.cards.rocky_terrain  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitFoodPayment,
    CommitPlow,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS, FOOD_PAYMENT_RESUMES
from agricola.cards.triggers import TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment, PendingPlow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("rocky_terrain",) + tuple(f"m{i}" for i in range(20)),
)

_HEARTH_IDX = 2   # a Cooking Hearth (grain/veg -> food; see cooking_rates)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(s, current_player=0), 0


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _num_fields(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type == CellType.FIELD)


def _reveal(state, space_id):
    sp = fast_replace(get_space(state.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _plow_to_after_phase(state, idx, row, col):
    """Place at Farmland, choose plow, commit the space's own plow -> the
    PendingPlow is now in its AFTER phase (where Rocky Terrain's trigger lives)."""
    state = _reveal(state, "farmland")
    state = step(state, PlaceWorker(space="farmland"))
    state = step(state, ChooseSubAction(name="plow"))
    state = step(state, CommitPlow(row=row, col=col))
    assert isinstance(state.pending_stack[-1], PendingPlow)
    assert state.pending_stack[-1].phase == "after"
    return state


def _commit_food_payment(state, **consumed):
    want = CommitFoodPayment(
        grain=consumed.get("grain", 0), veg=consumed.get("veg", 0),
        sheep=consumed.get("sheep", 0), boar=consumed.get("boar", 0),
        cattle=consumed.get("cattle", 0),
    )
    assert want in legal_actions(state), f"{want!r} not among {legal_actions(state)!r}"
    return step(state, want)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

def test_registers_minor_with_food_cost():
    assert "rocky_terrain" in MINORS
    spec = MINORS["rocky_terrain"]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.prereq is None
    assert spec.vps == 0
    assert not spec.passing_left


def test_registers_optional_after_plow_trigger_and_resume():
    entries = [e for e in TRIGGERS.get("after_plow", []) if e.card_id == "rocky_terrain"]
    assert len(entries) == 1
    assert entries[0].mandatory is False          # OPTIONAL / declinable
    assert "rocky_terrain" in FOOD_PAYMENT_RESUMES


# --------------------------------------------------------------------------- #
# The offer in the after-phase
# --------------------------------------------------------------------------- #

def test_offered_after_plow_with_food_on_hand():
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=2)
    s = _plow_to_after_phase(s, cp, 0, 2)
    la = legal_actions(s)
    assert FireTrigger(card_id="rocky_terrain") in la
    # Declinable: Stop is offered alongside (ends the plow without buying).
    assert Stop() in la


def test_offered_via_liquidation():
    # 0 food but 1 grain liquidatable -> 1 food covers the cost.
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=0, grain=1)
    s = _plow_to_after_phase(s, cp, 0, 2)
    assert FireTrigger(card_id="rocky_terrain") in legal_actions(s)


def test_not_offered_when_unaffordable():
    # 0 food and nothing convertible -> cannot pay the 1 food.
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=0, grain=0, veg=0)
    p = s.players[cp]
    s = fast_replace(s, players=tuple(
        fast_replace(p, animals=type(p.animals)()) if i == cp else s.players[i]
        for i in range(2)))
    s = _plow_to_after_phase(s, cp, 0, 2)
    assert FireTrigger(card_id="rocky_terrain") not in legal_actions(s)


def test_not_offered_when_not_owned():
    s, cp = _card_state()
    s = with_resources(s, cp, food=5)             # plenty of food, but no card
    s = _plow_to_after_phase(s, cp, 0, 2)
    assert FireTrigger(card_id="rocky_terrain") not in legal_actions(s)


# --------------------------------------------------------------------------- #
# The reward: +1 stone for 1 food
# --------------------------------------------------------------------------- #

def test_direct_buy_stone_for_food():
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=3, stone=0)
    s = _plow_to_after_phase(s, cp, 0, 2)
    s = step(s, FireTrigger(card_id="rocky_terrain"))
    # No food-payment frame (food on hand); the host PendingPlow is back on top.
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[cp].resources.food == 2      # 3 - 1
    assert s.players[cp].resources.stone == 1     # +1 stone


def test_liquidation_buy_stone():
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=0, grain=1, stone=0)
    s = _plow_to_after_phase(s, cp, 0, 2)
    s = step(s, FireTrigger(card_id="rocky_terrain"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == "rocky_terrain"
    s = _commit_food_payment(s, grain=1)          # 1 grain -> 1 food
    # Resume bought the stone; PendingPlow (after-phase) back on top.
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert s.players[cp].resources.food == 0      # raised 1, paid 1
    assert s.players[cp].resources.grain == 0     # the grain was liquidated
    assert s.players[cp].resources.stone == 1     # +1 stone


# --------------------------------------------------------------------------- #
# Optionality + scoping
# --------------------------------------------------------------------------- #

def test_declining_buys_nothing():
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=3, stone=0)
    s = _plow_to_after_phase(s, cp, 0, 2)
    # Decline: Stop ends the plow without buying.
    s = step(s, Stop())
    assert s.players[cp].resources.food == 3      # unchanged
    assert s.players[cp].resources.stone == 0


def test_fires_once_per_plowed_field():
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=5, stone=0)
    s = _plow_to_after_phase(s, cp, 0, 2)
    s = step(s, FireTrigger(card_id="rocky_terrain"))
    # Back at the after-phase PendingPlow; already fired -> not re-offered.
    assert FireTrigger(card_id="rocky_terrain") not in legal_actions(s)
    assert Stop() in legal_actions(s)


def test_offered_once_per_field_across_a_multi_field_plow():
    """A multi-field plow (Cultivation plows two fields here) offers the buy once
    per field — each field's own PendingPlow after-phase surfaces a fresh trigger."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=5, stone=0)
    s = _reveal(s, "cultivation")
    fields0 = _num_fields(s, cp)
    s = step(s, PlaceWorker(space="cultivation"))
    s = step(s, ChooseSubAction(name="plow"))
    # First plowed field's after-phase: buy stone #1.
    s = step(s, CommitPlow(row=0, col=2))
    assert isinstance(s.pending_stack[-1], PendingPlow)
    assert FireTrigger(card_id="rocky_terrain") in legal_actions(s)
    s = step(s, FireTrigger(card_id="rocky_terrain"))
    assert s.players[cp].resources.stone == 1
    s = step(s, Stop())                           # pop the first PendingPlow
    # Plow a second field -> a fresh PendingPlow -> the trigger is offered again.
    s = step(s, ChooseSubAction(name="plow"))
    s = step(s, CommitPlow(row=0, col=3))
    assert FireTrigger(card_id="rocky_terrain") in legal_actions(s)
    s = step(s, FireTrigger(card_id="rocky_terrain"))
    assert s.players[cp].resources.stone == 2     # +1 per plowed field
    assert _num_fields(s, cp) == fields0 + 2
    assert s.players[cp].resources.food == 3      # 5 - 2 (one food per buy)


def test_no_plow_no_offer():
    """A non-plow turn never surfaces the trigger (no after_plow event)."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=5)
    s = _reveal(s, "forest")
    s = step(s, PlaceWorker(space="forest"))      # atomic wood space, no plow
    while s.pending_stack:
        assert FireTrigger(card_id="rocky_terrain") not in legal_actions(s)
        s = step(s, Stop())
