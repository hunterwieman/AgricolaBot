"""Tests for Curator (occupation, A100; Artifex Expansion).

Card text: "In the returning home phase of each round, if you return at least 3
people from accumulation spaces, you can buy 1 bonus point for 1 food."

"In the returning home phase" is the round-end ladder's ``returning_home``
window (ruling 49, 2026-07-12), which fires PRE-reset — the still-placed board
is the event data, so the "at least 3 people returned from accumulation spaces"
condition reads the player's live worker counts on the accumulation spaces
(the mode-aware `helpers.accumulation_spaces` set; in the CARD game Meeting
Place is NOT one). "You can buy" is an OPTIONAL trigger (never an auto): a
FireTrigger on the window's PendingHarvestWindow choice frame, declinable via
Proceed. Firing pays 1 food through the shared food-payment path (direct debit
with food on hand; a raise-only PendingFoodPayment + registered resume when
short but liquidatable) and banks 1 bonus point in the CardStore counter, read
back at end-game by a scoring term. The bank accumulates across rounds.

The fire tests drive the REAL round-end walk: a drained cards-mode WORK state
(every person placed, the owner's workers recorded on the spaces under test),
advanced via `_advance_until_decision`, mirroring test_card_swimming_class.py.
"""
from __future__ import annotations

import agricola.cards.curator  # noqa: F401  (registers the card)

from agricola.actions import CommitFoodPayment, FireTrigger, Proceed
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.helpers import accumulation_spaces
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment, PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import (
    with_animals,
    with_majors,
    with_people,
    with_resources,
    with_space,
)

CARD_ID = "curator"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scorer():
    """The registered scoring fn for this card."""
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _own_occ(state, idx):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {CARD_ID}) if i == idx
        else state.players[i] for i in range(2)))


def _drained_cards_state(*, seed=5, owned=True, food=2,
                         spaces_p0=("forest", "clay_pit", "fishing"),
                         spaces_p1=()):
    """A cards-mode WORK round-1 state with every person placed (people_home=0
    for both players) and one P0 worker recorded on each of `spaces_p0` (P1 on
    `spaces_p1`) — so the PRE-reset returning_home occupancy is visible. P0
    optionally owns Curator and holds exactly `food` food (nothing else)."""
    s, _env = setup_env(seed, card_pool=_POOL)
    if owned:
        s = _own_occ(s, 0)
    s = with_resources(s, 0, food=food)
    for sid in spaces_p0:
        s = with_space(s, sid, workers=(1, 0))
    for sid in spaces_p1:
        s = with_space(s, sid, workers=(0, 1))
    for idx in (0, 1):
        s = with_people(s, idx, home=0)
    return s


def _banked(state, idx=0):
    return state.players[idx].card_state.get(CARD_ID, 0)


def _window_frames(state):
    return [f for f in state.pending_stack if isinstance(f, PendingHarvestWindow)]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    # "You CAN buy" -> an OPTIONAL trigger on the returning_home window,
    # never a choice-free auto.
    entries = [e for e in TRIGGERS.get("returning_home", ()) if e.card_id == CARD_ID]
    assert len(entries) == 1
    assert entries[0].mandatory is False
    assert CARD_ID not in {e.card_id for e in AUTO_EFFECTS.get("returning_home", ())}
    # The banked bonus point is read back by a scoring term.
    assert CARD_ID in {cid for cid, _ in SCORING_TERMS}
    # The 1-food price rides the shared food-payment path (raise-only frame +
    # this registered resume when the food must be liquidated).
    assert CARD_ID in FOOD_PAYMENT_RESUMES


# ---------------------------------------------------------------------------
# The buy, through the real round-end walk (3 returners from accumulation)
# ---------------------------------------------------------------------------

def test_buy_offered_and_fires_with_three_accumulation_returners():
    s = _drained_cards_state(food=2)
    s = _advance_until_decision(s)
    # Paused PRE-reset at the returning_home window: the workers are still on
    # the board (live occupancy is the event data).
    assert s.phase is Phase.RETURN_HOME
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "returning_home" and top.player_idx == 0
    for sid in ("forest", "clay_pit", "fishing"):
        assert get_space(s.board, sid).workers[0] == 1

    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la                    # optional -> declinable

    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[0].resources.food == 1   # 2 - 1: the food debited
    assert _banked(s) == 1                    # +1 banked bonus point
    # "1 bonus point" (singular): at most once per returning-home phase.
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert Proceed() in la

    s = step(s, Proceed())                    # the walk completes the round end
    assert not _window_frames(s)
    assert s.phase is Phase.PREPARATION       # round 1: no harvest
    assert _scorer()(s, 0) == 1


# ---------------------------------------------------------------------------
# Eligibility boundary — fewer than 3 from ACCUMULATION spaces
# ---------------------------------------------------------------------------

def test_not_offered_with_only_two_accumulation_returners():
    # 3 people return, but only 2 of them from accumulation spaces (the third
    # from Grain Seeds) -> ineligible -> no window frame is pushed at all.
    s = _drained_cards_state(food=2,
                             spaces_p0=("forest", "clay_pit", "grain_seeds"))
    s = _advance_until_decision(s)
    assert not _window_frames(s)
    assert _banked(s) == 0
    assert s.players[0].resources.food == 2   # nothing spent


def test_meeting_place_does_not_count_in_cards_mode():
    # In the CARD game Meeting Place gives no goods and is NOT an accumulation
    # space (user ruling 2026-07-02), so a worker there does not count toward
    # the 3.
    s = _drained_cards_state(food=2,
                             spaces_p0=("forest", "clay_pit", "meeting_place"))
    assert "meeting_place" not in accumulation_spaces(s)
    s = _advance_until_decision(s)
    assert not _window_frames(s)
    assert _banked(s) == 0


# ---------------------------------------------------------------------------
# The 1-food price — affordability gates the offer; liquidation satisfies it
# ---------------------------------------------------------------------------

def test_not_offered_when_food_unpayable():
    # 0 food and nothing convertible -> the buy cannot be paid -> not offered
    # (no dead-end trigger), so no window frame is pushed.
    s = _drained_cards_state(food=0)
    assert s.players[0].animals.sheep == 0    # nothing liquidatable either
    s = _advance_until_decision(s)
    assert not _window_frames(s)
    assert _banked(s) == 0


def test_offered_via_liquidation_and_food_payment_path():
    # 0 food but a Fireplace + 1 sheep (cookable to 2 food) -> offered; firing
    # pushes the raise-only PendingFoodPayment; resolving it banks the point.
    s = _drained_cards_state(food=0)
    s = with_majors(s, owner_by_idx={0: 0})   # player 0 owns a Fireplace
    s = with_animals(s, 0, sheep=1)
    s = _advance_until_decision(s)
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "returning_home"
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 1 and top.resume_kind == CARD_ID

    pay = CommitFoodPayment(grain=0, veg=0, sheep=1, boar=0, cattle=0)
    assert pay in legal_actions(s)
    s = step(s, pay)                          # cook the sheep (2 food), resume debits 1
    assert s.players[0].animals.sheep == 0    # the sheep is gone
    assert s.players[0].resources.food == 1   # raised 2, paid 1
    assert _banked(s) == 1
    # Back at the window frame; the buy is not re-offered.
    assert isinstance(s.pending_stack[-1], PendingHarvestWindow)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)

    s = step(s, Proceed())
    assert _scorer()(s, 0) == 1


# ---------------------------------------------------------------------------
# Optionality — Proceed declines without spending or banking
# ---------------------------------------------------------------------------

def test_decline_via_proceed_spends_and_banks_nothing():
    s = _drained_cards_state(food=2)
    s = _advance_until_decision(s)
    assert isinstance(s.pending_stack[-1], PendingHarvestWindow)
    s = step(s, Proceed())
    assert s.players[0].resources.food == 2   # no food spent
    assert _banked(s) == 0                    # nothing banked
    assert _scorer()(s, 0) == 0


# ---------------------------------------------------------------------------
# Owner-gating — a non-owner never sees the trigger
# ---------------------------------------------------------------------------

def test_non_owner_never_offered():
    # P1 returns 3 people from accumulation spaces but does not own Curator
    # (P0 owns it with no returners) -> no frame for anyone, nothing banked.
    s = _drained_cards_state(food=2, spaces_p0=(),
                             spaces_p1=("forest", "clay_pit", "fishing"))
    s = with_resources(s, 1, food=2)
    s = _advance_until_decision(s)
    assert not _window_frames(s)
    assert _banked(s, 0) == 0
    assert _banked(s, 1) == 0


# ---------------------------------------------------------------------------
# The bank accumulates across rounds
# ---------------------------------------------------------------------------

def test_bank_accumulates_across_two_rounds():
    s = _drained_cards_state(food=2)
    s = _advance_until_decision(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, Proceed())
    assert _banked(s) == 1

    # Re-arm round 2 on the SAME state (keeping card_state): drained WORK,
    # the workers back on the three accumulation spaces.
    s = fast_replace(s, pending_stack=(), phase=Phase.WORK, round_number=2)
    for sid in ("forest", "clay_pit", "fishing"):
        s = with_space(s, sid, workers=(1, 0))
    for idx in (0, 1):
        s = with_people(s, idx, home=0)
    s = _advance_until_decision(s)
    assert isinstance(s.pending_stack[-1], PendingHarvestWindow)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert _banked(s) == 2                    # cumulative
    assert s.players[0].resources.food == 0   # 1 food paid each round
    assert _scorer()(s, 0) == 2
