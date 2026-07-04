"""Tests for Cube Cutter (occupation, C98).

Card text (verbatim): "When you play this card, you immediately get 1 wood. In
the field phase of each harvest, you can use this card to exchange exactly 1
wood and 1 food for 1 bonus point."

Timing: the field-phase during-window (harvest window #5). The card was
previously (mis-)implemented on the FEEDING-phase HARVEST_CONVERSIONS seam; it
now rides the "field_phase" during-window as a free-ordered, declinable,
once-per-field-phase optional trigger (HARVEST_WINDOWS_DESIGN.md §4 class (a),
user-agreed 2026-07-03). Firing it spends exactly 1 wood + 1 food, produces no
food, and banks a bonus point in the per-card CardStore, read back at end-game
by a scoring term. These tests walk a REAL harvest to the PendingFieldPhase host
and fire the trigger around the mandatory crop take (free order). Cube Cutter has
NO major/Joinery gate: owning the occupation is sufficient.
"""
from __future__ import annotations

import dataclasses

import agricola.cards.cube_cutter  # noqa: F401  (register the card)

from agricola.actions import CommitFieldTake, FireTrigger, Proceed
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CARDS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingFieldPhase
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup

from tests.factories import with_phase, with_resources, with_sown_fields

CARD_ID = "cube_cutter"


# --- Helpers ----------------------------------------------------------------

def _give_occupation(state, player_idx):
    p = state.players[player_idx]
    p = dataclasses.replace(p, occupations=p.occupations | {CARD_ID})
    return dataclasses.replace(
        state,
        players=tuple(p if i == player_idx else state.players[i] for i in range(2)),
    )


def _owner_state(*, owner_food=10, owner_wood=5, give_occ=True, seed=0):
    """P0 owns Cube Cutter and is the starting player; P1 is food-rich.

    owner_food / owner_wood govern whether the 1-wood + 1-food exchange is
    affordable. Both players get a single sown grain field so the mandatory crop
    take has something to harvest at the during-frame.
    """
    state = setup(seed=seed)
    state = dataclasses.replace(state, starting_player=0)
    if give_occ:
        state = _give_occupation(state, 0)
    state = with_resources(state, 0, food=owner_food, wood=owner_wood)
    state = with_resources(state, 1, food=99)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])
    state = with_sown_fields(state, 1, grain_fields=[(0, 0)])
    return state


def _enter_field(state):
    """Put `state` into the harvest and advance to P0's PendingFieldPhase frame."""
    state = with_phase(state, Phase.HARVEST_FIELD)
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingFieldPhase) and top.player_idx == 0:
            return state
        state = step(state, legal_actions(state)[0])
    return state


def _fire_actions(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


# --- Registration -----------------------------------------------------------

def test_registered_as_occupation_field_phase_trigger_and_scoring():
    assert CARD_ID in OCCUPATIONS
    # Registered as an optional trigger on the field-phase during-window...
    assert CARD_ID in CARDS
    assert CARDS[CARD_ID].event == "field_phase"
    # ...and hooked into the field_phase harvest window index.
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("field_phase", set())
    assert any(card_id == CARD_ID for card_id, _ in SCORING_TERMS)


def test_no_longer_registered_as_harvest_conversion():
    """The mis-timed FEEDING-phase seam registration is gone."""
    from agricola.cards.harvest_conversions import HARVEST_CONVERSIONS
    assert CARD_ID not in HARVEST_CONVERSIONS


# --- On-play: +1 wood -------------------------------------------------------

def test_on_play_grants_one_wood():
    state = setup(seed=0)
    wood0 = state.players[0].resources.wood
    on_play = OCCUPATIONS[CARD_ID].on_play
    state = on_play(state, 0)
    assert state.players[0].resources.wood == wood0 + 1
    # Opponent untouched.
    assert state.players[1].resources.wood == 0


# --- The exchange is offered around the take (free order) --------------------

def test_offered_before_and_after_the_take():
    state = _enter_field(_owner_state(owner_food=10, owner_wood=5))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFieldPhase) and top.player_idx == 0
    assert not top.take_fired

    # BEFORE the take: the trigger and the mandatory take are both offered; no
    # Proceed yet (the take is mandatory).
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts
    assert CommitFieldTake() in acts
    assert Proceed() not in acts

    # Take first, then the trigger is STILL offered afterwards (free order).
    state = step(state, CommitFieldTake())
    acts = legal_actions(state)
    assert FireTrigger(card_id=CARD_ID) in acts
    assert Proceed() in acts
    assert CommitFieldTake() not in acts


def test_exchange_spends_wood_and_food_and_banks_one_point():
    state = _enter_field(_owner_state(owner_food=10, owner_wood=5))
    assert _fire_actions(state) == [FireTrigger(card_id=CARD_ID)]

    food0 = state.players[0].resources.food
    wood0 = state.players[0].resources.wood
    state = step(state, FireTrigger(card_id=CARD_ID))

    # 1 wood + 1 food spent, no food produced; one bonus point banked.
    assert state.players[0].resources.food == food0 - 1
    assert state.players[0].resources.wood == wood0 - 1
    assert state.players[0].card_state.get(CARD_ID, 0) == 1


def test_exchange_is_once_per_field_phase():
    state = _enter_field(_owner_state(owner_food=10, owner_wood=5))
    state = step(state, FireTrigger(card_id=CARD_ID))
    # After one exchange this field phase, it is no longer offered (even with
    # goods to spare) — the frame's triggers_resolved caps it at once.
    assert _fire_actions(state) == []
    assert state.players[0].card_state.get(CARD_ID, 0) == 1


def test_exchange_is_optional_declinable():
    """Declining is implicit: take the crop, then Proceed without ever firing."""
    state = _enter_field(_owner_state(owner_food=10, owner_wood=5))
    state = step(state, CommitFieldTake())
    assert Proceed() in legal_actions(state)
    state = step(state, Proceed())
    assert state.players[0].card_state.get(CARD_ID, 0) == 0


# --- Eligibility boundaries -------------------------------------------------

def test_not_offered_to_non_owner():
    """The trigger is owner-gated: P1 does not own Cube Cutter, so its
    during-window (if any) never offers the exchange.

    With no other field_phase card owned, P1 has no during-frame at all — the
    take runs inline. Assert the exchange is offered only in P0's frame, and that
    driving the whole harvest never surfaces it for P1.
    """
    state = _owner_state(owner_food=10, owner_wood=5)
    state = with_resources(state, 1, food=10, wood=5)  # P1 also goods-rich
    state = with_phase(state, Phase.HARVEST_FIELD)
    state = _advance_until_decision(state)

    saw_fire = False
    saw_p1_frame_fire = False
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        fires = _fire_actions(state)
        if fires:
            saw_fire = True
            if isinstance(top, PendingFieldPhase) and top.player_idx == 1:
                saw_p1_frame_fire = True
        state = step(state, legal_actions(state)[0])

    assert saw_fire            # the owner IS offered the exchange
    assert not saw_p1_frame_fire   # the non-owner is NOT


def test_not_offered_during_feeding_any_more():
    """The exchange must NOT surface as any feeding-phase action.

    The old (mis-timed) implementation offered it as a CommitHarvestConversion
    during HARVEST_FEED. Walk the whole harvest and assert no legal action at any
    HARVEST_FEED step mentions cube_cutter.
    """
    from agricola.actions import CommitHarvestConversion
    state = _owner_state(owner_food=10, owner_wood=5)
    state = with_phase(state, Phase.HARVEST_FIELD)
    state = _advance_until_decision(state)

    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        if state.phase == Phase.HARVEST_FEED:
            for a in legal_actions(state):
                assert not (isinstance(a, CommitHarvestConversion)
                            and a.conversion_id == CARD_ID), (
                    "cube_cutter must not surface during feeding any more")
        state = step(state, legal_actions(state)[0])


def test_not_offered_when_wood_short():
    """Needs 1 wood; with 0 wood the exchange is unaffordable and not offered."""
    state = _enter_field(_owner_state(owner_food=10, owner_wood=0))
    assert _fire_actions(state) == []


def test_not_offered_when_food_short():
    """Needs 1 food; with 0 food the exchange is unaffordable and not offered.

    Field-phase timing is the whole point of the re-time: the food must be on
    hand DURING the field phase, before any feeding-phase conversions could cook
    wood into food.
    """
    state = _enter_field(_owner_state(owner_food=0, owner_wood=5))
    assert _fire_actions(state) == []


# --- Accumulation + scoring -------------------------------------------------

def test_points_accumulate_across_harvests_and_score():
    base = _owner_state(owner_food=10, owner_wood=5)
    base_total, _ = score(base, 0)

    # Bank two points (simulating two harvests' exchanges) then score.
    p = base.players[0]
    p = dataclasses.replace(p, card_state=p.card_state.set(CARD_ID, 2))
    state = dataclasses.replace(base, players=(p, base.players[1]))

    # The owner's end-game score gains exactly the two banked points (owner-gated
    # by score()'s _owns(card_id) check).
    owner_total, _bd = score(state, 0)
    assert state.players[0].card_state.get(CARD_ID, 0) == 2
    assert owner_total == base_total + 2

    # The scoring fn reads the bank directly.
    fn = next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)
    assert fn(state, 0) == 2


def test_scoring_owner_gated_non_owner_reads_zero():
    """A non-owner with a stray card_state entry scores 0 (score() owner-gates)."""
    base = _owner_state(owner_food=10, owner_wood=5)
    # Give P1 (the non-owner) a stray banked count; score() must ignore it.
    p1 = base.players[1]
    p1 = dataclasses.replace(p1, card_state=p1.card_state.set(CARD_ID, 3))
    state = dataclasses.replace(base, players=(base.players[0], p1))
    p1_total, _ = score(state, 1)
    base_p1_total, _ = score(base, 1)
    assert p1_total == base_p1_total  # the stray bank contributes nothing
