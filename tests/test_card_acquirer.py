import agricola.cards.acquirer  # noqa: F401

"""Tests for Acquirer (occupation, E102; Ephipparius Expansion).

Card text: "At the start of each round, you may pay food equal to the number of
people you have to buy 1 good of your choice from the general supply."

An OPTIONAL `start_of_round` play-variant trigger (the Scholar / Mineral Feeder
shape): one FireTrigger per buyable good, the window host's Proceed as the decline,
`people_total` food per good. Resource goods (food included — Emissary D124) are a
direct debit-and-grant; animal goods route through `helpers.grant_animals`.
"""
import dataclasses

from agricola.actions import FireTrigger, Proceed
from agricola.cards.acquirer import CARD_ID, _GOODS, _legal_variants
from agricola.cards.display import variant_label
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingAccommodate, PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.setup import setup


def _edit_player(state, idx, **kw):
    p = fast_replace(state.players[idx], **kw)
    return dataclasses.replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _own(state, idx=0):
    p = state.players[idx]
    return _edit_player(state, idx, occupations=p.occupations | {CARD_ID})


def _enter_round(state, *, from_round=1):
    """Run the real preparation walk into round from_round+1 (the Mineral Feeder idiom)."""
    state = fast_replace(state, round_number=from_round, phase=Phase.PREPARATION)
    return _complete_preparation(state)


def _ready(*, food, people=2, animals=None):
    """Own Acquirer with the given food / people_total / animals, at a PREPARATION
    boundary about to enter the next round."""
    s = _own(setup(seed=0), 0)
    kw = {"resources": Resources(food=food), "people_total": people,
          "people_home": people}
    if animals is not None:
        kw["animals"] = animals
    return _edit_player(s, 0, **kw)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("start_of_round", [])}


# ---------------------------------------------------------------------------
# All goods offered when affordable; none when broke
# ---------------------------------------------------------------------------

def test_all_goods_offered_at_start_of_round():
    s = _enter_round(_ready(food=3))          # cost 2 (people_total 2) <= 3 food
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == "start_of_round"
    la = legal_actions(s)
    for good in _GOODS:
        assert FireTrigger(card_id=CARD_ID, variant=good) in la
    assert Proceed() in la                    # optional -> decline
    # "Food is also considered a good" (Emissary D124).
    assert FireTrigger(card_id=CARD_ID, variant="food") in la


def test_no_variants_when_food_below_cost():
    # 3 people -> cost 3; only 2 food -> nothing affordable.
    s = _ready(food=2, people=3)
    assert _legal_variants(s, 0) == []


# ---------------------------------------------------------------------------
# Buying a resource good: debit people_total food, gain 1 of the good
# ---------------------------------------------------------------------------

def test_buy_grain_debits_food():
    s = _enter_round(_ready(food=5))
    s2 = step(s, FireTrigger(card_id=CARD_ID, variant="grain"))
    p = s2.players[0]
    assert p.resources.grain == 1
    assert p.resources.food == 5 - 2          # people_total 2 food paid


def test_buy_food_nets_out():
    # Food is a good: pay 2 food, get 1 food -> net -1.
    s = _enter_round(_ready(food=5))
    s2 = step(s, FireTrigger(card_id=CARD_ID, variant="food"))
    assert s2.players[0].resources.food == 5 - 2 + 1


# ---------------------------------------------------------------------------
# Buying an animal routes through grant_animals (accommodation-aware)
# ---------------------------------------------------------------------------

def test_buy_sheep_grants_via_barrier_when_it_fits():
    s = _enter_round(_ready(food=5))
    s2 = step(s, FireTrigger(card_id=CARD_ID, variant="sheep"))
    p = s2.players[0]
    assert p.animals == Animals(sheep=1)      # 1 sheep fits the house pet slot
    assert p.resources.food == 3
    assert not any(isinstance(f, PendingAccommodate) for f in s2.pending_stack)


def test_buy_animal_over_capacity_surfaces_accommodation():
    # 1 sheep already fills the default farm's only animal slot (the house pet);
    # buying a cattle overflows -> grant_animals' barrier asks which to keep.
    s = _enter_round(_ready(food=5, animals=Animals(sheep=1)))
    s2 = step(s, FireTrigger(card_id=CARD_ID, variant="cattle"))
    assert any(isinstance(f, PendingAccommodate) for f in s2.pending_stack)


# ---------------------------------------------------------------------------
# Cost scales with people_total
# ---------------------------------------------------------------------------

def test_cost_scales_with_people():
    s = _enter_round(_ready(food=4, people=4))   # cost 4 == 4 food, exactly affordable
    s2 = step(s, FireTrigger(card_id=CARD_ID, variant="wood"))
    p = s2.players[0]
    assert p.resources.wood == 1
    assert p.resources.food == 0                 # all 4 food spent


# ---------------------------------------------------------------------------
# Optionality + once per round
# ---------------------------------------------------------------------------

def test_decline_via_proceed_buys_nothing():
    s = _enter_round(_ready(food=5))
    s2 = step(s, Proceed())
    p = s2.players[0]
    assert p.resources.food == 5                 # no food spent
    assert p.resources == Resources(food=5)      # nothing gained


def test_only_once_per_round():
    s = _enter_round(_ready(food=9))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="grain"))
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(s))


def test_unowned_never_offered():
    s = _enter_round(_edit_player(setup(seed=0), 0, resources=Resources(food=5)))
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(s))


# ---------------------------------------------------------------------------
# Web-UI labeler
# ---------------------------------------------------------------------------

def test_action_labels():
    assert variant_label(CARD_ID, "grain") == "buy 1 grain"
    assert variant_label(CARD_ID, "sheep") == "buy 1 sheep"
    assert variant_label(CARD_ID, "bogus") is None
