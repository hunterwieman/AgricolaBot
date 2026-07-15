import agricola.cards.new_purchase  # noqa: F401

"""Tests for New Purchase (minor improvement, B70; Bubulcus).

Card text: "Before the start of each round that ends with a harvest, you can buy
one of each of the following crops: 2 Food → 1 Grain; 4 Food → 1 Vegetable"

An OPTIONAL `before_round` play-variant trigger, eligible only when the round being
ENTERED (`round_number + 1`) is a harvest round. Routes: grain (2 food), veg (4
food), both (6 food). The window host's Proceed is the decline.
"""
import dataclasses

from agricola.actions import FireTrigger, Proceed
from agricola.cards.new_purchase import CARD_ID, _eligible, _legal_variants
from agricola.cards.display import variant_label
from agricola.cards.specs import MINORS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import HARVEST_ROUNDS, Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup


def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx=0):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {CARD_ID})


def _enter_round(state, *, from_round):
    state = fast_replace(state, round_number=from_round, phase=Phase.PREPARATION)
    return _complete_preparation(state)


def _ready(*, food, own=True):
    s = setup(seed=0)
    if own:
        s = _own(s, 0)
    return _edit_player(s, 0, resources=Resources(food=food))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()            # free
    assert spec.passing_left is False
    assert spec.vps == 0
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("before_round", [])}


# ---------------------------------------------------------------------------
# The harvest-round gate (round being entered = round_number + 1)
# ---------------------------------------------------------------------------

def test_eligibility_gate_on_upcoming_harvest_round():
    # round_number is the just-completed round at before_round; the entered round is +1.
    for rn in range(0, 14):
        s = _edit_player(setup(seed=0), 0, resources=Resources(food=9))
        s = _own(s, 0)
        s = fast_replace(s, round_number=rn)
        expected = (rn + 1) in HARVEST_ROUNDS
        assert _eligible(s, 0, frozenset()) is expected, rn


def test_variants_offered_entering_a_harvest_round():
    s = _enter_round(_ready(food=9), from_round=3)   # entering round 4 (harvest)
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == "before_round"
    la = legal_actions(s)
    for v in ("grain", "veg", "both"):
        assert FireTrigger(card_id=CARD_ID, variant=v) in la
    assert Proceed() in la


def test_not_offered_entering_a_non_harvest_round():
    s = _enter_round(_ready(food=9), from_round=1)   # entering round 2 (no harvest)
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(s))
    assert s.players[0].resources.food == 9          # untouched


# ---------------------------------------------------------------------------
# Each route buys the right crops at the right price
# ---------------------------------------------------------------------------

def test_buy_grain():
    s = _enter_round(_ready(food=9), from_round=3)
    s2 = step(s, FireTrigger(card_id=CARD_ID, variant="grain"))
    p = s2.players[0]
    assert (p.resources.grain, p.resources.veg, p.resources.food) == (1, 0, 7)


def test_buy_veg():
    s = _enter_round(_ready(food=9), from_round=3)
    s2 = step(s, FireTrigger(card_id=CARD_ID, variant="veg"))
    p = s2.players[0]
    assert (p.resources.grain, p.resources.veg, p.resources.food) == (0, 1, 5)


def test_buy_both():
    s = _enter_round(_ready(food=9), from_round=3)
    s2 = step(s, FireTrigger(card_id=CARD_ID, variant="both"))
    p = s2.players[0]
    assert (p.resources.grain, p.resources.veg, p.resources.food) == (1, 1, 3)


# ---------------------------------------------------------------------------
# Affordability boundaries on the routes
# ---------------------------------------------------------------------------

def test_route_affordability():
    def variants(food):
        s = _own(_edit_player(setup(seed=0), 0, resources=Resources(food=food)), 0)
        s = fast_replace(s, round_number=3)          # entering harvest round 4
        return _legal_variants(s, 0)

    assert variants(1) == []                         # can't afford grain
    assert variants(2) == ["grain"]
    assert variants(4) == ["grain", "veg"]
    assert variants(5) == ["grain", "veg"]           # both needs 6
    assert variants(6) == ["grain", "veg", "both"]


# ---------------------------------------------------------------------------
# Optionality + once-per-round
# ---------------------------------------------------------------------------

def test_decline_via_proceed():
    s = _enter_round(_ready(food=9), from_round=3)
    s2 = step(s, Proceed())
    assert s2.players[0].resources == Resources(food=9)   # nothing spent or gained


def test_only_once_per_round():
    s = _enter_round(_ready(food=9), from_round=3)
    s = step(s, FireTrigger(card_id=CARD_ID, variant="grain"))
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(s))


def test_unowned_never_offered():
    s = _enter_round(_ready(food=9, own=False), from_round=3)
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(s))


# ---------------------------------------------------------------------------
# Web-UI labeler
# ---------------------------------------------------------------------------

def test_action_labels():
    assert variant_label(CARD_ID, "grain") == "buy 1 grain (2 food)"
    assert variant_label(CARD_ID, "both") == "buy 1 grain + 1 vegetable (6 food)"
    assert variant_label(CARD_ID, "bogus") is None
