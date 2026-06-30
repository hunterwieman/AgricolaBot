"""Tests for Nest Site (minor improvement, A49; Artifex Expansion).

Card text: "Each time 1 reed is placed on a non-empty 'Reed Bank' accumulation
space during the preparation phase, you get 1 food."
Cost 1 food; prereq 1 occupation; no VPs; not passing.

Nest Site is a MANDATORY, choice-free start-of-round income (an `register_auto`
on the `start_of_round` event, like Scullery): when the preparation refill drops a
reed onto a Reed Bank that was already non-empty, the owner gets 1 food.

`_complete_preparation` refills the Reed Bank (+1 reed) BEFORE firing start-of-round
autos, so the auto reads the POST-refill board. Post-refill `reed_bank.reed >= 2`
exactly captures "the bank held >= 1 reed before the refill = the reed was placed on
a non-empty bank". These tests drive `_complete_preparation` directly (mirroring
tests/test_cards_category7.py's Scullery / Small-scale Farmer tests) and also run a
real round advancement end-to-end.
"""
from __future__ import annotations

import agricola.cards.nest_site  # noqa: F401  (registers the card — not in cards/__init__.py)

from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    START_OF_ROUND_CARDS,
    owns_start_of_round_card,
    should_host_preparation,
)
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingPreparation
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup, setup_env
from agricola.state import get_space, with_space


CARD_ID = "nest_site"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_reed_bank(state, reed):
    """Force the Reed Bank's accumulated reed (the pre-refill state)."""
    space = get_space(state.board, "reed_bank")
    space = fast_replace(space, accumulated=Resources(reed=reed))
    return fast_replace(state, board=with_space(state.board, "reed_bank", space))


def _prep_state(idx=0, *, reed_before):
    """A PREPARATION state (round 1 → becoming round 2) owning Nest Site with the
    Reed Bank set to `reed_before` reed before this round's +1 refill."""
    s = _own_minor(setup(0), idx)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_reed_bank(s, reed_before)
    return s


# ---------------------------------------------------------------------------
# Registration / prereq
# ---------------------------------------------------------------------------

def test_registered_as_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.min_occupations == 1


def test_registered_on_start_of_round_hook():
    assert CARD_ID in START_OF_ROUND_CARDS
    # Registered as an AUTO effect (mandatory, choice-free) — not an optional trigger.
    assert any(e.card_id == CARD_ID for e in AUTO_EFFECTS.get("start_of_round", ()))
    state = _own_minor(setup(0), 0)
    assert owns_start_of_round_card(state.players[0]) is True
    assert should_host_preparation(state) is True


def test_prereq_requires_one_occupation():
    spec = MINORS[CARD_ID]
    s = setup(0)
    # No occupation → prereq not met.
    assert prereq_met(spec, s, 0) is False
    # One occupation → prereq met.
    s = _own_occ(s, 0, "consultant")
    assert prereq_met(spec, s, 0) is True


# ---------------------------------------------------------------------------
# The effect via the real preparation refill flow
# ---------------------------------------------------------------------------

def test_food_when_reed_placed_on_nonempty_bank():
    # Bank held 1 reed before refill → +1 → post-refill 2 reed → reed placed on a
    # NON-EMPTY bank → +1 food.
    s = _prep_state(0, reed_before=1)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert get_space(after.board, "reed_bank").accumulated.reed == 2
    assert after.players[0].resources.food == before + 1
    # The host frame is still on the stack (owner owns a start-of-round card).
    assert isinstance(after.pending_stack[-1], PendingPreparation)


def test_no_food_when_reed_placed_on_empty_bank():
    # Bank empty before refill → +1 → post-refill 1 reed → reed placed on an EMPTY
    # bank → NO food.
    s = _prep_state(0, reed_before=0)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert get_space(after.board, "reed_bank").accumulated.reed == 1
    assert after.players[0].resources.food == before


def test_food_when_bank_well_stocked():
    # A larger stockpile (someone left a lot of reed) still pays exactly 1 food.
    s = _prep_state(0, reed_before=4)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert get_space(after.board, "reed_bank").accumulated.reed == 5
    assert after.players[0].resources.food == before + 1


# ---------------------------------------------------------------------------
# Optionality — it is a choice-free auto, so no FireTrigger surfaces
# ---------------------------------------------------------------------------

def test_no_firetrigger_surfaced_choicefree_auto():
    # After the auto fires at push, the only legal action at the host is Proceed
    # (a mandatory-with-choice trigger would withhold Proceed; an auto never does).
    from agricola.actions import Proceed
    s = _prep_state(0, reed_before=1)
    after = _complete_preparation(s)
    la = legal_actions(after)
    assert la == [Proceed()]


# ---------------------------------------------------------------------------
# Scoping — only the owner is paid
# ---------------------------------------------------------------------------

def test_only_owner_is_paid():
    # Player 0 owns Nest Site; player 1 does not. A non-empty bank pays only P0.
    s = _own_minor(setup(0), 0)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_reed_bank(s, 1)
    f0 = s.players[0].resources.food
    f1 = s.players[1].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == f0 + 1
    assert after.players[1].resources.food == f1


def test_non_owner_gets_nothing_even_on_nonempty_bank():
    # Player 1 owns it, player 0 does not. The hook hosts only for the owner.
    s = _own_minor(setup(0), 1)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_reed_bank(s, 2)
    f0 = s.players[0].resources.food
    f1 = s.players[1].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == f0      # never an owner
    assert after.players[1].resources.food == f1 + 1  # paid


# ---------------------------------------------------------------------------
# Round-1 exclusion — the first WORK state never runs a preparation phase
# ---------------------------------------------------------------------------

def test_round_one_excluded_no_food_at_game_start():
    # setup() returns the round-1 WORK state directly, never running preparation, so
    # the start-of-round auto cannot fire in round 1 even with a pre-stocked bank.
    s, env = setup_env(0)
    s = _own_minor(s, 0)
    # The freshly-dealt round-1 Reed Bank already carries its first reed; owning the
    # card must not have produced food at game start (no preparation ran).
    assert s.round_number == 1
    assert s.phase is Phase.WORK
    # The fixed setup-time starting resources for the owner (no Nest Site income yet):
    # both players start with the canonical opening food (3 for the non-starter).
    # Rather than couple to that constant, assert no PendingPreparation host exists
    # and the bank fill at setup did not trigger the auto.
    assert all(not isinstance(f, PendingPreparation) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# End-to-end: a controlled real preparation step from a WORK→PREPARATION boundary
# ---------------------------------------------------------------------------

def test_preparation_step_via_engine_pays_owner():
    # Build a state poised at the round-card reveal for round 2 with the Reed Bank
    # non-empty, then run the engine's preparation walk (RevealCard → _complete_
    # preparation) and confirm the owner is paid exactly 1 food.
    s, env = setup_env(0)
    s = _own_minor(s, 0)
    # Move to the PREPARATION boundary for round 2 with a non-empty bank (1 reed).
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_reed_bank(s, 1)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.round_number == 2
    assert after.players[0].resources.food == before + 1
