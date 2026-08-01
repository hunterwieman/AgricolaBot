"""Tests for Winter Caretaker (occupation, C113).

Card text (verbatim): "When you play this card, you immediately get 1 grain. At
the end of each harvest, you can buy exactly 1 vegetable for 2 food."

Two effects:
1. On play: immediately +1 grain.
2. A recurring, optional, once-per-harvest buy surfaced as an optional TRIGGER on
   harvest window #16 ``end_of_harvest`` (the last in-harvest moment, after
   breeding; ruling 2026-07-03). Firing it spends 2 food and grants 1 vegetable;
   declining is the window frame's ``Proceed``. The vegetable is a normal good, so
   there is NO scoring term.

Mis-timing history: the buy previously rode the ``HARVEST_CONVERSIONS`` seam,
surfacing during the FEED sub-phase. It has been migrated to window #16 per the
printed "at the end of each harvest" and the 2026-07-03 post-breeding-timeline
ruling. These tests drive the REAL harvest walk (``_advance_harvest`` via
``_advance_until_decision`` + step) and assert the buy surfaces at the
``end_of_harvest`` window (after breeding), never during feeding.

User ruling 85 (2026-07-27) governs what pays for the buy at its window: the
converters are CLOSED at end_of_harvest (their final home is the last
conversion opportunity of the breed phase, immediately before it — a
converter's food is routed into this buy by firing it at the owner's
``after_breeding`` surface, then buying with the banked food), and ruling 39's
post-breed cooking floor has LAPSED there — the buy CAN be paid by cooking a
just-bred animal.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.winter_caretaker  # noqa: F401  (register the card)

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
from agricola.constants import GameMode, Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingFoodPayment,
    PendingHarvestFeed,
    PendingHarvestWindow,
    push,
)
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.cards.harvest_windows import (
    HARVEST_WINDOW_CARDS,
    available_span_converters,
    post_breed_floors,
    sentinel_position,
)
from agricola.cards.triggers import TRIGGERS
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, OCCUPATIONS
from agricola.setup import CardPool, setup, setup_env

from tests.factories import with_animals, with_majors, with_phase, with_resources

CARD_ID = "winter_caretaker"


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, player_idx):
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _harvest_state(*, owner_food=10, give_occ=True):
    """A HARVEST_FIELD-phase state. P0 owns Winter Caretaker (unless give_occ is
    False) and holds owner_food food; P1 is food-rich so its feeding is trivial.
    P0 needs 4 food (2 adults) — owner_food governs whether the buy is affordable
    on top of feeding."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    state = with_resources(state, 0, food=owner_food)
    state = with_resources(state, 1, food=99)
    return state


def _walk_to_end_of_harvest(state):
    """Drive the harvest walk until P0's end_of_harvest window frame is on top,
    stepping the first legal action at every other decision. Returns
    (state, feeding_ever_offered_the_buy)."""
    saw_buy_in_feeding = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.AFTER_FEEDING, Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestFeed):
            if any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
                   for a in legal_actions(state)):
                saw_buy_in_feeding = True
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "end_of_harvest"
                and top.player_idx == 0):
            return state, saw_buy_in_feeding
        state = step(state, legal_actions(state)[0])
    return state, saw_buy_in_feeding


# --- Registration -----------------------------------------------------------

def test_registered_as_occupation_and_window_trigger():
    assert CARD_ID in OCCUPATIONS
    # Migrated off HARVEST_CONVERSIONS onto the end_of_harvest window.
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("end_of_harvest", set())
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("end_of_harvest", ()))
    # The 2-food price is liquidatable (ruling 82).
    assert CARD_ID in FOOD_PAYMENT_RESUMES


def test_no_longer_on_harvest_conversions():
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
    assert CARD_ID not in HARVEST_CONVERSIONS


def test_no_scoring_term():
    """The vegetable is a normal good — no banked points, no scoring term."""
    assert not any(card_id == CARD_ID for card_id, _ in SCORING_TERMS)


# --- On-play: +1 grain ------------------------------------------------------

def test_on_play_grants_one_grain():
    state = setup(seed=0)
    grain0 = state.players[0].resources.grain

    on_play = OCCUPATIONS[CARD_ID].on_play
    new_state = on_play(state, 0)

    assert new_state.players[0].resources.grain == grain0 + 1
    # No other resource moved, opponent untouched.
    assert new_state.players[1].resources == state.players[1].resources
    assert (
        dataclasses.replace(new_state.players[0].resources, grain=grain0)
        == state.players[0].resources
    )


# --- The buy surfaces at end_of_harvest (not feeding) -----------------------

def test_buy_surfaces_at_end_of_harvest_not_feeding():
    """The buy is a FireTrigger at the end_of_harvest window (after breeding),
    and never appears during feeding."""
    state, saw_buy_in_feeding = _walk_to_end_of_harvest(_harvest_state(owner_food=10))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "end_of_harvest"
    assert top.player_idx == 0
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)
    assert not saw_buy_in_feeding


def test_buy_spends_two_food_and_grants_one_vegetable():
    state, _ = _walk_to_end_of_harvest(_harvest_state(owner_food=10))
    food0 = state.players[0].resources.food
    veg0 = state.players[0].resources.veg
    state = step(state, FireTrigger(card_id=CARD_ID))

    # Direct path: no PendingFoodPayment — the window frame stays on top.
    assert isinstance(state.pending_stack[-1], PendingHarvestWindow)
    # 2 food spent, no food produced; one vegetable gained.
    assert state.players[0].resources.food == food0 - 2
    assert state.players[0].resources.veg == veg0 + 1


def test_buy_is_once_per_harvest():
    """Once-per-window: after firing, only Proceed remains for this window."""
    state, _ = _walk_to_end_of_harvest(_harvest_state(owner_food=10))
    veg0 = state.players[0].resources.veg
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert legal_actions(state) == [Proceed()]
    assert state.players[0].resources.veg == veg0 + 1


def test_buy_is_optional_declinable():
    """Declining is the window frame's Proceed; nothing is spent or gained."""
    state, _ = _walk_to_end_of_harvest(_harvest_state(owner_food=10))
    veg0 = state.players[0].resources.veg
    food0 = state.players[0].resources.food
    assert Proceed() in legal_actions(state)
    state = step(state, Proceed())
    assert state.players[0].resources.veg == veg0
    assert state.players[0].resources.food == food0


# --- Eligibility boundaries -------------------------------------------------

def test_not_offered_to_non_owner_seat():
    """The trigger is global; only the occupation owner is offered the buy.

    Drive the whole harvest and assert P0's end_of_harvest frame offers the buy
    while P1 never gets an end_of_harvest frame at all (owner-gated)."""
    state = _harvest_state(owner_food=10)
    state = with_resources(state, 1, food=10)  # P1 food-rich too

    saw_p0_buy = False
    saw_p1_window = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.AFTER_FEEDING, Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.window_id == "end_of_harvest":
            buys = [a for a in legal_actions(state)
                    if isinstance(a, FireTrigger) and a.card_id == CARD_ID]
            if top.player_idx == 0 and buys:
                saw_p0_buy = True
            if top.player_idx == 1:
                saw_p1_window = True
        state = step(state, legal_actions(state)[0])

    assert saw_p0_buy         # the owner IS offered the buy
    assert not saw_p1_window  # the non-owner gets no end_of_harvest frame


def test_not_offered_when_unowned():
    """No seat owns Winter Caretaker → no end_of_harvest frame ever appears."""
    state = _harvest_state(owner_food=10, give_occ=False)
    saw_window = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.AFTER_FEEDING, Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.window_id == "end_of_harvest":
            saw_window = True
        state = step(state, legal_actions(state)[0])
    assert not saw_window


def test_not_offered_when_food_short():
    """Needs 2 food to buy; with 1 food (and feeding need 4) and nothing
    liquidatable (no crops/animals/converters) the price is not payable by any
    route, so eligibility fails and no end_of_harvest frame is pushed for P0."""
    state = _harvest_state(owner_food=1)
    saw_window = False
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.AFTER_FEEDING, Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow) and top.window_id == "end_of_harvest":
            saw_window = True
        state = step(state, legal_actions(state)[0])
    assert not saw_window


# --- Ruling 85 (2026-07-27): the converter/floor boundary at end_of_harvest --

def _neutral_action(state):
    """An action that advances the harvest walk WITHOUT firing any card or
    converter surface: the mechanical commits first, then Proceed/Stop, never
    a FireTrigger or a CommitHarvestConversion (the test_card_plow_builder
    walker)."""
    actions = legal_actions(state)
    for kind in (CommitFieldTake, CommitConvert, CommitBreed):
        for a in actions:
            if isinstance(a, kind):
                return a
    for a in actions:
        if isinstance(a, (Proceed, Stop)):
            return a
    for a in actions:
        if not isinstance(a, (FireTrigger, CommitHarvestConversion)):
            return a
    raise AssertionError(f"no neutral action among {actions}")


_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _cards_harvest_state(*, food=4, wood=0):
    """A CARDS-mode HARVEST_FIELD-phase state at the fresh walk entry: P0 is
    starting player, owns Winter Caretaker and the Joinery (major 7), and
    holds the given food/wood; P1 food-rich so its frames resolve trivially.
    CARDS mode because the craft majors' span-window triggers — the ruled
    after_breeding surface below — are Cards-only (ruling 74)."""
    cs, _env = setup_env(5, card_pool=_POOL)
    assert cs.mode is GameMode.CARDS
    cs = with_phase(cs, Phase.HARVEST_FIELD)
    cs = dataclasses.replace(
        cs, starting_player=0, pending_stack=(), harvest_cursor=None)
    cs = _give_occupation(cs, 0)
    cs = with_majors(cs, owner_by_idx={7: 0})
    cs = with_resources(cs, 0, food=food, wood=wood)
    cs = with_resources(cs, 1, food=99)
    return cs


def _walk_to_p0_window(state, window_id):
    """Neutral-step the walk to P0's frame for the named window. The loop set
    includes the CARDS-mode outer-window phases (PRE_HARVEST /
    END_OF_HARVEST / AFTER_HARVEST): a Cards walk paused at a lead/tail
    window carries the honest phase, not a band phase."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.AFTER_FEEDING,
                          Phase.HARVEST_BREED, Phase.PRE_HARVEST,
                          Phase.END_OF_HARVEST, Phase.AFTER_HARVEST):
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == window_id
                and top.player_idx == 0):
            return state
        state = step(state, _neutral_action(state))
    raise AssertionError(f"no P0 {window_id} frame surfaced")


def test_converters_closed_at_end_of_harvest_ruled_play_via_after_breeding():
    """Ruling 85 (2026-07-27): the converters are closed at end_of_harvest —
    a converter's final home is the last conversion opportunity of the breed
    phase, immediately before it. The ruled play for "use the Joinery to pay
    for the vegetable" (which the raise frame used to serve at end_of_harvest
    itself): the owner standalone-fires the Joinery span trigger at their
    after_breeding surface, banking the 2 food, and the buy then fires DIRECT
    at end_of_harvest — no raise frame, no converter in it."""
    state = _cards_harvest_state(food=4, wood=1)      # feeding takes exactly 4

    state = _walk_to_p0_window(state, "after_breeding")
    p0 = state.players[0]
    assert p0.resources.food == 0                     # feeding drained it
    assert p0.resources.wood == 1
    assert "joinery" not in p0.harvest_conversions_used
    # The Joinery's span trigger is offered here — its LAST surface.
    assert FireTrigger(card_id="craft_span_joinery") in legal_actions(state)
    state = step(state, FireTrigger(card_id="craft_span_joinery"))
    p0 = state.players[0]
    assert p0.resources.food == 2 and p0.resources.wood == 0
    assert "joinery" in p0.harvest_conversions_used

    state = _walk_to_p0_window(state, "end_of_harvest")
    assert available_span_converters(state, 0) == ()  # the span is closed here
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    # Direct path on the banked food: no raise frame ever appears.
    assert not any(isinstance(f, PendingFoodPayment)
                   for f in state.pending_stack)
    p0 = state.players[0]
    assert p0.resources.veg == 1 and p0.resources.food == 0


def _end_of_harvest_frame_state(*, food=0, grain=0, wood=0, sheep=0,
                                fireplace=False, joinery=False):
    """A hand-built P0 end_of_harvest window frame at the FAMILY-mode walk
    shape: phase HARVEST_BREED (the Family walk keeps the tail under it —
    the honest END_OF_HARVEST phase is stamped only when state.mode is
    CARDS) and the stored cursor such a frame carries — one past the
    window's virtual position (a frame pushed at position P stores cursor
    P + 1). This is the shape a Family-mode state with hand-given cards
    reaches, and it exercises the CURSOR side of ruling 85's boundary
    (`cur > _END_OF_HARVEST_POS`); the Cards-mode phase side is pinned in
    test_harvest_phase_attribution.py."""
    state = setup(seed=0)
    state = fast_replace(state, starting_player=0)
    state = _give_occupation(state, 0)
    owners = {}
    if fireplace:
        owners[0] = 0                                 # Fireplace (major 0)
    if joinery:
        owners[7] = 0                                 # Joinery (major 7)
    if owners:
        state = with_majors(state, owner_by_idx=owners)
    state = with_resources(state, 0, food=food, grain=grain, wood=wood)
    if sheep:
        state = with_animals(state, 0, sheep=sheep)
    state = push(state, PendingHarvestWindow(window_id="end_of_harvest",
                                             player_idx=0))
    return fast_replace(
        state, phase=Phase.HARVEST_BREED,
        harvest_cursor=sentinel_position("end_of_harvest", None) + 1)


def test_no_converter_in_end_of_harvest_raise_bundles():
    """Ruling 85: a raise frame AT end_of_harvest carries no converter — the
    span closed after after_breeding. P0 has 0 food, 2 grain, 1 wood, and the
    Joinery unused: the buy IS offered (the grain covers the price), but
    every payment bundle is converter-free — the Joinery never appears in
    one, and its once-per-harvest budget survives the buy untouched."""
    state = _end_of_harvest_frame_state(grain=2, wood=1, joinery=True)
    assert available_span_converters(state, 0) == ()
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment)
    assert top.food_needed == 2 and top.resume_kind == CARD_ID
    commits = [a for a in legal_actions(state) if isinstance(a, CommitFoodPayment)]
    assert commits
    assert all(c.conversions == () for c in commits)  # no Joinery bundle
    state = step(state, commits[0])
    p0 = state.players[0]
    assert p0.resources.veg == 1                      # the buy completed
    assert p0.resources.grain == 0                    # the grain was the fuel
    assert p0.resources.wood == 1                     # the Joinery input untouched
    assert "joinery" not in p0.harvest_conversions_used


def test_floor_lapsed_at_end_of_harvest_cooks_just_bred_sheep():
    """Ruling 85's floor boundary, lapse side: at the end_of_harvest window
    (still Phase.HARVEST_BREED) ruling 39's post-breed floor no longer binds
    — with 0 food, 3 just-bred sheep, and a Fireplace, the buy IS offered and
    the payment bundle cooks a sheep BELOW the old floor of 3. One step
    earlier (a frame paused at the breed phase's last after_breeding surface,
    cursor one lower) the same holdings are still floored — the boundary is
    exactly the end_of_harvest moment."""
    state = _end_of_harvest_frame_state(sheep=3, fireplace=True)
    at_after_breeding = fast_replace(
        state, harvest_cursor=sentinel_position("after_breeding", 1) + 1)
    assert post_breed_floors(at_after_breeding, 0) == (3, 3, 3)   # still bound
    assert post_breed_floors(state, 0) == (0, 0, 0)               # lapsed

    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFoodPayment) and top.food_needed == 2
    commits = [a for a in legal_actions(state) if isinstance(a, CommitFoodPayment)]
    assert commits == [CommitFoodPayment(grain=0, veg=0, sheep=1, boar=0,
                                         cattle=0)]
    state = step(state, commits[0])
    p0 = state.players[0]
    assert p0.resources.veg == 1 and p0.resources.food == 0
    assert p0.animals.sheep == 2                      # below the old floor of 3


def test_probe_hosts_no_frame_when_only_route_is_closed_converter():
    """The residue fix (user-approved phase-honesty pass, 2026-07-27): the
    walk's eligibility probes run with the cursor cleared, and before the
    honest tail phases they fell back to a phase read that said "still in
    the harvest" at end_of_harvest — so a player whose ONLY route to the
    2-food buy was the now-closed Joinery got a Proceed-only frame. Pin:
    Cards harvest, Winter Caretaker owned, P0 reaches end_of_harvest with 0
    food (feeding took exactly its 4), no crops or animals, 1 wood, and the
    Joinery unused — the walk hosts NO frame for P0 at that window (passes
    silently), because the probe now answers under Phase.END_OF_HARVEST:
    converters closed, nothing else raises the 2 food."""
    state = _cards_harvest_state(food=4, wood=1)
    p = state.players[0]
    assert p.animals.sheep == p.animals.boar == p.animals.cattle == 0
    assert p.resources.grain == 0 and p.resources.veg == 0

    state = _advance_until_decision(state)
    eoh_frames = []
    for _ in range(300):
        if state.phase not in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                               Phase.AFTER_FEEDING,
                               Phase.HARVEST_BREED, Phase.PRE_HARVEST,
                               Phase.END_OF_HARVEST, Phase.AFTER_HARVEST):
            break
        top = state.pending_stack[-1] if state.pending_stack else None
        if (isinstance(top, PendingHarvestWindow)
                and top.window_id == "end_of_harvest"):
            eoh_frames.append(top.player_idx)
        state = step(state, _neutral_action(state))
    else:
        raise AssertionError("harvest walk did not terminate")

    assert eoh_frames == []                    # nobody was owed the window
    assert state.phase is Phase.PREPARATION    # the walk completed silently
    p0 = state.players[0]
    assert p0.resources.food == 0 and p0.resources.veg == 0
    assert p0.resources.wood == 1              # the Joinery input untouched
    assert "joinery" not in p0.harvest_conversions_used


# --- Eligibility unit check -------------------------------------------------

def test_eligibility_gates_on_ownership_and_food():
    from agricola.cards.winter_caretaker import _eligible
    state = _harvest_state(owner_food=10)
    assert _eligible(state, 0, frozenset()) is True
    # Non-owner seat.
    assert _eligible(state, 1, frozenset()) is False
    # Owner with only 1 food cannot afford it.
    state1 = with_resources(state, 0, food=1)
    assert _eligible(state1, 0, frozenset()) is False
