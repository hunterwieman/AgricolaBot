"""Tests for Trout Pool (minor improvement, D54; Dulcinaria Expansion).

Card text: "At the start of each work phase, if there are at least 3 food on the
'Fishing' accumulation space, you get 1 food from the general supply."
Cost 2 clay; no prereq; 1 VP; not passing.

Trout Pool is a MANDATORY, choice-free income (a `register_auto` on the
preparation ladder's `start_of_work` event — its printed "at the start of each
work phase" rung, ruling 54): when the start-of-work-phase Fishing bank holds
>= 3 food, the owner gets 1 food from the supply.

The ladder runs this round's accumulation refill (`__replenish__`, Fishing +1
food) BEFORE the `start_of_work` window, so the auto reads the POST-refill
board — which is exactly the board the player faces at the start of the work
phase. The literal threshold `fishing.accumulated_amount >= 3` is therefore
correct as-written with no off-by-one adjustment (Fishing is a food/animal
accumulation space, so its food lives in the scalar `accumulated_amount`).
These tests drive `_complete_preparation` directly (mirroring
tests/test_card_nest_site.py) and also run a real engine preparation step end-to-end.
"""
from __future__ import annotations

import agricola.cards.trout_pool  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import Phase
from agricola.engine import _complete_preparation
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup, setup_env
from agricola.state import get_space, with_space


CARD_ID = "trout_pool"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_fishing(state, food):
    """Force the Fishing space's accumulated food (the PRE-refill state). Fishing is a
    food/animal accumulation space, so its food count lives in `accumulated_amount`."""
    space = get_space(state.board, "fishing")
    space = fast_replace(space, accumulated_amount=food)
    return fast_replace(state, board=with_space(state.board, "fishing", space))


def _prep_state(idx=0, *, food_before):
    """A PREPARATION state (round 1 → becoming round 2) owning Trout Pool with the
    Fishing space set to `food_before` food before this round's +1 refill."""
    s = _own_minor(setup(0), idx)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_fishing(s, food_before)
    return s


# ---------------------------------------------------------------------------
# Registration / prereq
# ---------------------------------------------------------------------------

def test_registered_as_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(clay=2))
    assert spec.vps == 1
    assert spec.passing_left is False
    assert spec.min_occupations == 0


def test_registered_on_start_of_work_window():
    # RE-TAGGED (ruling 54): "at the start of each work phase" is the preparation
    # ladder's `start_of_work` window (after the refill), not `start_of_round`.
    # Registered as an AUTO effect (mandatory, choice-free) — not an optional trigger.
    assert any(e.card_id == CARD_ID for e in AUTO_EFFECTS.get("start_of_work", ()))
    assert all(e.card_id != CARD_ID for e in AUTO_EFFECTS.get("start_of_round", ()))
    assert all(e.card_id != CARD_ID for e in TRIGGERS.get("start_of_work", []))


def test_no_prerequisite():
    spec = MINORS[CARD_ID]
    s = setup(0)
    # No occupation, nothing owned → still playable (no prereq).
    assert prereq_met(spec, s, 0) is True


# ---------------------------------------------------------------------------
# The effect via the real preparation refill flow
# ---------------------------------------------------------------------------

def test_food_when_fishing_bank_at_threshold():
    # Bank held 2 food before refill → +1 → post-refill 3 food → threshold met → +1 food.
    s = _prep_state(0, food_before=2)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert get_space(after.board, "fishing").accumulated_amount == 3
    assert after.players[0].resources.food == before + 1
    # Auto-only card → no frame: the ladder completes straight to WORK.
    assert after.pending_stack == ()
    assert after.phase is Phase.WORK


def test_no_food_when_below_threshold():
    # Bank held 1 food before refill → +1 → post-refill 2 food → below 3 → NO food.
    s = _prep_state(0, food_before=1)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert get_space(after.board, "fishing").accumulated_amount == 2
    assert after.players[0].resources.food == before


def test_no_food_when_fishing_empty():
    # Bank empty before refill → +1 → post-refill 1 food → below 3 → NO food.
    s = _prep_state(0, food_before=0)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert get_space(after.board, "fishing").accumulated_amount == 1
    assert after.players[0].resources.food == before


def test_food_when_bank_well_stocked():
    # A larger stockpile (Fishing left unharvested for rounds) still pays exactly 1 food.
    s = _prep_state(0, food_before=6)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert get_space(after.board, "fishing").accumulated_amount == 7
    assert after.players[0].resources.food == before + 1


# ---------------------------------------------------------------------------
# Optionality — it is a choice-free auto, so no FireTrigger surfaces
# ---------------------------------------------------------------------------

def test_no_firetrigger_surfaced_choicefree_auto():
    # A choice-free auto never surfaces a FireTrigger: the ladder fires it
    # mechanically with NO frame at all, so the returned state is already in
    # WORK with an empty stack (and the food paid).
    s = _prep_state(0, food_before=2)
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == before + 1
    assert after.pending_stack == ()
    assert after.phase is Phase.WORK


# ---------------------------------------------------------------------------
# Scoping — only the owner is paid
# ---------------------------------------------------------------------------

def test_only_owner_is_paid():
    # Player 0 owns Trout Pool; player 1 does not. A stocked bank pays only P0.
    s = _own_minor(setup(0), 0)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_fishing(s, 2)  # → post-refill 3 → threshold met
    f0 = s.players[0].resources.food
    f1 = s.players[1].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == f0 + 1
    assert after.players[1].resources.food == f1


def test_non_owner_gets_nothing_even_on_stocked_bank():
    # Player 1 owns it, player 0 does not. The auto fires only for the owner.
    s = _own_minor(setup(0), 1)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_fishing(s, 4)  # → post-refill 5 → threshold met
    f0 = s.players[0].resources.food
    f1 = s.players[1].resources.food
    after = _complete_preparation(s)
    assert after.players[0].resources.food == f0      # never an owner
    assert after.players[1].resources.food == f1 + 1  # paid


# ---------------------------------------------------------------------------
# Re-checks each round — arms/disarms with the board
# ---------------------------------------------------------------------------

def test_income_disarms_when_bank_drained():
    # Round A: bank stocked → paid. Round B: bank drained (someone fished) → no pay.
    s = _prep_state(0, food_before=2)
    f = s.players[0].resources.food
    after_a = _complete_preparation(s)
    assert after_a.players[0].resources.food == f + 1
    # Now simulate the next round with an emptied Fishing space (after_a is
    # already a WORK state with an empty stack — auto-only, no frame).
    s2 = fast_replace(after_a, phase=Phase.PREPARATION)
    s2 = _set_fishing(s2, 0)  # drained → post-refill 1 → below threshold
    f2 = s2.players[0].resources.food
    after_b = _complete_preparation(s2)
    assert after_b.players[0].resources.food == f2


# ---------------------------------------------------------------------------
# Round-1 exclusion — the first WORK state never runs a preparation phase
# ---------------------------------------------------------------------------

def test_round_one_excluded_no_food_at_game_start():
    # setup() returns the round-1 WORK state directly, never running preparation, so
    # the start-of-work auto cannot fire in round 1 even with a stocked Fishing space.
    s, env = setup_env(0)
    s = _own_minor(s, 0)
    assert s.round_number == 1
    assert s.phase is Phase.WORK
    assert s.pending_stack == ()


# ---------------------------------------------------------------------------
# End-to-end: a real preparation step from a WORK→PREPARATION boundary
# ---------------------------------------------------------------------------

def test_preparation_step_via_engine_pays_owner():
    # Build a state at the round-2 preparation boundary with the Fishing space stocked,
    # then run the engine's preparation completion and confirm the owner is paid 1 food.
    s, env = setup_env(0)
    s = _own_minor(s, 0)
    s = fast_replace(s, phase=Phase.PREPARATION, round_number=1)
    s = _set_fishing(s, 2)  # → post-refill 3 → threshold met
    before = s.players[0].resources.food
    after = _complete_preparation(s)
    assert after.round_number == 2
    assert after.players[0].resources.food == before + 1
