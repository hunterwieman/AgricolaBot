"""Tests for Braid Maker (occupation, E109; ruling 74, 2026-07-21).

Card text (verbatim): "Each harvest, you can use this card to exchange 1 reed
for 2 food. You can build the Basketmaker's Workshop for 1 reed and 1 stone
even when taking a "Minor Impr." action."

Coverage:

- Registration on every surface: occupation spec, the harvest-conversion row
  (frontier_fire included), the free-span trigger set, the build_major cost
  formula, and the minor-action major-build seam row.
- The 1-reed-1-stone formula: prices every Basketmaker's build by the owner
  (Major Improvement composite AND House Redevelopment provenance), dominates
  the printed 2r+2s base, owner-gated.
- The named "Minor Improvement" action build, end-to-end in CARDS mode:
  Meeting Place -> the minor branch takeable with NO playable minor in hand
  (the seam's gate) -> the swap trigger -> Basketmaker's built for 1r+1s; the
  decline path (playing a hand minor normally); the branch-gate negatives.
- The reed->2-food harvest-span exchange through the REAL banded harvest walk:
  the feed-frame fire, the end_of_harvest window fire on a post-feed reed
  gain, the shared once-per-harvest budget in both directions, the fresh
  next-harvest reset, and the raise-frame (PendingFoodPayment) reach.
- Family-mode negative: an unowned harvest surfaces nothing new.
"""
from __future__ import annotations

import agricola.cards.braid_maker  # noqa: F401  (register the card)

import dataclasses

from agricola.actions import (
    ChooseSubAction,
    CommitBreed,
    CommitBuildMajor,
    CommitConvert,
    CommitFieldTake,
    CommitFoodPayment,
    CommitHarvestConversion,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.braid_maker import BASKETMAKER_IDX, CARD_ID
from agricola.cards.cost_mods import FORMULA_MODS
from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
from agricola.cards.harvest_windows import (
    FREE_SPAN_EVENTS,
    HARVEST_WINDOW_CARDS,
    SENTINEL_WINDOWS,
    available_span_converters,
    sentinel_position,
)
from agricola.cards.specs import FOOD_PAYMENT_RESUMES, OCCUPATIONS
from agricola.cards.triggers import TRIGGERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import (
    MINOR_ACTION_MAJOR_BUILDS,
    legal_actions,
    minor_action_major_build_options,
)
from agricola.pending import (
    PendingBuildMajor,
    PendingFoodPayment,
    PendingHarvestFeed,
    PendingHarvestWindow,
    PendingPlayMinor,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space

from tests.factories import with_majors, with_phase, with_resources
from tests.test_utils import sole_play_minor

_HARVEST_PHASES = (Phase.HARVEST_FIELD, Phase.HARVEST_FEED, Phase.HARVEST_BREED)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, idx):
    p = state.players[idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == idx else state.players[i] for i in range(2)),
    )


def _harvest_state(*, reed=0, food=10, give_occ=True):
    """A HARVEST_FIELD-phase state at the fresh walk entry. P0 owns Braid
    Maker (unless give_occ is False) and holds `reed` reed + `food` food;
    P1 is food-rich so its frames resolve trivially."""
    state = with_phase(setup(seed=0), Phase.HARVEST_FIELD)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    state = with_resources(state, 0, food=food, reed=reed)
    state = with_resources(state, 1, food=99)
    return state


def _neutral_action(state):
    """An action that advances the harvest walk WITHOUT firing the exchange:
    the mechanical commits first, then Proceed/Stop, never a FireTrigger or a
    CommitHarvestConversion."""
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


def _exchange_offers(state):
    """Every surface currently offering the exchange: window/breed
    FireTriggers and feed-frame CommitHarvestConversions for this card."""
    return [
        a for a in legal_actions(state)
        if (isinstance(a, FireTrigger) and a.card_id == CARD_ID)
        or (isinstance(a, CommitHarvestConversion) and a.conversion_id == CARD_ID)
    ]


def _walk_until(state, stop_pred, *, max_steps=500):
    """Neutral-step the harvest walk until stop_pred(state) or the harvest
    ends. Returns (state, offers_seen): every exchange offer observed at
    decisions stepped THROUGH (not the stop state itself)."""
    offers_seen = []
    state = _advance_until_decision(state)
    for _ in range(max_steps):
        if state.phase not in _HARVEST_PHASES:
            return state, offers_seen
        if stop_pred(state):
            return state, offers_seen
        offers_seen.extend(_exchange_offers(state))
        state = step(state, _neutral_action(state))
    raise AssertionError("harvest walk did not terminate")


def _top_is_p0_feed(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return isinstance(top, PendingHarvestFeed) and top.player_idx == 0


def _top_is_p0_window(state):
    top = state.pending_stack[-1] if state.pending_stack else None
    return isinstance(top, PendingHarvestWindow) and top.player_idx == 0


def _top_is_p0_end_of_harvest(state):
    return _top_is_p0_window(state) and \
        state.pending_stack[-1].window_id == "end_of_harvest"


def _major9_commits(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitBuildMajor) and a.major_idx == BASKETMAKER_IDX]


def _build_state(*, give_occ=True, provenance="major_minor_improvement", **res):
    """A Family-shape state with a bare PendingBuildMajor on top for P0 (the
    Major Improvement composite / House Redevelopment provenance strings —
    neither is a "card:" grant, so granted_by is None on both) and P0 holding
    exactly the given resources."""
    state = setup(seed=0)
    if give_occ:
        state = _give_occupation(state, 0)
    state = with_resources(state, 0, **res)
    return dataclasses.replace(state, pending_stack=(
        PendingBuildMajor(player_idx=0, initiated_by_id=provenance),))


def _mp_state(*, hand_minors=frozenset(), give_occ=True, **res):
    """A CARDS-mode state with the current player owning Braid Maker (unless
    give_occ=False), the given hand minors, and exactly the given resources;
    the opponent's hand is emptied. Returns (state, current_player)."""
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    p = fast_replace(
        p,
        hand_minors=frozenset(hand_minors),
        occupations=(p.occupations | {CARD_ID}) if give_occ else p.occupations,
        resources=Resources(**res),
    )
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    return cs, cp


# --- Registration -----------------------------------------------------------

def test_registered_on_every_surface():
    # A no-op on-play occupation (pure recurring effects).
    assert CARD_ID in OCCUPATIONS
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) is state

    # The conversion row: exactly 1 reed -> 2 food, no riders, no variants,
    # frontier-eligible (a pure building-resource converter — rulings 37/74).
    spec = HARVEST_CONVERSIONS[CARD_ID]
    assert spec.input_cost == Resources(reed=1)
    assert spec.food_out == 2
    assert spec.side_effect_fn is None
    assert spec.variants_fn is None
    assert spec.frontier_fire == ((0, 0, 1, 0), 2)

    # The free span: a trigger on EVERY free-span event, with the window hooks
    # indexed for the non-sentinel windows.
    for event in FREE_SPAN_EVENTS:
        assert any(e.card_id == CARD_ID for e in TRIGGERS.get(event, ())), event
        if event not in SENTINEL_WINDOWS:
            assert CARD_ID in HARVEST_WINDOW_CARDS.get(event, set()), event

    # The named-minor-action build seam row (ruling 74).
    assert MINOR_ACTION_MAJOR_BUILDS[CARD_ID] == BASKETMAKER_IDX
    # The swap trigger on the play-minor frame's before-window.
    assert any(e.card_id == CARD_ID for e in TRIGGERS.get("before_play_minor", ()))

    # The 1r+1s whole-cost formula on build_major.
    assert any(cid == CARD_ID for cid, _a, _f in FORMULA_MODS.get("build_major", ()))


# --- The 1-reed-1-stone formula (clause 2a; ruling 74: major builds too) -----

def test_formula_prices_basketmakers_at_one_reed_one_stone():
    """With only 1 reed + 1 stone (the printed 2r+2s unaffordable), the owner
    can still build the Basketmaker's at the Major Improvement composite."""
    state = _build_state(reed=1, stone=1)
    assert _major9_commits(state) == [CommitBuildMajor(
        major_idx=BASKETMAKER_IDX, payment=Resources(reed=1, stone=1))]


def test_formula_dominates_the_printed_cost():
    """With 2r+2s held, only the 1r+1s payment surfaces — the printed base is
    Pareto-dominated by the formula (the Oven Site pipeline precedent, so
    further reductions/conversions could stack downstream)."""
    state = _build_state(reed=2, stone=2)
    assert _major9_commits(state) == [CommitBuildMajor(
        major_idx=BASKETMAKER_IDX, payment=Resources(reed=1, stone=1))]


def test_formula_applies_via_house_redevelopment():
    """Ruling 74: the price covers EVERY build of the Basketmaker's by the
    owner — the House Redevelopment build-major frame prices it 1r+1s too."""
    state = _build_state(reed=1, stone=1, provenance="house_redevelopment")
    assert _major9_commits(state) == [CommitBuildMajor(
        major_idx=BASKETMAKER_IDX, payment=Resources(reed=1, stone=1))]


def test_formula_owner_only():
    # Non-owner with 1r+1s: the Basketmaker's is not affordable at all.
    assert _major9_commits(_build_state(give_occ=False, reed=1, stone=1)) == []
    # Non-owner with the printed cost: pays 2r+2s, no discount.
    assert _major9_commits(_build_state(give_occ=False, reed=2, stone=2)) == [
        CommitBuildMajor(major_idx=BASKETMAKER_IDX,
                         payment=Resources(reed=2, stone=2))]


def test_build_executes_at_the_formula_price():
    state = _build_state(reed=1, stone=1)
    state = step(state, _major9_commits(state)[0])
    assert state.board.major_improvement_owners[BASKETMAKER_IDX] == 0
    res = state.players[0].resources
    assert res.reed == 0 and res.stone == 0


# --- The seam's options predicate (clause 2b gate) ---------------------------

def test_minor_action_build_options_gate():
    # Owner + affordable + unbuilt -> one braid_maker entry.
    cs, cp = _mp_state(reed=1, stone=1)
    assert (CARD_ID, BASKETMAKER_IDX) in minor_action_major_build_options(cs, cp)
    # Non-owner -> nothing.
    cs2, cp2 = _mp_state(give_occ=False, reed=1, stone=1)
    assert minor_action_major_build_options(cs2, cp2) == []
    # Unaffordable (no reed/stone) -> nothing.
    cs3, cp3 = _mp_state()
    assert minor_action_major_build_options(cs3, cp3) == []
    # Basketmaker's already built -> nothing.
    cs4, cp4 = _mp_state(reed=1, stone=1)
    cs4 = with_majors(cs4, owner_by_idx={BASKETMAKER_IDX: 1 - cp4})
    assert minor_action_major_build_options(cs4, cp4) == []


# --- The named-minor-action build, end-to-end (CARDS mode) -------------------

def test_meeting_place_swap_builds_basketmakers_with_no_playable_minor():
    """Meeting Place, empty hand: the minor branch is takeable purely on the
    seam's gate; the frame's only action is the swap trigger; firing it
    converts the named action into the 1r+1s Basketmaker's build."""
    cs, cp = _mp_state(reed=1, stone=1)
    cs = step(cs, PlaceWorker(space="meeting_place"))

    # The branch is gated IN despite no playable hand minor (the seam's gate).
    acts = legal_actions(cs)
    assert ChooseSubAction(name="play_minor") in acts
    assert Proceed() in acts

    cs = step(cs, ChooseSubAction(name="play_minor"))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingPlayMinor) and top.minor_improvement_action
    # No hand minor is playable, so the swap trigger is the frame's only action
    # (the gate<->eligibility agreement the seam's caller contract demands).
    assert legal_actions(cs) == [FireTrigger(card_id=CARD_ID)]

    cs = step(cs, FireTrigger(card_id=CARD_ID))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingBuildMajor)
    assert top.allowed_majors == (BASKETMAKER_IDX,)
    # Menu-restricted to the Basketmaker's, priced by the formula.
    acts = legal_actions(cs)
    assert acts == [CommitBuildMajor(major_idx=BASKETMAKER_IDX,
                                     payment=Resources(reed=1, stone=1))]

    cs = step(cs, acts[0])
    assert cs.board.major_improvement_owners[BASKETMAKER_IDX] == cp
    res = cs.players[cp].resources
    assert res.reed == 0 and res.stone == 0

    # Unwind: build-major after-phase, then the Meeting Place parent.
    assert legal_actions(cs) == [Stop()]
    cs = step(cs, Stop())
    assert legal_actions(cs) == [Proceed()]     # minor branch consumed
    cs = step(cs, Proceed())
    assert legal_actions(cs) == [Stop()]
    cs = step(cs, Stop())
    assert cs.pending_stack == ()


def test_meeting_place_decline_by_playing_a_minor_normally():
    """With a playable hand minor, both routes surface at the frame; playing
    the minor normally is the swap's implicit decline."""
    cs, cp = _mp_state(hand_minors={"market_stall"}, grain=1, reed=1, stone=1)
    cs = step(cs, PlaceWorker(space="meeting_place"))
    cs = step(cs, ChooseSubAction(name="play_minor"))

    acts = legal_actions(cs)
    assert FireTrigger(card_id=CARD_ID) in acts
    play = sole_play_minor(cs, "market_stall")
    assert play in acts

    cs = step(cs, play)
    # The minor was played; the Basketmaker's was NOT built, resources kept.
    assert cs.board.major_improvement_owners[BASKETMAKER_IDX] is None
    res = cs.players[cp].resources
    assert res.reed == 1 and res.stone == 1
    # After-phase: the before_play_minor swap is no longer offered.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(cs)
    assert Stop() in legal_actions(cs)


def test_meeting_place_branch_stays_gated_without_the_build():
    """No playable minor AND no available swap -> the branch is not offered
    (exactly the pre-seam gate)."""
    # Unaffordable swap (no reed/stone).
    cs, _cp = _mp_state()
    cs = step(cs, PlaceWorker(space="meeting_place"))
    assert legal_actions(cs) == [Proceed()]
    # Basketmaker's already built.
    cs2, cp2 = _mp_state(reed=1, stone=1)
    cs2 = with_majors(cs2, owner_by_idx={BASKETMAKER_IDX: 1 - cp2})
    cs2 = step(cs2, PlaceWorker(space="meeting_place"))
    assert legal_actions(cs2) == [Proceed()]
    # Card not owned.
    cs3, _cp3 = _mp_state(give_occ=False, reed=1, stone=1)
    cs3 = step(cs3, PlaceWorker(space="meeting_place"))
    assert legal_actions(cs3) == [Proceed()]


# --- The reed -> 2-food exchange: the feed-frame fire ------------------------

def test_feed_frame_fire_spends_one_reed_and_grants_two_food():
    state, _ = _walk_until(_harvest_state(reed=1), _top_is_p0_feed)
    assert _top_is_p0_feed(state)
    assert CommitHarvestConversion(conversion_id=CARD_ID) in legal_actions(state)

    res0 = state.players[0].resources
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))

    res1 = state.players[0].resources
    assert res1.reed == res0.reed - 1
    assert res1.food == res0.food + 2
    assert CARD_ID in state.players[0].harvest_conversions_used
    # "Each harvest" = once: the frame no longer offers it.
    assert CommitHarvestConversion(conversion_id=CARD_ID) not in legal_actions(state)


def test_feed_fire_withholds_every_later_span_surface():
    """Shared budget, feed -> windows direction: after firing on the feed
    frame, no free-span surface offers the exchange for the rest of the
    harvest."""
    state, _ = _walk_until(_harvest_state(reed=2), _top_is_p0_feed)
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    state, offers_seen = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES  # the harvest ran to completion
    assert offers_seen == []                   # despite the second reed


# --- The window fire, incl. end_of_harvest on a post-feed reed gain ----------

def test_window_fire_spends_one_reed_and_withholds_the_feed_offer():
    """The exchange surfaces as a FireTrigger at the first in-span window of
    the owner's band; firing it applies -1 reed / +2 food, marks the budget,
    and withholds the feed-frame offer (window -> feed direction)."""
    state, _ = _walk_until(_harvest_state(reed=1), _top_is_p0_window)
    top = state.pending_stack[-1]
    assert top.window_id in FREE_SPAN_EVENTS
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)
    assert Proceed() in legal_actions(state)   # declining stays open

    res0 = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID))
    res1 = state.players[0].resources
    assert res1.reed == res0.reed - 1
    assert res1.food == res0.food + 2
    assert CARD_ID in state.players[0].harvest_conversions_used

    state, offers_before_feed = _walk_until(state, _top_is_p0_feed)
    assert _top_is_p0_feed(state)
    assert offers_before_feed == []
    assert CommitHarvestConversion(conversion_id=CARD_ID) not in legal_actions(state)
    state, offers_after = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []


def test_end_of_harvest_fire_on_a_post_feed_reed_gain():
    """Ruling 74's late offering: reed that arrives AFTER feeding can still be
    exchanged at end_of_harvest — the span's last window."""
    # Start reedless: no surface offers the exchange up to and at the feed.
    state, offers = _walk_until(_harvest_state(reed=0), _top_is_p0_feed)
    assert offers == []
    assert CommitHarvestConversion(conversion_id=CARD_ID) not in legal_actions(state)
    # Resolve P0's feeding, then simulate a post-feed reed gain.
    state = step(state, _neutral_action(state))
    p = state.players[0]
    p = dataclasses.replace(p, resources=p.resources + Resources(reed=1))
    state = dataclasses.replace(
        state, players=(p, state.players[1]))

    # The walk now reaches an end_of_harvest window frame for P0.
    state, _ = _walk_until(state, _top_is_p0_end_of_harvest)
    assert _top_is_p0_end_of_harvest(state)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)

    res0 = state.players[0].resources
    state = step(state, FireTrigger(card_id=CARD_ID))
    res1 = state.players[0].resources
    assert res1.reed == res0.reed - 1
    assert res1.food == res0.food + 2
    assert CARD_ID in state.players[0].harvest_conversions_used
    # The frame offers only the decline now; the harvest then completes.
    assert legal_actions(state) == [Proceed()]
    state, offers_after = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert offers_after == []


# --- Fresh next harvest ------------------------------------------------------

def test_next_harvest_offers_the_exchange_again():
    """The budget is per-harvest: after a fire in one harvest, a fresh harvest
    entry resets harvest_conversions_used and offers the exchange anew."""
    state, _ = _walk_until(_harvest_state(reed=2), _top_is_p0_feed)
    state = step(state, CommitHarvestConversion(conversion_id=CARD_ID))
    state, _ = _walk_until(state, lambda s: False)
    assert state.phase not in _HARVEST_PHASES
    assert CARD_ID in state.players[0].harvest_conversions_used  # survives...
    assert state.players[0].resources.reed == 1                  # ...one reed left

    # Harvest 2: synthesize a fresh FIELD entry (the walk resets the budget at
    # a None-cursor HARVEST_FIELD entry).
    state = dataclasses.replace(
        state, phase=Phase.HARVEST_FIELD, pending_stack=(), harvest_cursor=None)
    state, _ = _walk_until(state, _top_is_p0_window)
    assert _top_is_p0_window(state)
    assert CARD_ID not in state.players[0].harvest_conversions_used
    assert FireTrigger(card_id=CARD_ID) in legal_actions(state)


# --- The raise-frame reach (rulings 34/37 via frontier_fire) -----------------

# A synthetic resume so a hand-built frame can be stepped through the executor
# (registered once; only frames naming it ever reach it).
FOOD_PAYMENT_RESUMES["_test_braid_maker_resume"] = lambda state, idx: state


def _in_span_state(*, reed=0, grain=0, food=0, owe=2, owned=True):
    """A hand-built in-span PendingFoodPayment (the stone_carver idiom): P0
    mid-BREED phase, post-both-breed-passes, owing `owe` food."""
    state = setup(3)
    state = fast_replace(state, starting_player=0)
    p = state.players[0]
    if owned:
        p = fast_replace(p, occupations=p.occupations | frozenset({CARD_ID}))
    p = fast_replace(
        p,
        resources=Resources(reed=reed, grain=grain, food=food),
        animals=fast_replace(p.animals, sheep=0, boar=0, cattle=0),
    )
    frame = PendingFoodPayment(
        player_idx=0, food_needed=food + owe,
        resume_kind="_test_braid_maker_resume", reserved=Cost())
    cur = sentinel_position("after_breeding", 1)
    return fast_replace(
        state,
        players=tuple(p if i == 0 else state.players[i] for i in range(2)),
        phase=Phase.HARVEST_BREED, pending_stack=(frame,), harvest_cursor=cur)


def test_raise_frame_offers_and_fires_the_exchange():
    s = _in_span_state(reed=1, owe=2)
    assert available_span_converters(s, 0) == ((CARD_ID, (0, 0, 1, 0), 2),)
    assert legal_actions(s) == [CommitFoodPayment(
        grain=0, veg=0, sheep=0, boar=0, cattle=0, conversions=(CARD_ID,))]
    nxt = step(s, legal_actions(s)[0])
    p = nxt.players[0]
    assert p.resources.reed == 0
    assert p.resources.food == 2            # raise-only: the 2 food banked (the
    #                                         no-op test resume debits nothing)
    assert CARD_ID in p.harvest_conversions_used


def test_raise_frame_unowned_sees_no_converter():
    # Grain covers the owed food, so the frontier is non-empty without the
    # (unowned) converter — which must not appear in any offered config.
    s = _in_span_state(reed=1, grain=2, owe=2, owned=False)
    assert available_span_converters(s, 0) == ()
    assert all(a.conversions == () for a in legal_actions(s))


# --- Ownership / Family negatives --------------------------------------------

def test_unowned_harvest_surfaces_nothing_new():
    """The Family shape: with the occupation unowned (every Family game), the
    whole harvest walk surfaces no exchange offer and pushes no window frame —
    the registrations are ownership-gated on every surface."""
    saw_window_frame = False
    state = _advance_until_decision(_harvest_state(reed=3, give_occ=False))
    for _ in range(500):
        if state.phase not in _HARVEST_PHASES:
            break
        assert _exchange_offers(state) == []
        if any(isinstance(f, PendingHarvestWindow) for f in state.pending_stack):
            saw_window_frame = True
        state = step(state, _neutral_action(state))
    else:
        raise AssertionError("harvest walk did not terminate")
    assert not saw_window_frame


def test_non_owner_seat_never_offered():
    """The registrations are global; only the occupation owner sees the
    exchange. P1 (reed-rich) must never be offered either surface."""
    state = _advance_until_decision(_harvest_state(reed=1))
    state = with_resources(state, 1, food=99, reed=5)
    saw_p1_offer = False
    for _ in range(500):
        if state.phase not in _HARVEST_PHASES:
            break
        top = state.pending_stack[-1] if state.pending_stack else None
        if top is not None and getattr(top, "player_idx", None) == 1 \
                and _exchange_offers(state):
            saw_p1_offer = True
        state = step(state, _neutral_action(state))
    else:
        raise AssertionError("harvest walk did not terminate")
    assert not saw_p1_offer
