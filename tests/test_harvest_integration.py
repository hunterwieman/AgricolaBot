"""End-to-end multi-round integration tests for the harvest pipeline (Task 7).

Exercises the full FIELD → FEED → BREED → PREPARATION (or BEFORE_SCORING)
flow across multiple harvests, plus invariants on phase coverage, budget
reset, and begging-marker propagation into scoring.
"""
from __future__ import annotations

import dataclasses

import pytest

from agricola.actions import CommitBreed, CommitConvert, CommitHarvestConversion, Stop
from agricola.constants import HARVEST_ROUNDS, NUM_ROUNDS, Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingHarvestBreed,
    PendingHarvestFeed,
)
from agricola.scoring import score
from agricola.setup import setup

from tests.factories import (
    with_majors,
    with_phase,
    with_resources,
    with_round,
)
from tests.test_utils import random_agent_play


# --- Random agent over many seeds -------------------------------------------

@pytest.mark.parametrize("seed", list(range(20)))
def test_random_agent_reaches_before_scoring(seed):
    """Across many seeds, random_agent_play runs to BEFORE_SCORING without
    raising. Round 14 + empty stack + RETURN_HOME-already-done is the
    canonical terminal."""
    state, _trace = random_agent_play(setup(seed=seed), seed=seed)
    assert state.phase == Phase.BEFORE_SCORING
    assert state.round_number == NUM_ROUNDS
    assert state.pending_stack == ()


def test_harvest_phases_reached_across_seeds():
    """Across 10 seeds, every harvest phase is reached at least once."""
    from agricola.engine import step
    from agricola.legality import legal_actions
    import numpy as np

    phases_seen = set()
    pendings_seen = set()
    for seed in range(10):
        state = setup(seed=seed)
        rng = np.random.default_rng(seed)
        while state.phase != Phase.BEFORE_SCORING:
            phases_seen.add(state.phase)
            if state.pending_stack:
                pendings_seen.add(type(state.pending_stack[-1]).__name__)
            actions = legal_actions(state)
            state = step(state, actions[int(rng.integers(len(actions)))])

    # Note: HARVEST_FIELD is mechanical and never observed mid-step
    # (it transitions to HARVEST_FEED inside _resolve_harvest_field).
    assert Phase.HARVEST_FEED in phases_seen
    assert Phase.HARVEST_BREED in phases_seen
    assert "PendingHarvestFeed" in pendings_seen
    assert "PendingHarvestBreed" in pendings_seen


# --- Specific round transitions ---------------------------------------------

def test_round_14_terminal_transition():
    """After round 14's HARVEST_BREED, the engine transitions to BEFORE_SCORING.

    We construct a state with both BREED pendings empty (Stop'd) by setting
    phase=HARVEST_BREED with an empty stack at round 14 — _advance_until_decision
    will then transition to BEFORE_SCORING.
    """
    state = setup(seed=0)
    state = with_round(state, NUM_ROUNDS)
    state = with_phase(state, Phase.HARVEST_BREED)
    # Empty stack = phase-exit signal.
    state = dataclasses.replace(state, pending_stack=())
    # Drive _advance_until_decision via a dummy no-op step: easiest path is
    # to import _advance_until_decision directly.
    from agricola.engine import _advance_until_decision
    state = _advance_until_decision(state)
    assert state.phase == Phase.BEFORE_SCORING
    assert state.round_number == NUM_ROUNDS


def test_round_4_breed_exit_transitions_to_preparation():
    """After round 4's BREED, phase=PREPARATION; PREPARATION then increments
    to round 5."""
    state = setup(seed=0)
    state = with_round(state, 4)
    state = with_phase(state, Phase.HARVEST_BREED)
    state = dataclasses.replace(state, pending_stack=())
    from agricola.engine import _advance_until_decision
    state = _advance_until_decision(state)
    # PREPARATION ran -> round 5, phase WORK.
    assert state.phase == Phase.WORK
    assert state.round_number == 5


# --- Budget reset across harvests -------------------------------------------

def test_harvest_conversions_used_resets_each_harvest():
    """A craft used in harvest 1 is available again in harvest 2."""
    # Set up player with Joinery + 2 wood + 0 food; force player 0 SP.
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_majors(state, owner_by_idx={7: 0})  # Joinery
    state = with_resources(state, 0, food=0, wood=2)
    state = with_resources(state, 1, food=99)
    state = with_round(state, 4)
    state = with_phase(state, Phase.HARVEST_FIELD)

    from agricola.engine import _resolve_harvest_field, _advance_until_decision
    state = _resolve_harvest_field(state)
    assert state.players[0].harvest_conversions_used == frozenset()

    # Player 0 fires Joinery, then fully commits with begging.
    state = step(state, CommitHarvestConversion(conversion_id="joinery"))
    assert "joinery" in state.players[0].harvest_conversions_used

    # Continue through FEED + BREED for both players via the random-agent loop.
    import numpy as np
    rng = np.random.default_rng(0)
    while state.phase != Phase.BEFORE_SCORING and state.round_number < 5:
        actions = legal_actions(state)
        state = step(state, actions[int(rng.integers(len(actions)))])

    # By round 5+ (post-PREPARATION), harvest_conversions_used should be empty.
    # The reset happens at the NEXT harvest's _resolve_harvest_field; check
    # that on round 7 (next HARVEST_ROUND).
    # Speed-test by forcing state into round 7 HARVEST_FIELD.
    state = with_round(state, 7)
    state = with_phase(state, Phase.HARVEST_FIELD)
    # Pre-populate to confirm reset overrides.
    state = dataclasses.replace(
        state,
        players=tuple(
            dataclasses.replace(p, harvest_conversions_used=frozenset({"joinery"}))
            for p in state.players
        ),
    )
    state = _resolve_harvest_field(state)
    for p in state.players:
        assert p.harvest_conversions_used == frozenset()


# --- Begging propagates to scoring ------------------------------------------

def test_begging_markers_propagate_to_score():
    """Begging markers from FEED show up in score (negative contribution)."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=0)
    state = with_resources(state, 1, food=99)
    state = with_round(state, 4)
    state = with_phase(state, Phase.HARVEST_FIELD)

    from agricola.engine import _resolve_harvest_field
    state = _resolve_harvest_field(state)
    # Player 0 has 0 food, need=4, no convertibles. Only CommitConvert(0,0,0,0,0);
    # _execute_convert pays 0 food and assigns 4 begging markers.
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    state = step(state, Stop())

    assert state.players[0].begging_markers == 4

    # Score reflects the 4 begging markers (-3 each = -12).
    total, breakdown = score(state, 0)
    assert breakdown.begging_markers == -12


# --- Pending stack shape during multi-player FEED ---------------------------

def test_fed_stack_evolves_correctly():
    """Walk FEED and BREED for both players — banded per ruling 40
    (2026-07-12): ONE frame per band pass, starting player's whole pass
    before the other player's, the cursor carrying the walk between them."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = with_resources(state, 0, food=99)
    state = with_resources(state, 1, food=99)
    state = with_round(state, 4)
    state = with_phase(state, Phase.HARVEST_FIELD)
    from agricola.engine import _resolve_harvest_field
    state = _resolve_harvest_field(state)

    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingHarvestFeed)
    assert state.pending_stack[-1].player_idx == 0

    # SP commits + stops; the walk resumes and pushes the OTHER player's frame.
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    state = step(state, Stop())

    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingHarvestFeed)
    assert state.pending_stack[-1].player_idx == 1

    # Player 1 commits + stops -> the BREED band, again one frame per pass.
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    state = step(state, Stop())

    assert state.phase == Phase.HARVEST_BREED
    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingHarvestBreed)
    assert state.pending_stack[-1].player_idx == 0

    state = step(state, legal_actions(state)[0])           # SP breeds/commits
    while state.pending_stack and state.pending_stack[-1].player_idx == 0:
        state = step(state, legal_actions(state)[0])
    assert len(state.pending_stack) == 1
    assert isinstance(state.pending_stack[-1], PendingHarvestBreed)
    assert state.pending_stack[-1].player_idx == 1


# --- Newborn discount applied at FEED ---------------------------------------

def test_newborn_discount_applied_at_round_4_feed():
    """Player with newborn from round 4 (a Family Growth this round) -> need
    reduced by 1 at this harvest's FEED.

    Verified end-to-end: 2 adults + 1 newborn has need = 2*3 - 1 = 5 (not 6),
    so a 0-food player with no convertibles ends with 5 begging markers
    (not 6) after the gratuitous CommitConvert."""
    state = setup(seed=0)
    state = dataclasses.replace(state, starting_player=0)
    state = dataclasses.replace(
        state,
        players=(
            dataclasses.replace(state.players[0],
                                people_total=3, people_home=3, newborns=1),
            state.players[1],
        ),
    )
    state = with_resources(state, 0, food=0)
    state = with_resources(state, 1, food=99)
    state = with_round(state, 4)
    state = with_phase(state, Phase.HARVEST_FIELD)
    from agricola.engine import _resolve_harvest_field
    state = _resolve_harvest_field(state)

    # CommitConvert(0,...) pays 0 food and assigns begging = need = 5.
    state = step(state, CommitConvert(0, 0, 0, 0, 0))
    assert state.players[0].begging_markers == 5


# --- Harvest occurs at every HARVEST_ROUND ----------------------------------

def test_all_six_harvests_fire_in_sequence():
    """Across a deterministic random play, harvests fire at rounds 4, 7, 9,
    11, 13, 14. We track which round each FEED was entered at."""
    import numpy as np
    state = setup(seed=0)
    rng = np.random.default_rng(0)
    feed_rounds = set()
    while state.phase != Phase.BEFORE_SCORING:
        if state.phase == Phase.HARVEST_FEED and state.pending_stack:
            feed_rounds.add(state.round_number)
        actions = legal_actions(state)
        state = step(state, actions[int(rng.integers(len(actions)))])
    assert feed_rounds == HARVEST_ROUNDS
