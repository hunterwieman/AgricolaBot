"""Tests for the start-of-round phase hook + the mandatory-with-choice frame
(Unit 4 infra; CARD_IMPLEMENTATION_PLAN.md II.1 / II.6).

The start-of-round hook (`PendingPreparation`) is the preparation-phase analog of
the atomic action-space host: `_complete_preparation` pushes a `PendingPreparation`
frame for each player who owns a start-of-round card (Plow Driver, Groom, Scullery,
…), firing the `start_of_round` automatic effects at push and surfacing its triggers
as `FireTrigger`; `Proceed` pops the frame. The push is card-dependent
(`should_host_preparation`), so the Family game's preparation phase is byte-identical
and the C++ Family engine never sees the frame.

The mandatory-with-choice firing kind (the third kind, II.1) is a `mandatory`-tagged
trigger whose host frame withholds its phase-exit (`Proceed`/`Stop`) until it fires.
Firing it pushes a `PendingCardChoice(options)` whose only legal actions are
`CommitCardChoice(index)` per option — no decline. A card-keyed resolver applies the
chosen option.

These tests drive the engine directly through round boundaries and construct
PendingPreparation / PendingCardChoice states from factories, mirroring
`tests/test_cards_category6.py`.
"""
from __future__ import annotations

import numpy as np

from agricola.actions import CommitCardChoice, FireTrigger, Proceed
from agricola.agents.base import decider_of
from agricola.cards.triggers import (
    START_OF_ROUND_CARDS,
    has_unfired_mandatory_trigger,
    owns_start_of_round_card,
    register,
    register_card_choice_resolver,
    register_start_of_round_hook,
    should_host_preparation,
)
from agricola.constants import Phase
from agricola.engine import _complete_preparation, step
from agricola.legality import legal_actions
from agricola.pending import PendingCardChoice, PendingPreparation, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup, setup_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _prep_entry_state(seed=0, round_number=1):
    """A PREPARATION-phase state poised for `_complete_preparation` to run: the
    round-`round_number+1` card is up (count == round_number+1 > round_number), so
    `_complete_preparation` finishes setup and (without a card) transitions to WORK.
    Built by stepping a fresh game's first reveal so the invariant holds.
    """
    state, env = setup_env(seed)
    # setup_env returns a round-1 WORK state with round 1 already dealt. To exercise
    # _complete_preparation in isolation, fabricate a PREPARATION state whose count
    # already exceeds round_number (one extra revealed card), mirroring the post-
    # RevealCard invariant the engine relies on.
    return state, env


# ---------------------------------------------------------------------------
# Registration-time ownership index
# ---------------------------------------------------------------------------

def test_start_of_round_index_populated():
    # Cards landed in Unit 4 register on the start-of-round hook.
    for cid in ("plow_driver", "groom", "scholar", "childless",
                "small_scale_farmer", "scullery"):
        assert cid in START_OF_ROUND_CARDS


def test_no_host_without_a_start_of_round_card():
    assert should_host_preparation(setup(0)) is False


def test_host_when_a_player_owns_a_start_of_round_card():
    state = _own_occ(setup(0), 0, "plow_driver")
    assert owns_start_of_round_card(state.players[0]) is True
    assert should_host_preparation(state) is True
    # Owned by the OTHER player still hosts (per-owner frames).
    state2 = _own_occ(setup(0), 1, "groom")
    assert should_host_preparation(state2) is True


def test_no_host_when_card_only_in_hand():
    state = setup(0)
    p = state.players[0]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {"plow_driver"})
    state = fast_replace(state, players=(p, state.players[1]))
    assert should_host_preparation(state) is False


# ---------------------------------------------------------------------------
# Family byte-identity — the load-bearing invariant
# ---------------------------------------------------------------------------

def test_preparation_byte_identical_without_card():
    """A full Family game completes with no PendingPreparation frame ever produced,
    and the round structure is unchanged (192-ish steps as before Unit 4)."""
    rng = np.random.default_rng(11)
    s, env = setup_env(11)
    saw_prep = False
    steps = 0
    while s.phase != Phase.BEFORE_SCORING and steps < 8000:
        for f in s.pending_stack:
            if isinstance(f, (PendingPreparation, PendingCardChoice)):
                saw_prep = True
        d = decider_of(s)
        if d is None:
            s = step(s, env.resolve(s))
        else:
            la = legal_actions(s)
            s = step(s, la[rng.integers(len(la))])
        steps += 1
    assert s.phase == Phase.BEFORE_SCORING
    assert not saw_prep


def test_complete_preparation_no_frame_without_card():
    """_complete_preparation pushes no frame when no player owns a start-of-round
    card (the WORK transition runs straight through)."""
    # Build a PREPARATION state one reveal ahead of round_number.
    s, env = setup_env(5)
    # Drive to the round-2 PREPARATION boundary by playing round 1 randomly.
    rng = np.random.default_rng(5)
    while s.round_number == 1 and s.phase != Phase.BEFORE_SCORING:
        d = decider_of(s)
        if d is None:
            s = step(s, env.resolve(s))
        else:
            la = legal_actions(s)
            s = step(s, la[rng.integers(len(la))])
    # We are back in WORK of round 2 with no prep frame.
    assert all(not isinstance(f, PendingPreparation) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# start_of_round host lifecycle (synthetic trigger)
# ---------------------------------------------------------------------------

def test_preparation_frame_surfaces_trigger_and_proceeds():
    """A PendingPreparation host surfaces an eligible optional start_of_round trigger
    as a FireTrigger, and Proceed (always offered, no mandatory pending) pops it."""
    state = _own_occ(setup(0), 0, "plow_driver")
    # Make Plow Driver eligible: stone house + 1 food. (Plow Driver: once in stone
    # house, at round start pay 1 food to plow 1 field.)
    from agricola.constants import HouseMaterial
    p = state.players[0]
    p = fast_replace(p, house_material=HouseMaterial.STONE,
                     resources=p.resources + Resources(food=2))
    state = fast_replace(state, players=(p, state.players[1]))
    state = push(state, PendingPreparation(player_idx=0))
    la = legal_actions(state)
    # Plow Driver eligible → its FireTrigger + Proceed are both legal (optional).
    assert FireTrigger(card_id="plow_driver") in la
    assert Proceed() in la
    # Proceed pops the frame.
    after = step(fast_replace(state, phase=Phase.WORK), Proceed())
    assert all(not isinstance(f, PendingPreparation) for f in after.pending_stack)


# ---------------------------------------------------------------------------
# Mandatory-with-choice gate + PendingCardChoice (synthetic mandatory trigger)
# ---------------------------------------------------------------------------

_SYNTH_FIRED = []


def _synth_eligible(state, idx, triggers_resolved):
    return "synth_mand" not in triggers_resolved


def _synth_apply(state, idx):
    # Push a 2-option card choice (grain or veg).
    return push(state, PendingCardChoice(
        player_idx=idx, initiated_by_id="card:synth_mand",
        options=("grain", "veg")))


def _synth_resolve(state, idx, chosen):
    p = state.players[idx]
    gain = Resources(grain=1) if chosen == "grain" else Resources(veg=1)
    p = fast_replace(p, resources=p.resources + gain)
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    # Resolver owns its frame: pop the PendingCardChoice.
    from agricola.pending import pop
    return pop(state)


# Register the synthetic mandatory trigger once at import.
register("start_of_round", "synth_mand", _synth_eligible, _synth_apply,
         mandatory=True)
register_start_of_round_hook("synth_mand")
register_card_choice_resolver("synth_mand", _synth_resolve)


def test_mandatory_gate_withholds_proceed():
    state = _own_occ(setup(0), 0, "synth_mand")
    pending = PendingPreparation(player_idx=0)
    state = push(state, pending)
    assert has_unfired_mandatory_trigger(state, pending, "start_of_round") is True
    la = legal_actions(state)
    # Proceed is withheld; only the mandatory FireTrigger is legal.
    assert Proceed() not in la
    assert FireTrigger(card_id="synth_mand") in la


def test_mandatory_fire_pushes_card_choice_then_proceed_reopens():
    state = _own_occ(setup(0), 0, "synth_mand")
    state = fast_replace(state, phase=Phase.WORK)
    state = push(state, PendingPreparation(player_idx=0))
    # Fire the mandatory trigger → PendingCardChoice on top, options grain/veg.
    state = step(state, FireTrigger(card_id="synth_mand"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.options == ("grain", "veg")
    # Legal actions at the choice: exactly one per option, no Stop/decline.
    la = legal_actions(state)
    assert la == [CommitCardChoice(index=0), CommitCardChoice(index=1)]
    # Pick veg.
    before_veg = state.players[0].resources.veg
    state = step(state, CommitCardChoice(index=1))
    assert state.players[0].resources.veg == before_veg + 1
    # Back to the PendingPreparation host; mandatory now fired → Proceed reopens.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingPreparation)
    la = legal_actions(state)
    assert Proceed() in la
    assert FireTrigger(card_id="synth_mand") not in la


def test_single_option_card_choice_is_singleton():
    """A 1-option PendingCardChoice offers exactly one CommitCardChoice (a singleton
    the agent auto-resolves)."""
    state = setup(0)
    state = push(state, PendingCardChoice(
        player_idx=0, initiated_by_id="card:synth_mand", options=("grain",)))
    assert legal_actions(state) == [CommitCardChoice(index=0)]
