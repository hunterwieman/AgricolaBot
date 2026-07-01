"""Tests for Rocky Terrain (minor improvement, C80; Corbarius Expansion).

Card text: "Each time you plow a field (tile or card), you can also buy 1 stone
for 1 food."

Implemented as an OPTIONAL, declinable `before_plow` FireTrigger: by the
Trigger-Timing ruling a bare "each time you plow a field …" fires in the BEFORE
window of the plow (CARD_AUTHORING_GUIDE.md), and the reward is a flat exchange
(buy 1 stone for 1 food) that reads nothing about what was plowed — so `before`,
not `after`. In the before-phase of every PendingPlow (one per field plowed) the
plowing owner may fire the trigger to buy +1 stone for 1 food; the CommitPlow
options remain legal alongside it (firing does not force or strand the plow).
Drives the reward through the real engine plow flow (Farmland / Cultivation
placement -> ChooseSubAction("plow") -> before-phase PendingPlow), not by poking
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
from agricola.state import get_space, with_space
from tests.factories import with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("rocky_terrain",) + tuple(f"m{i}" for i in range(20)),
)


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


def _plow_to_before_phase(state, idx):
    """Place at Farmland, choose plow -> the PendingPlow is now in its BEFORE
    phase (where Rocky Terrain's trigger lives, alongside the CommitPlow options
    that have not yet been taken)."""
    state = _reveal(state, "farmland")
    state = step(state, PlaceWorker(space="farmland"))
    state = step(state, ChooseSubAction(name="plow"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPlow)
    assert top.phase == "before"
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


def test_registers_optional_before_plow_trigger_and_resume():
    # T1 timing fix: the trigger lives on before_plow, NOT after_plow.
    assert not any(e.card_id == "rocky_terrain" for e in TRIGGERS.get("after_plow", []))
    entries = [e for e in TRIGGERS.get("before_plow", []) if e.card_id == "rocky_terrain"]
    assert len(entries) == 1
    assert entries[0].mandatory is False          # OPTIONAL / declinable
    assert "rocky_terrain" in FOOD_PAYMENT_RESUMES


# --------------------------------------------------------------------------- #
# The offer in the BEFORE-phase (before CommitPlow)
# --------------------------------------------------------------------------- #

def test_offered_before_plow_alongside_commit_plow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=2)
    s = _plow_to_before_phase(s, cp)
    la = legal_actions(s)
    # The buy is offered in the BEFORE window ...
    assert FireTrigger(card_id="rocky_terrain") in la
    # ... and the plow itself is still legal alongside it (firing does not force
    # or strand the plow — before-timing keeps the CommitPlow options).
    assert any(isinstance(a, CommitPlow) for a in la)


def test_offered_via_liquidation():
    # 0 food but 1 grain liquidatable -> 1 food covers the cost.
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=0, grain=1)
    s = _plow_to_before_phase(s, cp)
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
    s = _plow_to_before_phase(s, cp)
    la = legal_actions(s)
    assert FireTrigger(card_id="rocky_terrain") not in la
    # The plow is still fully legal — unaffordability only drops the buy.
    assert any(isinstance(a, CommitPlow) for a in la)


def test_not_offered_when_not_owned():
    s, cp = _card_state()
    s = with_resources(s, cp, food=5)             # plenty of food, but no card
    s = _plow_to_before_phase(s, cp)
    assert FireTrigger(card_id="rocky_terrain") not in legal_actions(s)


# --------------------------------------------------------------------------- #
# The reward: +1 stone for 1 food
# --------------------------------------------------------------------------- #

def test_direct_buy_stone_for_food():
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=3, stone=0)
    s = _plow_to_before_phase(s, cp)
    s = step(s, FireTrigger(card_id="rocky_terrain"))
    # No food-payment frame (food on hand); the host PendingPlow is back on top,
    # still in its before-phase with the plow still to be taken.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingPlow)
    assert top.phase == "before"
    assert s.players[cp].resources.food == 2      # 3 - 1
    assert s.players[cp].resources.stone == 1     # +1 stone
    # The plow can still be committed after buying the stone.
    assert any(isinstance(a, CommitPlow) for a in legal_actions(s))


def test_liquidation_buy_stone():
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=0, grain=1, stone=0)
    s = _plow_to_before_phase(s, cp)
    s = step(s, FireTrigger(card_id="rocky_terrain"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == "rocky_terrain"
    s = _commit_food_payment(s, grain=1)          # 1 grain -> 1 food
    # Resume bought the stone; PendingPlow (before-phase) back on top.
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
    s = _plow_to_before_phase(s, cp)
    # Decline: take the plow directly without firing the trigger.
    s = step(s, CommitPlow(row=0, col=2))
    assert s.players[cp].resources.food == 3      # unchanged
    assert s.players[cp].resources.stone == 0
    assert _num_fields(s, cp) >= 1                # the plow still happened


def test_fires_once_per_plowed_field():
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=5, stone=0)
    s = _plow_to_before_phase(s, cp)
    s = step(s, FireTrigger(card_id="rocky_terrain"))
    # Back at the before-phase PendingPlow; already fired -> not re-offered,
    # but the plow itself is still legal.
    la = legal_actions(s)
    assert FireTrigger(card_id="rocky_terrain") not in la
    assert any(isinstance(a, CommitPlow) for a in la)


def test_re_armed_on_each_fresh_plow():
    """"Each time you plow a field" — the once-per-frame scope re-arms on the NEXT
    plow: `triggers_resolved` lives on the PendingPlow, and every plow (each
    Farmland/Cultivation host plows one field) pushes a fresh PendingPlow, so the
    buy is offered again for the next plowed field. (Cultivation plows a single
    field, so two plows means two turns.)"""
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=5, stone=0)
    fields0 = _num_fields(s, cp)

    # First plow (turn 1): fire the buy, then commit — the plow completes.
    s = _plow_to_before_phase(s, cp)
    assert FireTrigger(card_id="rocky_terrain") in legal_actions(s)
    s = step(s, FireTrigger(card_id="rocky_terrain"))
    assert s.players[cp].resources.stone == 1
    s = step(s, CommitPlow(row=0, col=2))         # plow field #1
    assert _num_fields(s, cp) == fields0 + 1

    # Second plow on a brand-new PendingPlow frame: re-seat P0 with a clean stack
    # and place at Farmland again. The fresh frame's empty `triggers_resolved`
    # re-arms the trigger -> the buy is offered again for the next plowed field.
    s = fast_replace(s, current_player=cp, pending_stack=())
    s = _plow_to_before_phase(s, cp)
    assert FireTrigger(card_id="rocky_terrain") in legal_actions(s)   # re-armed
    s = step(s, FireTrigger(card_id="rocky_terrain"))
    assert s.players[cp].resources.stone == 2     # +1 per plowed field
    s = step(s, CommitPlow(row=1, col=2))         # plow field #2
    assert _num_fields(s, cp) == fields0 + 2
    assert s.players[cp].resources.food == 3      # 5 - 2 (one food per buy)


def test_no_plow_no_offer():
    """A non-plow turn never surfaces the trigger (no plow event at all)."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "rocky_terrain")
    s = with_resources(s, cp, food=5)
    s = _reveal(s, "forest")
    s = step(s, PlaceWorker(space="forest"))      # atomic wood space, no plow
    while s.pending_stack:
        assert FireTrigger(card_id="rocky_terrain") not in legal_actions(s)
        s = step(s, Stop())
