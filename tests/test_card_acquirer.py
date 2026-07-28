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
    # Food is a good, but NOT offered: paying people_total food for 1 food is
    # strictly dominated (user ruling 2026-07-15).
    assert FireTrigger(card_id=CARD_ID, variant="food") not in la


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
# Ruling 82 (2026-07-26): the price is payable by raising, not only on hand
# ---------------------------------------------------------------------------

def _ready_goods(*, people=2, **res):
    """Own Acquirer with exactly the given resources (food defaults to 0)."""
    s = _own(setup(seed=0), 0)
    return _edit_player(s, 0, resources=Resources(**res),
                        people_total=people, people_home=people)


def test_zero_food_with_convertible_grain_offers_and_raise_completes():
    """Boundary pins: at 0 food with 2 grain (price = 2 people = 2 food) every
    good IS offered — the price is raise-able by the at-any-time conversions
    (the old plain food-on-hand gate wrongly withheld the whole trigger).
    Firing pushes the raise-only PendingFoodPayment; committing the grain
    bundle completes the buy identically to the on-hand path. The food-good
    prune (user ruling 2026-07-15) stands under the fix."""
    from agricola.actions import CommitFoodPayment
    from agricola.pending import PendingFoodPayment
    s = _enter_round(_ready_goods(grain=2))
    la = legal_actions(s)
    for good in _GOODS:
        assert FireTrigger(card_id=CARD_ID, variant=good) in la
    assert FireTrigger(card_id=CARD_ID, variant="food") not in la   # prune stands
    s = step(s, FireTrigger(card_id=CARD_ID, variant="wood"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment) and top.food_needed == 2
    bundles = [a for a in legal_actions(s) if isinstance(a, CommitFoodPayment)]
    assert bundles == [CommitFoodPayment(grain=2, veg=0, sheep=0, boar=0, cattle=0)]
    s = step(s, bundles[0])
    p = s.players[0]
    assert p.resources.wood == 1              # the bought good
    assert p.resources.food == 0              # raised 2, debited 2
    assert p.resources.grain == 0             # the grain was the fuel
    # Once per round: back at the window, the card is resolved.
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(s))


def test_animal_good_via_raise_routes_through_grant_animals():
    """An animal good bought through the raise path still lands via
    grant_animals: 1 sheep fits the house-pet slot, no accommodation frame."""
    from agricola.actions import CommitFoodPayment
    from agricola.pending import PendingFoodPayment
    s = _enter_round(_ready_goods(grain=2))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="sheep"))
    assert isinstance(s.pending_stack[-1], PendingFoodPayment)
    bundles = [a for a in legal_actions(s) if isinstance(a, CommitFoodPayment)]
    s = step(s, bundles[0])
    p = s.players[0]
    assert p.animals == Animals(sheep=1)
    assert p.resources.food == 0 and p.resources.grain == 0
    assert not any(isinstance(f, PendingAccommodate) for f in s.pending_stack)


def test_nothing_liquidatable_stays_silent():
    """0 food and nothing convertible: no route can pay, so no variant is
    offered (the card is silent, exactly as before the fix)."""
    s = _ready_goods()
    assert _legal_variants(s, 0) == []
    s = _enter_round(s)
    assert not any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(s))


def test_food_on_hand_stays_direct():
    """With the price on hand the buy never detours through a raise frame."""
    from agricola.pending import PendingFoodPayment
    s = _enter_round(_ready(food=5))
    s = step(s, FireTrigger(card_id=CARD_ID, variant="grain"))
    assert not any(isinstance(f, PendingFoodPayment) for f in s.pending_stack)
    assert s.players[0].resources.food == 3


# ---------------------------------------------------------------------------
# Web-UI labeler
# ---------------------------------------------------------------------------

def test_action_labels():
    assert variant_label(CARD_ID, "grain") == "buy 1 grain"
    assert variant_label(CARD_ID, "sheep") == "buy 1 sheep"
    assert variant_label(CARD_ID, "bogus") is None
