"""Tests for Sugar Baker (occupation, D101; Consul Dirigens Expansion).

Card text: "Each time after you use the 'Grain Utilization' action space, you
can buy 1 bonus point for 1 food. Place the food on the action space (for the
next visitor)."

Two halves. The PURCHASE ("after you use ... you can") is an OPTIONAL trigger
on the Grain Utilization host's after-phase: firing pays 1 food (direct debit,
or the raise-only PendingFoodPayment + registered resume when short but
liquidatable), banks 1 bonus point in the CardStore counter (read back by a
scoring term), and records the paid food as owed to the next visitor. The
DEPOSITED FOOD ("place the food on the action space") is represented per the
user's 2026-07-14 ruling (option b): it rides the owner's CardStore under
"sugar_baker_owed" — NOT the space's accumulated fields — and an any_player
before_action_space AUTO grants it to the NEXT player who uses Grain
Utilization (either player, the owner included) and clears the debt. The pile
can never exceed 1 food: any next visit collects in its before-phase, before
the after-phase could deposit again.

The tests drive the real host flow: PlaceWorker at grain_utilization ->
ChooseSubAction("sow") -> CommitSow -> Stop -> Proceed (flips the host to its
after-phase, where the buy surfaces) -> Stop.
"""
from __future__ import annotations

import agricola.cards.sugar_baker  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitFoodPayment,
    CommitSow,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment, PendingGrainUtilization, PendingSow
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup_env
from tests.factories import (
    with_animals,
    with_fields,
    with_majors,
    with_resources,
    with_space,
)

CARD_ID = "sugar_baker"
OWED_KEY = "sugar_baker_owed"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scorer():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _card_state(seed=5):
    """Cards-mode round-1 WORK state with P0 as current player."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_occ(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))


def _banked(state, idx=0):
    return state.players[idx].card_state.get(CARD_ID, 0)


def _owed(state, idx=0):
    return state.players[idx].card_state.get(OWED_KEY, 0)


def _use_gu_to_after_phase(s, idx):
    """Place player `idx`'s worker at Grain Utilization (revealing it), sow 1
    grain, and Proceed the host to its after-phase — a full real use of the
    space. The buy is an AFTER-use trigger, so it must not be offered at any
    earlier point of the visit."""
    s = with_space(s, "grain_utilization", revealed=True)
    s = step(s, PlaceWorker(space="grain_utilization"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrainUtilization) and top.phase == "before"
    # "AFTER you use" — never offered in the before-phase.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = step(s, ChooseSubAction(name="sow"))
    assert isinstance(s.pending_stack[-1], PendingSow)
    s = step(s, CommitSow(grain=1, veg=0))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = step(s, Stop())                       # pop the sow leaf, back at the host
    top = s.pending_stack[-1]
    assert isinstance(top, PendingGrainUtilization) and top.sow_chosen
    assert Proceed() in legal_actions(s)
    s = step(s, Proceed())                    # the use is done -> after-phase
    assert s.pending_stack[-1].phase == "after"
    return s


def _deposited_state():
    """P0 (owning Sugar Baker) completes a Grain Utilization use and buys the
    point: bank 1, 1 food owed on the space, turn over (empty stack)."""
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = with_resources(s, cp, grain=1, food=1)
    s = with_fields(s, cp, [(1, 0)])
    s = _use_gu_to_after_phase(s, cp)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, Stop())
    assert s.pending_stack == ()
    assert _banked(s, cp) == 1 and _owed(s, cp) == 1
    return s, cp


def _fresh_visit(s, visitor):
    """Fabricate a later visit: the space's worker cleared, `visitor` to move."""
    s = with_space(s, "grain_utilization", workers=(0, 0))
    return fast_replace(s, current_player=visitor)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    # The buy: an OPTIONAL trigger on the after_action_space event.
    entries = [e for e in TRIGGERS.get("after_action_space", ()) if e.card_id == CARD_ID]
    assert len(entries) == 1
    assert entries[0].mandatory is False
    # The deposit hand-off: an any_player AUTO on before_action_space (the next
    # visitor may be EITHER player).
    autos = [e for e in AUTO_EFFECTS.get("before_action_space", ()) if e.card_id == CARD_ID]
    assert len(autos) == 1
    assert autos[0].any_player is True
    # Banked points are read back at scoring; the 1 food rides the shared
    # food-payment path.
    assert CARD_ID in {cid for cid, _ in SCORING_TERMS}
    assert CARD_ID in FOOD_PAYMENT_RESUMES


# ---------------------------------------------------------------------------
# The buy, after a real Grain Utilization use
# ---------------------------------------------------------------------------

def test_buy_after_grain_utilization_use():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = with_resources(s, cp, grain=1, food=1)
    s = with_fields(s, cp, [(1, 0)])
    s = _use_gu_to_after_phase(s, cp)

    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Stop() in la                       # declining is also available

    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[cp].resources.food == 0  # 1 - 1: the food paid
    assert _banked(s, cp) == 1                # +1 banked bonus point
    assert _owed(s, cp) == 1                  # the food sits on the space, owed
    # Once per use: not re-offered on the same host visit.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)

    s = step(s, Stop())
    assert s.pending_stack == ()
    assert _scorer()(s, cp) == 1


# ---------------------------------------------------------------------------
# The deposited food goes to the NEXT visitor (either player)
# ---------------------------------------------------------------------------

def test_next_visitor_opponent_collects_the_food():
    s, cp = _deposited_state()
    opp = 1 - cp
    s = _fresh_visit(s, opp)
    opp_food = s.players[opp].resources.food
    s = step(s, PlaceWorker(space="grain_utilization"))
    # The before-phase grant: +1 food to the VISITOR, the owner's debt cleared.
    assert s.players[opp].resources.food == opp_food + 1
    assert _owed(s, cp) == 0
    assert s.players[cp].resources.food == 0  # the owner gains nothing
    assert _banked(s, cp) == 1                # the banked point stays banked


def test_owner_collects_own_deposit_then_redeposits():
    # The owner may be their own next visitor: they collect the food in the
    # before-phase, and may buy again in the after-phase. The debt is cleared
    # before it can be re-recorded, so it can never stack above 1.
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = with_resources(s, cp, grain=2, food=1)
    s = with_fields(s, cp, [(1, 0), (1, 1)])

    # Visit 1: use + buy (food 1 -> 0, bank 1, 1 owed).
    s = _use_gu_to_after_phase(s, cp)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, Stop())
    assert s.players[cp].resources.food == 0 and _owed(s, cp) == 1

    # Visit 2 (a later turn): the owner collects their own deposit at the push.
    s = _fresh_visit(s, cp)
    s = _use_gu_to_after_phase(s, cp)
    # The before-phase grant landed before the sow: +1 food, debt cleared ...
    assert s.players[cp].resources.food == 1
    # ... and the after-phase offers the buy again (a fresh host frame).
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[cp].resources.food == 0
    assert _banked(s, cp) == 2
    assert _owed(s, cp) == 1                  # never stacks above 1
    s = step(s, Stop())
    assert _scorer()(s, cp) == 2


# ---------------------------------------------------------------------------
# Optionality — declining spends and records nothing
# ---------------------------------------------------------------------------

def test_decline_via_stop_spends_and_banks_nothing():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = with_resources(s, cp, grain=1, food=1)
    s = with_fields(s, cp, [(1, 0)])
    s = _use_gu_to_after_phase(s, cp)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, Stop())                       # decline the buy
    assert s.pending_stack == ()
    assert s.players[cp].resources.food == 1  # no food spent
    assert _banked(s, cp) == 0
    assert _owed(s, cp) == 0
    assert _scorer()(s, cp) == 0


# ---------------------------------------------------------------------------
# The 1-food price via liquidation (0 food, Fireplace + sheep)
# ---------------------------------------------------------------------------

def test_buy_via_liquidation_food_payment_path():
    s, cp = _card_state()
    s = _own_occ(s, cp)
    s = with_resources(s, cp, grain=1, food=0)
    s = with_majors(s, owner_by_idx={0: cp})  # a Fireplace (sheep -> 2 food)
    s = with_animals(s, cp, sheep=1)
    s = with_fields(s, cp, [(1, 0)])
    s = _use_gu_to_after_phase(s, cp)         # the sow spent the 1 grain

    assert s.players[cp].resources.food == 0
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)   # liquidatable
    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == CARD_ID

    pay = CommitFoodPayment(grain=0, veg=0, sheep=1, boar=0, cattle=0)
    assert pay in legal_actions(s)
    s = step(s, pay)                          # cook the sheep (2 food), resume debits 1
    assert s.players[cp].animals.sheep == 0   # the sheep is gone
    assert s.players[cp].resources.food == 1  # raised 2, paid 1
    assert _banked(s, cp) == 1
    assert _owed(s, cp) == 1                  # the debt is recorded
    # Back at the after-phase host; not re-offered.
    assert isinstance(s.pending_stack[-1], PendingGrainUtilization)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Gating — non-owner sees no trigger; no debt means no grant; wrong space
# ---------------------------------------------------------------------------

def test_non_owner_sees_no_trigger_and_debtless_owner_grants_nothing():
    # P0 owns Sugar Baker with NO deposit owed; P1 (no card) uses the space.
    s, cp = _card_state()
    s = _own_occ(s, cp)
    opp = 1 - cp
    s = with_resources(s, opp, grain=1, food=1)
    s = with_fields(s, opp, [(1, 0)])
    s = fast_replace(s, current_player=opp)
    s = _use_gu_to_after_phase(s, opp)
    # No debt -> the before-phase granted nothing.
    assert s.players[opp].resources.food == 1
    # The trigger is the OWNER's: the non-owning visitor is not offered it.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert Stop() in legal_actions(s)
    s = step(s, Stop())
    assert _banked(s, cp) == 0 and _banked(s, opp) == 0


def test_deposit_not_collected_on_another_space():
    # "Place the food on THE action space": a deposit owed is handed over only
    # by a Grain Utilization use — a Farmland visit (also a hosted space firing
    # before_action_space) does not collect it.
    s, cp = _deposited_state()
    s = fast_replace(s, current_player=cp)    # P0 has a second worker
    s = step(s, PlaceWorker(space="farmland"))
    assert s.players[cp].resources.food == 0  # nothing granted
    assert _owed(s, cp) == 1                  # the deposit still waits
