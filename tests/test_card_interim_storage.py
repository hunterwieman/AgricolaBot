"""Tests for Interim Storage (minor improvement, A81).

Card text: "Each time you use a clay/reed/stone accumulation space, place 1
wood/clay/reed on this card. At the start of rounds 7, 11, and 14, move all the
goods on this card to your supply."

Two halves are exercised through real engine flows:
  ACCUMULATE — a `before_action_space` automatic effect on the four building
    accumulation spaces; driven through the hosted-space lifecycle
    (PlaceWorker → Proceed → Stop), mirroring tests/test_cards_action_space_hook.py.
  RELEASE — a `start_of_round` automatic effect; driven through the real
    `_complete_preparation` round-boundary transition, mirroring
    tests/test_cards_preparation_hook.py.
"""
from __future__ import annotations

import pytest

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    START_OF_ROUND_CARDS,
    should_host_space,
)
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space

import agricola.cards.interim_storage  # noqa: F401  (registers the card)

CARD_ID = "interim_storage"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    """A card-mode round-1 WORK state."""
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own(state, idx, minors=(CARD_ID,)):
    p = fast_replace(
        state.players[idx],
        minor_improvements=state.players[idx].minor_improvements | set(minors),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _set_held(state, idx, held: Resources):
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, held))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _held(state, idx) -> Resources:
    return state.players[idx].card_state.get(CARD_ID, Resources())


def _play_hosted_space(state, space_id):
    """Drive the full hosted lifecycle: place, then Proceed (primary effect) and
    Stop. Returns the post-turn state, asserting the singleton lifecycle shape."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    # Automatic-only card → before-phase is a singleton Proceed.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert state.pending_stack[-1].phase == "after"
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_with_cost():
    from agricola.cards.specs import MINORS
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(food=2)
    assert spec.passing_left is False
    assert spec.vps == 0


def test_registered_on_both_hooks():
    # Accumulate: before_action_space auto + the four-space hosting index.
    accum_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD_ID in accum_ids
    for sid in ("clay_pit", "reed_bank", "western_quarry", "eastern_quarry"):
        assert CARD_ID in OWN_ACTION_HOOK_CARDS[sid]
    # Release: start_of_round auto + the start-of-round ownership index.
    release_ids = {e.card_id for e in AUTO_EFFECTS.get("start_of_round", ())}
    assert CARD_ID in release_ids
    assert CARD_ID in START_OF_ROUND_CARDS


# ---------------------------------------------------------------------------
# Hosting decision
# ---------------------------------------------------------------------------

def test_hosts_only_the_four_accumulation_spaces():
    s = _own(_card_state(), 0)
    for sid in ("clay_pit", "reed_bank", "western_quarry", "eastern_quarry"):
        assert should_host_space(s, sid, 0)
    # Not a hooked space (Forest) and not when unowned.
    assert not should_host_space(s, "forest", 0)
    assert not should_host_space(_card_state(), "clay_pit", 0)


# ---------------------------------------------------------------------------
# ACCUMULATE — the good placed is one tier DOWN from the space's yield
# ---------------------------------------------------------------------------

def test_clay_pit_places_one_wood_on_card():
    s = fast_replace(_own(_card_state(), 0), current_player=0)
    before_res = s.players[0].resources
    out = _play_hosted_space(s, "clay_pit")
    # The clay space puts 1 WOOD on the card (not in supply).
    assert _held(out, 0) == Resources(wood=1)
    # The placed good came from supply onto the card, NOT from the player's stock.
    # (The player still receives the space's own accumulated clay via Proceed.)
    assert out.players[0].resources.wood == before_res.wood


def test_reed_bank_places_one_clay_on_card():
    s = fast_replace(_own(_card_state(), 0), current_player=0)
    out = _play_hosted_space(s, "reed_bank")
    assert _held(out, 0) == Resources(clay=1)


@pytest.mark.parametrize("quarry", ["western_quarry", "eastern_quarry"])
def test_quarries_place_one_reed_on_card(quarry):
    # The quarries are Stage 2/4 spaces — reveal + stock one to make it placeable.
    from agricola.state import with_space
    s = fast_replace(_own(_card_state(), 0), current_player=0)
    sp = get_space(s.board, quarry)
    s = fast_replace(
        s,
        board=with_space(
            s.board, quarry, fast_replace(sp, revealed=True, accumulated=Resources(stone=1))
        ),
    )
    out = _play_hosted_space(s, quarry)
    assert _held(out, 0) == Resources(reed=1)


def test_accumulation_stacks_across_uses():
    # Start with a wood already on the card, then use the reed space → +1 clay.
    s = fast_replace(_own(_card_state(), 0), current_player=0)
    s = _set_held(s, 0, Resources(wood=2, clay=1))
    out = _play_hosted_space(s, "reed_bank")
    assert _held(out, 0) == Resources(wood=2, clay=2)


def test_does_not_fire_for_non_owner():
    # Player 1 owns the card; player 0 uses clay_pit → nothing placed (host not
    # pushed for player 0, and the auto is owner-gated).
    s = fast_replace(_own(_card_state(), 1), current_player=0)
    assert not should_host_space(s, "clay_pit", 0)
    out = step(s, PlaceWorker(space="clay_pit"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert _held(out, 1) == Resources()


# ---------------------------------------------------------------------------
# RELEASE — at the start of rounds 7 / 11 / 14, move all goods to supply
# ---------------------------------------------------------------------------

def _enter_round(state, idx, *, from_round: int, held: Resources):
    """Own the card with `held` goods, set round_number=from_round, and run the
    real `_complete_preparation` to enter round from_round+1."""
    state = _own(state, idx)
    state = _set_held(state, idx, held)
    state = fast_replace(state, round_number=from_round)
    return _complete_preparation(state)


@pytest.mark.parametrize("release_round", [7, 11, 14])
def test_release_at_rounds_7_11_14(release_round):
    s = _card_state()
    held = Resources(wood=2, clay=1, reed=3)
    before = s.players[0].resources
    out = _enter_round(s, 0, from_round=release_round - 1, held=held)
    assert out.round_number == release_round
    # All held goods moved to supply; the card is reset to empty.
    assert _held(out, 0) == Resources()
    gained = out.players[0].resources - before
    assert gained == held


@pytest.mark.parametrize("non_release_round", [2, 5, 6, 8, 10, 12, 13])
def test_no_release_on_other_rounds(non_release_round):
    s = _card_state()
    held = Resources(wood=2)
    out = _enter_round(s, 0, from_round=non_release_round - 1, held=held)
    assert out.round_number == non_release_round
    # Goods stay on the card; nothing released.
    assert _held(out, 0) == held


def test_release_noop_when_card_empty():
    # Entering round 7 with an empty card is a clean no-op (eligibility is gated on
    # held goods being non-empty), so the card never appears in card_state.
    s = _card_state()
    out = _enter_round(s, 0, from_round=6, held=Resources())
    assert out.round_number == 7
    assert _held(out, 0) == Resources()


def test_release_only_for_owner():
    # Player 0 owns + holds goods; player 1 does not own → only P0 releases.
    s = _card_state()
    held = Resources(reed=3)
    out = _enter_round(s, 0, from_round=6, held=held)
    assert _held(out, 0) == Resources()              # P0 released + reset
    assert _held(out, 1) == Resources()              # P1 never had any
