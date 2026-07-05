"""Tests for Winnowing Fan (minor improvement, A61; Artifex Expansion).

Card text: "After the field phase of each harvest, you can use a baking
improvement but only to turn exactly 1 grain into food. (This is not considered
a "Bake Bread" action.)"  Cost: 1 Reed. Prereq: "Baking Improvement".

Implemented per user ruling 2026-07-05 as a DIRECT best-rate conversion at the
`after_field_phase` window: 1 grain → the best owned baking rate (outcome-
identical to a 1-grain bake, whose greedy allocator uses the best rate anyway),
never touching the Bake Bread primitive — so the printed "not a Bake Bread
action" holds structurally: no before/after-bake hook can fire.
"""
from __future__ import annotations

import agricola.cards.winnowing_fan  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, Proceed
from agricola.cards.harvest_windows import HARVEST_WINDOW_CARDS
from agricola.cards.specs import MINORS
from agricola.cards.triggers import CARDS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup

from tests.factories import with_phase

CARD_ID = "winnowing_fan"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _with_major(state, idx, major_idx):
    """Give player `idx` ownership of the board major improvement `major_idx`
    (0/1 Fireplace, 2/3 Cooking Hearth, 4 Clay Oven [wait — see MAJOR order],
    board-indexed as in BoardState.major_improvement_owners)."""
    owners = list(state.board.major_improvement_owners)
    owners[major_idx] = idx
    return fast_replace(state, board=fast_replace(
        state.board, major_improvement_owners=tuple(owners)))


def _harvest_state(seed=0, food=10, grain=2):
    state = with_phase(setup(seed), Phase.HARVEST_FIELD)
    for idx in (0, 1):
        p = state.players[idx]
        p = fast_replace(p, resources=fast_replace(p.resources, food=food,
                                                   grain=grain))
        state = fast_replace(state, players=tuple(
            p if i == idx else state.players[i] for i in range(2)))
    return state


def _walk_to_window(state):
    """Advance until this card's PendingHarvestWindow surfaces (or FEED)."""
    state = _advance_until_decision(state)
    while state.phase in (Phase.HARVEST_FIELD, Phase.HARVEST_FEED,
                          Phase.HARVEST_BREED):
        top = state.pending_stack[-1] if state.pending_stack else None
        if isinstance(top, PendingHarvestWindow):
            return state
        state = step(state, legal_actions(state)[0])
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert CARD_ID in CARDS                     # an optional trigger
    assert CARD_ID in HARVEST_WINDOW_CARDS.get("after_field_phase", set())
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(reed=1))
    assert spec.prereq is not None              # "Baking Improvement"
    assert spec.vps == 0


def test_prereq_requires_a_baking_improvement():
    spec = MINORS[CARD_ID]
    state = setup(0)
    assert spec.prereq(state, 0) is False       # nothing owned
    assert spec.prereq(_with_major(state, 0, 0), 0) is True   # Fireplace


# ---------------------------------------------------------------------------
# The conversion — best owned rate, exactly 1 grain, after the field phase
# ---------------------------------------------------------------------------

def test_converts_one_grain_at_fireplace_rate():
    state = _own_minor(_with_major(_harvest_state(), 0, 0), 0)   # Fireplace: 1->2
    state = _walk_to_window(state)
    top = state.pending_stack[-1]
    assert top.window_id == "after_field_phase" and top.player_idx == 0
    g0, f0 = state.players[0].resources.grain, state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.grain == g0 - 1
    assert state.players[0].resources.food == f0 + 2


def test_best_rate_wins_with_multiple_improvements():
    # Fireplace (2) + Cooking Hearth (3): the better rate applies.
    state = _own_minor(_harvest_state(), 0)
    state = _with_major(_with_major(state, 0, 0), 0, 2)
    state = _walk_to_window(state)
    f0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == f0 + 3


def test_once_per_harvest_and_declinable():
    state = _own_minor(_with_major(_harvest_state(), 0, 0), 0)
    state = _walk_to_window(state)
    state = step(state, FireTrigger(card_id=CARD_ID))
    # Spent: only Proceed remains this window.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert _advance_until_decision(state).phase == Phase.HARVEST_FEED
    # Decline path: a fresh harvest, Proceed without firing costs nothing.
    state2 = _own_minor(_with_major(_harvest_state(seed=1), 0, 0), 0)
    state2 = _walk_to_window(state2)
    g0 = state2.players[0].resources.grain
    state2 = step(state2, Proceed())
    assert state2.players[0].resources.grain == g0


def test_not_offered_without_grain_or_improvement():
    # No grain: the window passes silently — _walk_to_window never pauses at a
    # window frame, so the whole harvest completes into PREPARATION.
    state = _own_minor(_with_major(_harvest_state(grain=0), 0, 0), 0)
    after = _walk_to_window(state)
    assert after.phase == Phase.PREPARATION
    # No baking improvement: same.
    state = _own_minor(_harvest_state(), 0)
    after = _walk_to_window(state)
    assert after.phase == Phase.PREPARATION


def test_fires_after_that_players_take():
    """Window #7 sits after the take in the owner's FIELD segment: the fields
    are already harvested when the conversion is offered."""
    from tests.factories import with_sown_fields
    state = _own_minor(_with_major(_harvest_state(grain=0), 0, 0), 0)
    state = with_sown_fields(state, 0, grain_fields=[(0, 0)])   # take yields 1 grain
    state = _walk_to_window(state)
    # The grain funding the conversion arrived FROM the take.
    assert state.players[0].resources.grain == 1
    assert state.players[0].farmyard.grid[0][0].grain == 2      # take done
    f0 = state.players[0].resources.food
    state = step(state, FireTrigger(card_id=CARD_ID))
    assert state.players[0].resources.food == f0 + 2


def test_no_bake_action_hooks_fire():
    """"This is not considered a 'Bake Bread' action": a probe auto on the
    before_bake_bread event must NOT fire when Winnowing Fan converts."""
    from agricola.cards.triggers import AUTO_EFFECTS, AutoEntry
    probe_hits = []
    entry = AutoEntry("_test_wf_probe", "before_bake_bread",
                      lambda s, i: True,
                      lambda s, i: probe_hits.append(i) or s)
    AUTO_EFFECTS.setdefault("before_bake_bread", []).append(entry)
    try:
        state = _own_minor(_with_major(_harvest_state(), 0, 0), 0)
        # Own the probe card so ownership gating passes if the event ever fired.
        p = state.players[0]
        state = fast_replace(state, players=tuple(
            fast_replace(p, occupations=p.occupations | {"_test_wf_probe"})
            if i == 0 else state.players[i] for i in range(2)))
        state = _walk_to_window(state)
        state = step(state, FireTrigger(card_id=CARD_ID))
        assert probe_hits == []          # no bake event fired
    finally:
        AUTO_EFFECTS["before_bake_bread"].remove(entry)
