"""Tests for Bumper Crop (minor improvement, E25; Ephipparius Expansion).

Card text (verbatim): "When you play this card, immediately play the field phase
of the harvest on your farmyard only."
Free, 1 VP, prerequisite "2 Grain Fields", kept.

Per user rulings 4 and 12 (CARD_DEFERRED_PLANS.md → "Harvest-window redesign —
user rulings"): the on-play plays the field-phase EFFECT, not the phase and not a
harvest. It calls the bare ``resolution.field_take`` (1 crop per planted field,
owner's farmyard only) then ``resolution.emit_harvest_occasion`` — with NO
take-modifier fold-ins, and no phase-keyed occasion consumers firing (the phase is
WORK and the occasion source is ``"card:bumper_crop"``, so the phase gate and the
``source == "take"`` gate both keep those cards silent while the crops still
arrive).

These tests drive the on-play through a real ``PendingPlayMinor`` /
``CommitPlayMinor`` flow.
"""
from __future__ import annotations

import agricola.cards.bumper_crop  # noqa: F401  (register the card)
import agricola.cards.crack_weeder  # noqa: F401  (negative-test card)
import agricola.cards.grain_sieve  # noqa: F401  (negative-test card)

from agricola.actions import CommitPlayMinor
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType, Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell

from tests.factories import with_sown_fields

CARD_ID = "bumper_crop"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, "crack_weeder", "grain_sieve") + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _at_play_minor_frame(seed=5, *, grain_fields=((0, 1), (0, 2)), veg_fields=(),
                         own_minors=frozenset()):
    """A CARDS-mode WORK-phase state at a PendingPlayMinor host, the current
    player holding Bumper Crop in hand, with the given sown fields plowed and any
    ``own_minors`` already in the tableau (for the negative tests)."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     minor_improvements=cs.players[cp].minor_improvements | own_minors)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_sown_fields(cs, cp, grain_fields=grain_fields, veg_fields=veg_fields)
    cs = fast_replace(cs, pending_stack=(
        PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def _play(cs):
    """Fire the single CommitPlayMinor for Bumper Crop from the current frame."""
    plays = [a for a in legal_actions(cs)
             if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]
    assert len(plays) == 1                              # free -> one payment option
    return step(cs, plays[0])


# --- Registration / spec (vs the JSON: free, 1 VP, prereq "2 Grain Fields") --

def test_registered_minor_spec():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                          # cost: null -> free
    assert spec.vps == 1                                # vps: 1
    assert spec.passing_left is False                   # kept
    assert spec.prereq is not None                      # "2 Grain Fields"


def test_prereq_two_grain_fields():
    """'2 Grain Fields' = at least two FIELD cells currently holding grain. One
    grain field, or veg fields, do not qualify."""
    spec = MINORS[CARD_ID]
    state = setup(seed=0)
    assert not prereq_met(spec, state, 0)               # no fields at all
    one = with_sown_fields(state, 0, grain_fields=((0, 1),))
    assert not prereq_met(spec, one, 0)                 # only one grain field
    two = with_sown_fields(state, 0, grain_fields=((0, 1), (0, 2)))
    assert prereq_met(spec, two, 0)
    veg = with_sown_fields(state, 0, veg_fields=((0, 1), (0, 2)))
    assert not prereq_met(spec, veg, 0)                 # veg fields are not grain


def test_prereq_gates_the_play():
    """With only one grain field the play is not offered (prereq unmet)."""
    cs, _cp = _at_play_minor_frame(grain_fields=((0, 1),))
    assert not any(isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID
                   for a in legal_actions(cs))


# --- The on-play field-phase effect -----------------------------------------

def test_play_harvests_owner_fields_one_crop_each():
    """Playing the card takes 1 crop from each of the owner's planted fields —
    grain over veg, exactly 1 per field even though each is sown to 3/2."""
    cs, cp = _at_play_minor_frame(grain_fields=((0, 1), (0, 2)), veg_fields=((1, 0),))
    g0, v0 = cs.players[cp].resources.grain, cs.players[cp].resources.veg
    cs = _play(cs)

    # Two grain fields -> +2 grain; one veg field -> +1 veg (1 crop per field).
    assert cs.players[cp].resources.grain == g0 + 2
    assert cs.players[cp].resources.veg == v0 + 1
    # Each field lost exactly 1 crop (3->2 grain, 2->1 veg), never emptied.
    grid = cs.players[cp].farmyard.grid
    assert grid[0][1].grain == 2 and grid[0][2].grain == 2
    assert grid[1][0].veg == 1
    # The card is now in the tableau, out of hand.
    assert CARD_ID in cs.players[cp].minor_improvements
    assert CARD_ID not in cs.players[cp].hand_minors


def test_play_stays_in_work_phase_mid_round():
    """The effect is played mid-round (an on-play), not a harvest detour: the
    phase stays WORK and no harvest sub-phase is entered."""
    cs, _cp = _at_play_minor_frame()
    assert cs.phase == Phase.WORK
    cs = _play(cs)
    assert cs.phase == Phase.WORK


def test_play_touches_only_owners_farmyard():
    """'on your farmyard only': the opponent's sown fields are untouched."""
    cs, cp = _at_play_minor_frame()
    opp = 1 - cp
    # Sow the opponent too, and snapshot their grid + supply.
    cs = with_sown_fields(cs, opp, grain_fields=((2, 0), (2, 1)))
    opp_grid_before = cs.players[opp].farmyard.grid
    opp_grain_before = cs.players[opp].resources.grain

    cs = _play(cs)

    assert cs.players[opp].farmyard.grid == opp_grid_before   # fields unchanged
    assert cs.players[opp].resources.grain == opp_grain_before


# --- No phase-keyed cards fire (rulings 4/12) --------------------------------

def test_grain_sieve_stays_silent_but_crops_arrive():
    """Grain Sieve ('if you harvest at least 2 grain, +1 grain') gates on
    ``occasion.source == "take"`` (ruling 9). Bumper Crop's occasion is
    ``source="card:bumper_crop"``, so Grain Sieve does NOT fire even though two
    grain fields would meet its threshold — yet the 2 grain still arrive."""
    cs, cp = _at_play_minor_frame(grain_fields=((0, 1), (0, 2)),
                                  own_minors=frozenset({"grain_sieve"}))
    g0 = cs.players[cp].resources.grain
    cs = _play(cs)
    # The take delivers +2 grain; Grain Sieve's would-be +1 bonus is NOT added.
    assert cs.players[cp].resources.grain == g0 + 2


def test_crack_weeder_stays_silent_but_crops_arrive():
    """Crack Weeder ('+1 food per vegetable taken in the field phase of a
    harvest') gates on ``state.phase == Phase.HARVEST_FIELD``. Bumper Crop runs
    during WORK, so Crack Weeder does NOT fire even though a veg is taken — yet the
    veg still arrives. (Crack Weeder's +1 on-play food is irrelevant: it is
    already in the tableau, not replayed here.)"""
    cs, cp = _at_play_minor_frame(grain_fields=((0, 1), (0, 2)), veg_fields=((1, 0),),
                                  own_minors=frozenset({"crack_weeder"}))
    f0 = cs.players[cp].resources.food
    v0 = cs.players[cp].resources.veg
    cs = _play(cs)
    # The take delivers +1 veg; Crack Weeder's would-be +1 food is NOT added.
    assert cs.players[cp].resources.veg == v0 + 1
    assert cs.players[cp].resources.food == f0
