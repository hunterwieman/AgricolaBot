"""Registry-driven contract tests for FOOD-priced harvest conversions.

A `HarvestConversionSpec` whose `input_cost` includes food is a food PRICE, and
ruling 82 (CARD_AUTHORING_GUIDE.md §0.4) forbids gating a food price on
food-on-hand — the at-any-time conversions are legal payment routes, so the
plain gate deletes rules-legal lines. The FEED seam therefore gates such
entries with `_liquidatable_to` and `_execute_harvest_conversion` pushes the
raise-only `PendingFoodPayment` when the fee is short, resuming into the
card's registered `FOOD_PAYMENT_RESUMES` continuation (built 2026-07-30,
retiring ruling 84 item 4's on-hand carve-out for Basket Carrier and
Furniture Carpenter — the last two plain food gates in the catalog).

Why these tests iterate the REGISTRY rather than name cards: the carve-out
survived a same-day 572-card audit precisely because the audit's unit was the
card module while the gate lived in a shared engine enumerator (correct there
for every non-food-priced entry). A registry sweep covers a future food-priced
conversion the day it registers, with no allowlist to maintain.

Test 2 substitutes each spec's `is_owned_fn` with an always-True stand-in for
the duration of the drive: ownership predicates are arbitrary closures
(Furniture Carpenter wants the Joinery on the board AND the occupation
played), so a generic test cannot satisfy the real one for a card it does not
know — and per-card ownership setup would recreate exactly the per-card
auditing that missed this class.
"""
import dataclasses

import agricola.cards  # noqa: F401  (registers the full catalog)

from agricola.actions import CommitFoodPayment, CommitHarvestConversion
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.specs import FOOD_PAYMENT_RESUMES
from agricola.constants import Phase
from agricola.engine import _initiate_harvest_feed, step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment
from agricola.replace import fast_replace
from agricola.resources import Animals
from agricola.setup import setup

from tests.factories import with_majors, with_phase, with_resources


def _food_priced_specs():
    return [(cid, spec) for cid, spec in sorted(HARVEST_CONVERSIONS.items())
            if spec.input_cost.food > 0]


def test_food_priced_conversions_exist():
    """The sweep below must not silently pass vacuously: at least the two
    known food-priced entries are registered."""
    ids = {cid for cid, _ in _food_priced_specs()}
    assert {"basket_carrier", "furniture_carpenter"} <= ids


def test_every_food_priced_conversion_registers_a_resume():
    """The import-time half of `_execute_harvest_conversion`'s contract: a
    food-priced conversion MUST register a food-payment resume, because the
    raise-only frame resumes into it. Without one, the executor's assert fires
    mid-game; this catches it at test time for every current and future entry."""
    for cid, spec in _food_priced_specs():
        assert cid in FOOD_PAYMENT_RESUMES, (
            f"{cid}: food-priced harvest conversion (input {spec.input_cost}) "
            f"has no register_food_payment_resume(...) entry — the ruling-82 "
            f"raise shape cannot resume it")
        assert spec.variants_fn is None, (
            f"{cid}: PendingFoodPayment carries no variant; a variant-bearing "
            f"food-priced conversion needs its resume to carry the variant "
            f"before the raise path can serve it")


def test_every_food_priced_conversion_offered_when_raisable():
    """The behavioural half: at a real feed frame with ZERO food and one
    cookable sheep (Fireplace: 2 food — enough for any current fee), each
    food-priced conversion is OFFERED, and firing it pushes the raise-only
    PendingFoodPayment instead of resolving. A plain `_can_afford` gate at
    the feed seam fails the offer assertion — this is the regression test for
    the exact defect the 2026-07-30 fix removed."""
    for cid, spec in _food_priced_specs():
        always_owned = dataclasses.replace(
            spec, is_owned_fn=lambda state, idx: idx == 0)
        original = HARVEST_CONVERSIONS[cid]
        HARVEST_CONVERSIONS[cid] = always_owned
        try:
            state = setup(seed=0)
            state = dataclasses.replace(state, starting_player=0)
            p0 = dataclasses.replace(state.players[0],
                                     animals=Animals(sheep=3))
            state = dataclasses.replace(state, players=(p0, state.players[1]))
            state = with_majors(state, owner_by_idx={0: 0})   # Fireplace(2c)
            state = with_resources(state, 0, food=0)
            state = with_resources(state, 1, food=99)
            state = with_phase(state, Phase.HARVEST_FEED)
            state = _initiate_harvest_feed(state)

            offered = [a for a in legal_actions(state)
                       if isinstance(a, CommitHarvestConversion)
                       and a.conversion_id == cid]
            assert offered, (
                f"{cid}: food-priced conversion withheld at the feed frame "
                f"with 0 food but a raisable fee — a plain food-on-hand gate "
                f"(ruling 82 violation)")

            state = step(state, offered[0])
            assert isinstance(state.pending_stack[-1], PendingFoodPayment), (
                f"{cid}: firing with the fee short must push the raise-only "
                f"PendingFoodPayment")
            bundle = next(a for a in legal_actions(state)
                          if isinstance(a, CommitFoodPayment))
            state = step(state, bundle)
            assert cid in state.players[0].harvest_conversions_used, (
                f"{cid}: the resumed continuation must mark the shared "
                f"once-per-harvest budget")
        finally:
            HARVEST_CONVERSIONS[cid] = original
