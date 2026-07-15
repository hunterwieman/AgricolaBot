"""Tests for Harvest Festival Planning (minor improvement, C72; Corbarius Exp.).

Card text (verbatim): "When you play this card, immediately carry out the field
phase of the harvest. Afterwards, you get a "Major or Minor Improvement" action."
Clarification (verbatim): "This is not a harvest and is for you only."
Cost 1 Food, prereq "2 Occupations", no VPs.

On play: the bare field-phase take on the owner's farmyard only (the Bumper Crop
ruling-4 effect — not a harvest, source ``"card:..."``, mid-WORK), THEN a
composite "Major or Minor Improvement" action (``PendingMajorMinorImprovement``,
the Angler grant) — pushed only when it has a legal child (else an unusable
no-op; the composite host has no before-phase decline). Tests drive the on-play
through a real ``PendingPlayMinor`` / ``CommitPlayMinor`` flow (the Bumper Crop
idiom).
"""
from __future__ import annotations

import agricola.cards.harvest_festival_planning  # noqa: F401  (register the card)

import pytest

from agricola.actions import ChooseSubAction, CommitPlayMinor
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType, Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingMajorMinorImprovement, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_sown_fields

CARD_ID = "harvest_festival_planning"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _at_play_minor_frame(seed=5, *, grain_fields=((0, 1), (0, 2)), veg_fields=(),
                         occ=2, resources=None):
    """A CARDS-mode WORK-phase state at a PendingPlayMinor host, the current
    player holding Harvest Festival Planning in hand with ``occ`` played
    occupations (the prereq), ``resources`` in supply, and the given sown
    fields plowed."""
    if resources is None:
        resources = Resources(food=1, wood=5, clay=5, reed=5, stone=5)
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     occupations=frozenset({f"o{i}" for i in range(occ)}),
                     resources=resources)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_sown_fields(cs, cp, grain_fields=grain_fields, veg_fields=veg_fields)
    cs = fast_replace(cs, pending_stack=(
        PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def _play(cs):
    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    assert len(plays) == 1                              # 1 food -> one payment option
    return step(cs, plays[0])


# --- Registration / spec -----------------------------------------------------

def test_registered_minor_spec():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=1))
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.min_occupations == 2                    # "2 Occupations"


def test_prereq_two_occupations():
    spec = MINORS[CARD_ID]
    state = setup(seed=0)
    assert not prereq_met(spec, state, 0)               # 0 occupations
    one = _edit_player(state, 0, occupations=frozenset({"o0"}))
    assert not prereq_met(spec, one, 0)
    two = _edit_player(state, 0, occupations=frozenset({"o0", "o1"}))
    assert prereq_met(spec, two, 0)


# --- The on-play field phase + granted improvement action -------------------

def test_play_harvests_owner_fields_then_grants_improvement_action():
    cs, cp = _at_play_minor_frame(grain_fields=((0, 1), (0, 2)), veg_fields=((1, 0),))
    g0, v0 = cs.players[cp].resources.grain, cs.players[cp].resources.veg
    cs = _play(cs)

    # Field phase: +1 crop per planted field (grain over veg), fields not emptied.
    assert cs.players[cp].resources.grain == g0 + 2
    assert cs.players[cp].resources.veg == v0 + 1
    grid = cs.players[cp].farmyard.grid
    assert grid[0][1].grain == 2 and grid[0][2].grain == 2 and grid[1][0].veg == 1
    # Paid 1 food (5 building resources still on hand for a major).
    assert cs.players[cp].resources.food == 0
    # The card is in the tableau, out of hand.
    assert CARD_ID in cs.players[cp].minor_improvements
    assert CARD_ID not in cs.players[cp].hand_minors

    # Afterwards: a composite "Major or Minor Improvement" action is on top,
    # offering the build-major choice (5 building resources afford one).
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement)
    assert top.initiated_by_id == f"card:{CARD_ID}"
    assert ChooseSubAction(name="build_major") in legal_actions(cs)


def test_play_stays_in_work_phase_not_a_harvest():
    """The field phase is an on-play effect (not a harvest detour): phase stays
    WORK — no harvest sub-phase is entered."""
    cs, _cp = _at_play_minor_frame()
    assert cs.phase == Phase.WORK
    cs = _play(cs)
    assert cs.phase == Phase.WORK


def test_play_touches_only_owners_farmyard():
    """'for you only': the opponent's sown fields and supply are untouched."""
    cs, cp = _at_play_minor_frame()
    opp = 1 - cp
    cs = with_sown_fields(cs, opp, grain_fields=((2, 0), (2, 1)))
    opp_grid_before = cs.players[opp].farmyard.grid
    opp_grain_before = cs.players[opp].resources.grain
    cs = _play(cs)
    assert cs.players[opp].farmyard.grid == opp_grid_before
    assert cs.players[opp].resources.grain == opp_grain_before


def test_improvement_action_omitted_when_no_legal_child():
    """The composite host has no before-phase decline, so an unusable granted
    action is not pushed (the Angler gate): with no building resources and no
    other hand minor, no major is affordable and no minor playable, so the field
    phase still runs but no PendingMajorMinorImprovement is pushed."""
    cs, cp = _at_play_minor_frame(grain_fields=((0, 1), (0, 2)),
                                  resources=Resources(food=1))  # only the play cost
    g0 = cs.players[cp].resources.grain
    cs = _play(cs)
    # Field phase still happened (+2 grain).
    assert cs.players[cp].resources.grain == g0 + 2
    assert CARD_ID in cs.players[cp].minor_improvements
    # ...but no improvement action was granted (no legal child).
    assert not any(isinstance(f, PendingMajorMinorImprovement)
                   for f in cs.pending_stack)


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
