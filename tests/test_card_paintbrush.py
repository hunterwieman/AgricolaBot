"""Tests for Paintbrush (minor improvement, E39; Ephipparius Expansion).

Card text (verbatim): "Each harvest, you can exchange exactly 1 clay for your
choice of 2 food or 1 bonus point."
Cost 1 Wood. Prerequisite: 1 Wild Boar (a HAVE-check at play time). No printed
VP (the points are earned).

ONE once-per-harvest budget (id "paintbrush"), THREE surfaces (user rulings
34/36/37, 2026-07-12):

1. The FEED payment frame — a variant-bearing HarvestConversionSpec
   (food_out=0; the chosen output — +2 food or +1 banked point — is granted in
   the side effect, so one spec serves both branches).
2. The generalized in-harvest raise frame — `frontier_fire=((0, 1, 0, 0), 2)`:
   a raise-frame fire IS the food branch (ruling 37: the point rider is not
   frontier-eligible) and marks the same budget (ruling 34).
3. The free span (ruling 36) — a variant-expanded optional FireTrigger on
   every in-span window/event, eligibility gated on ownership + the unused
   budget + clay >= 1.

Any one surface's fire withholds the other two for the rest of the harvest
(the shared `harvest_conversions_used` budget). These tests drive the REAL
harvest walk from Phase.HARVEST_FIELD for the feed/window surfaces, and the
hand-built in-span PendingFoodPayment idiom (from
tests/test_food_payment_generalized.py) for the raise frame.
"""
from __future__ import annotations

import agricola.cards.paintbrush  # noqa: F401  (register the card)

from agricola.actions import (
    CommitBreed,
    CommitConvert,
    CommitFieldTake,
    CommitFoodPayment,
    CommitHarvestConversion,
    FireTrigger,
    Proceed,
    Stop,
)
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.harvest_windows import (
    FREE_SPAN_EVENTS,
    HARVEST_WINDOW_CARDS,
    SENTINEL_WINDOWS,
    available_span_converters,
    in_conversion_span,
    sentinel_position,
)
from agricola.cards.paintbrush import CARD_ID, _variants
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, MINORS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingFoodPayment,
    PendingHarvestFeed,
    PendingHarvestWindow,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup

from tests.factories import with_animals, with_minors, with_phase, with_resources

_HARVEST_PHASES = (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)


# --- Helpers ----------------------------------------------------------------

def _harvest_state(*, clay=0, food=10, owners=(0,), clay_p1=0):
    """A HARVEST_FIELD-phase state: P0 (the starting player) holds `clay` and
    `food`; the seats in `owners` own Paintbrush; P1 food-rich."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = fast_replace(state, starting_player=0)
    for i in owners:
        state = with_minors(state, i, frozenset({CARD_ID}))
    state = with_resources(state, 0, food=food, clay=clay)
    state = with_resources(state, 1, food=99, clay=clay_p1)
    return state


def _is_paintbrush(action) -> bool:
    return ((isinstance(action, CommitHarvestConversion)
             and action.conversion_id == CARD_ID)
            or (isinstance(action, FireTrigger) and action.card_id == CARD_ID))


def _decline(acts):
    """The do-nothing pick at every harvest decision point: Proceed a window,
    take the field crops bare, convert/breed nothing, Stop — never a card
    fire, so the walk reaches its target with the budget intact."""
    for a in acts:
        if isinstance(a, Proceed):
            return a
    for a in acts:
        if isinstance(a, CommitFieldTake):
            return a
    for a in acts:
        if (isinstance(a, CommitConvert)
                and (a.grain, a.veg, a.sheep, a.boar, a.cattle) == (0, 0, 0, 0, 0)):
            return a
    for a in acts:
        if isinstance(a, CommitBreed) and (a.sheep, a.boar, a.cattle) == (0, 0, 0):
            return a
    for a in acts:
        if isinstance(a, Stop):
            return a
    raise AssertionError(f"no declining action among {acts}")


def _walk_to(state, want, limit=300):
    """Drive the harvest walk (declining everything) until `want(state)` is
    true of the current decision state; fail if the harvest ends first."""
    state = _advance_until_decision(state)
    for _ in range(limit):
        if state.phase not in _HARVEST_PHASES:
            raise AssertionError("harvest ended before the target state")
        if want(state):
            return state
        state = step(state, _decline(legal_actions(state)))
    raise AssertionError("walk limit hit")


def _run_harvest_collect(state, limit=300):
    """Drive the whole harvest to completion (declining everything), returning
    (final_state, offers) where offers is every Paintbrush action surfaced,
    tagged with the top frame's player_idx."""
    state = _advance_until_decision(state)
    offers = []
    for _ in range(limit):
        if state.phase not in _HARVEST_PHASES:
            return state, offers
        acts = legal_actions(state)
        top = state.pending_stack[-1]
        offers.extend((top.player_idx, a) for a in acts if _is_paintbrush(a))
        state = step(state, _decline(acts))
    raise AssertionError("walk limit hit")


def _at_p0_feed(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return (isinstance(top, PendingHarvestFeed) and top.player_idx == 0
            and not top.conversion_done)


def _at_p0_window(window_id):
    def want(state):
        top = state.pending_stack[-1] if state.pending_stack else None
        return (isinstance(top, PendingHarvestWindow) and top.player_idx == 0
                and top.window_id == window_id)
    return want


def _paintbrush_actions(state):
    return [a for a in legal_actions(state) if _is_paintbrush(a)]


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


# --- Registration -----------------------------------------------------------

def test_registration_spec_row():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=1)           # "1 Wood"
    assert spec.prereq is not None                            # 1 Wild Boar
    assert spec.min_occupations == 0
    assert spec.vps == 0                                      # none printed
    conv = HARVEST_CONVERSIONS[CARD_ID]
    assert conv.input_cost == Resources(clay=1)               # "exactly 1 clay"
    assert conv.food_out == 0                                 # outputs ride the side effect
    assert conv.side_effect_fn is not None
    assert conv.variants_fn is not None
    assert conv.frontier_fire == ((0, 1, 0, 0), 2)            # the pure food branch
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_free_span_registration():
    """One trigger per free-span event (windows indexed for hosting, sentinels
    not), plus the play-variant registration that expands each surface's fire
    into the food/point pair."""
    for event in FREE_SPAN_EVENTS:
        assert CARD_ID in {e.card_id for e in TRIGGERS.get(event, ())}, event
        if event not in SENTINEL_WINDOWS:
            assert CARD_ID in HARVEST_WINDOW_CARDS.get(event, set()), event
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert _variants(setup(0), 0) == ["food", "point"]


def test_prereq_one_wild_boar():
    """Prerequisite "1 Wild Boar" is a HAVE-check: >= 1 boar at play time."""
    spec = MINORS[CARD_ID]
    state = setup(0)
    assert state.players[0].animals.boar == 0
    assert not spec.prereq(state, 0)
    assert spec.prereq(with_animals(state, 0, boar=1), 0)


# --- Surface 1: the FEED payment frame ---------------------------------------

def test_feed_frame_offers_both_variants_and_food_fire():
    """At the feed frame both variants are offered; firing "food" debits 1 clay,
    adds 2 food, banks nothing, and spends the once-per-harvest budget."""
    state = _walk_to(_harvest_state(clay=2), _at_p0_feed)
    assert _paintbrush_actions(state) == [
        CommitHarvestConversion(conversion_id=CARD_ID, variant="food"),
        CommitHarvestConversion(conversion_id=CARD_ID, variant="point"),
    ]
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID, variant="food"))
    p = state.players[0]
    assert p.resources.clay == 1
    assert p.resources.food == 12                 # 10 + the chosen 2 food
    assert p.card_state.get(CARD_ID, 0) == 0      # no point banked
    assert CARD_ID in p.harvest_conversions_used
    # Once per harvest: no re-offer at the same frame.
    assert isinstance(state.pending_stack[-1], PendingHarvestFeed)
    assert _paintbrush_actions(state) == []


def test_feed_frame_point_fire_banks_and_scores():
    """Firing "point" debits 1 clay, adds no food, banks +1 in the CardStore
    counter, and the scoring term reads it back at end-game."""
    state = _walk_to(_harvest_state(clay=1), _at_p0_feed)
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID, variant="point"))
    p = state.players[0]
    assert p.resources.clay == 0
    assert p.resources.food == 10                 # unchanged
    assert p.card_state.get(CARD_ID, 0) == 1
    assert CARD_ID in p.harvest_conversions_used
    assert _score_fn()(state, 0) == 1
    assert _score_fn()(state, 1) == 0


# --- Surface 2: the raise frame (rulings 34/37) -------------------------------

# A synthetic resume so a hand-built frame can be stepped through the executor
# (the tests/test_food_payment_generalized.py idiom).
FOOD_PAYMENT_RESUMES["_test_paintbrush_resume"] = lambda state, idx: state


def _in_span_state(*, clay=0, grain=0, food=0, owe=2, used=frozenset()):
    """An in-span PendingFoodPayment state (post-both-breed-passes), P0 owning
    Paintbrush — the test_food_payment_generalized.py idiom with this minor in
    place of the Joinery."""
    state = setup(3)
    state = fast_replace(state, starting_player=0)
    state = with_minors(state, 0, frozenset({CARD_ID}))
    p = state.players[0]
    p = fast_replace(
        p,
        resources=Resources(clay=clay, grain=grain, food=food),
        animals=fast_replace(p.animals, sheep=0, boar=0, cattle=0),
        harvest_conversions_used=frozenset(used),
    )
    frame = PendingFoodPayment(
        player_idx=0, food_needed=food + owe,
        resume_kind="_test_paintbrush_resume", reserved=Cost())
    return fast_replace(
        state, players=tuple(p if i == 0 else state.players[i] for i in range(2)),
        phase=Phase.HARVEST_BREED, pending_stack=(frame,),
        harvest_cursor=sentinel_position("after_breeding", 1))


def test_span_converter_derivation():
    s = _in_span_state(clay=1)
    assert in_conversion_span(s, 0)
    assert available_span_converters(s, 0) == ((CARD_ID, (0, 1, 0, 0), 2),)


def test_raise_frame_fire_is_the_food_branch():
    """A raise-frame fire IS the food branch (ruling 37): 1 clay -> 2 food,
    the shared budget marked, NO point banked (the rider is feed/span-only)."""
    s = _in_span_state(clay=1, owe=2)
    opts = legal_actions(s)
    assert opts == [CommitFoodPayment(
        grain=0, veg=0, sheep=0, boar=0, cattle=0, conversions=(CARD_ID,))]
    nxt = step(s, opts[0])
    p = nxt.players[0]
    assert p.resources.clay == 0
    assert p.resources.food == 2                  # the raised 2 food
    assert p.card_state.get(CARD_ID, 0) == 0      # no point through this surface
    assert CARD_ID in p.harvest_conversions_used
    assert not any(isinstance(f, PendingFoodPayment) for f in nxt.pending_stack)


def test_raise_frame_withheld_once_budget_spent():
    """Ruling 34's shared budget: with "paintbrush" already in
    harvest_conversions_used the raise frame offers no fire — grain pays."""
    s = _in_span_state(clay=1, grain=2, owe=2, used={CARD_ID})
    assert available_span_converters(s, 0) == ()
    opts = legal_actions(s)
    assert all(a.conversions == () for a in opts)
    assert any(a.grain == 2 for a in opts)


# --- Surface 3: the free span (ruling 36) --------------------------------------

def test_window_surface_offers_variant_pair_and_point_fire():
    """The span's first surface (P0's before_field_phase window) offers the
    food/point FireTrigger pair + Proceed; firing "point" debits 1 clay, banks
    +1, spends the budget, and leaves only Proceed."""
    state = _walk_to(_harvest_state(clay=1),
                     _at_p0_window("before_field_phase"))
    assert legal_actions(state) == [
        FireTrigger(card_id=CARD_ID, variant="food"),
        FireTrigger(card_id=CARD_ID, variant="point"),
        Proceed(),
    ]
    state = step(state, FireTrigger(card_id=CARD_ID, variant="point"))
    p = state.players[0]
    assert p.resources.clay == 0
    assert p.resources.food == 10                 # unchanged
    assert p.card_state.get(CARD_ID, 0) == 1
    assert CARD_ID in p.harvest_conversions_used
    assert legal_actions(state) == [Proceed()]


def test_window_surface_food_fire():
    """The food variant through a window surface: -1 clay, +2 food, no point."""
    state = _walk_to(_harvest_state(clay=1),
                     _at_p0_window("before_field_phase"))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="food"))
    p = state.players[0]
    assert p.resources.clay == 0
    assert p.resources.food == 12
    assert p.card_state.get(CARD_ID, 0) == 0
    assert CARD_ID in p.harvest_conversions_used


# --- The shared budget across surfaces (two pairings) --------------------------

def test_window_fire_withholds_feed_and_raise_surfaces():
    """Pairing 1: a window-surface fire spends the ONE budget — the feed frame
    no longer offers the conversion and the raise-frame converter list is
    empty for the rest of the harvest."""
    state = _walk_to(_harvest_state(clay=2),
                     _at_p0_window("before_field_phase"))
    state = step(state, FireTrigger(card_id=CARD_ID, variant="point"))
    assert available_span_converters(state, 0) == ()   # raise surface withheld
    state = _walk_to(state, _at_p0_feed)
    assert _paintbrush_actions(state) == []            # feed surface withheld
    # (clay=2: a second clay is on hand, so only the budget withholds.)


def test_feed_fire_withholds_window_surfaces():
    """Pairing 2: a feed-seam fire spends the ONE budget — no later span
    window ever offers the trigger again this harvest."""
    state = _walk_to(_harvest_state(clay=2), _at_p0_feed)
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID, variant="food"))
    assert available_span_converters(state, 0) == ()
    _final, offers = _run_harvest_collect(state)
    assert offers == []                                # no window re-offer


# --- Withholding boundaries -----------------------------------------------------

def test_unowned_never_offered():
    """Clay on hand but no card: no surface offers anything, no window frame
    is pushed for it, across the whole harvest."""
    _final, offers = _run_harvest_collect(_harvest_state(clay=2, owners=()))
    assert offers == []


def test_opponent_ownership_routes_to_owner_only():
    """P1 owns Paintbrush (with clay): every surfaced Paintbrush action sits
    on a P1 frame; P0's frames never offer it."""
    state = _harvest_state(clay=2, owners=(1,), clay_p1=1)
    _final, offers = _run_harvest_collect(state)
    assert offers != []                                # the owner IS offered
    assert all(player_idx == 1 for player_idx, _a in offers)


def test_no_clay_withheld_everywhere():
    """Owned but clay-less: the feed affordability gate and the span
    eligibility's clay check withhold every surface."""
    _final, offers = _run_harvest_collect(_harvest_state(clay=0))
    assert offers == []


def test_budget_resets_next_harvest():
    """The budget is once per HARVEST — a fresh harvest walk offers again
    (harvest_conversions_used is reset at the fresh FIELD entry)."""
    state = _harvest_state(clay=2)
    p = state.players[0]
    state = fast_replace(state, players=tuple(
        fast_replace(p, harvest_conversions_used=frozenset({CARD_ID}))
        if i == 0 else state.players[i] for i in range(2)))
    state = _walk_to(state, _at_p0_window("before_field_phase"))
    assert _paintbrush_actions(state) != []            # fresh budget, offered


def test_points_accumulate_across_harvests():
    """The CardStore bank is cross-harvest; the scoring term sums it."""
    state = setup(0)
    state = with_minors(state, 0, frozenset({CARD_ID}))
    p = state.players[0]
    state = fast_replace(state, players=tuple(
        fast_replace(p, card_state=p.card_state.set(CARD_ID, 4))
        if i == 0 else state.players[i] for i in range(2)))
    assert _score_fn()(state, 0) == 4
