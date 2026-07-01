"""Tests for Baking Sheet (minor improvement, A30; Artifex Expansion):

    "Each time you take a 'Bake Bread' action, you can use this card to exchange
     exactly 1 grain for 2 food and 1 bonus point."
    Clarification: "You must bake normally to make this exchange."
    Prerequisite: "No Grain Field" (no field cell currently holds grain).

An OPTIONAL `before_bake_bread` trigger that exchanges 1 grain for 2 food + a banked
bonus point (read back at scoring). Per the Trigger-Timing ruling a bare "each time
you take a 'Bake Bread' action" fires in the BEFORE phase (the reward is flat), and
the "must bake normally" clarification is a GATE satisfied structurally: the
`PendingBakeBread` before-phase offers only FireTrigger + CommitBake (no Stop), so a
bake is still forced after the exchange. Because the exchange spends 1 grain BEFORE
that forced bake, eligibility requires `grain >= 2` (a stranding guard) so a legal
CommitBake still remains after the −1.

Each firing test drives the real Bake Bread flow through Grain Utilization (place ->
bake_bread sub-action pushes PendingBakeBread in its BEFORE-phase, where the trigger
is offered alongside the CommitBake options). Mirrors the Beer Stein tests (identical
optional-before-action banked-point shape, differing only in cost + prereq).
"""
import agricola.cards.baking_sheet  # noqa: F401  (registers the card; not yet in cards/__init__.py)

from agricola.actions import ChooseSubAction, CommitBake, FireTrigger, PlaceWorker, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup
from tests.factories import (
    with_current_player,
    with_majors,
    with_resources,
    with_sown_fields,
)

CARD_ID = "baking_sheet"


def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _bake_setup(*, owner=0, current_player=0, grain=2, seed=0):
    """Family round-1 WORK state with a legal Grain Utilization placement (grain
    + a Fireplace so the player can bake), and `owner` (idx or None) holding the
    Baking Sheet minor."""
    s = setup(seed=seed)
    s = with_current_player(s, current_player)
    s = with_resources(s, current_player, grain=grain)
    s = with_majors(s, owner_by_idx={0: current_player})   # Fireplace (idx 0)
    if owner is not None:
        s = _own_minor(s, owner)
    return s


def _bake_to_before_phase(s):
    """Drive place -> choose bake_bread; leaves the bake host in its BEFORE-phase
    (where the Baking Sheet trigger is offered alongside the CommitBake options,
    with no Stop — the bake is still mandatory)."""
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, ChooseSubAction(name="bake_bread"))
    return s


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.vps == 0                 # the point is banked, not printed
    assert spec.cost == Cost()           # no cost
    assert spec.prereq is not None       # custom "No Grain Field" prereq
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_registered_on_before_bake_bread():
    from agricola.cards.triggers import TRIGGERS
    entries = TRIGGERS.get("before_bake_bread", [])
    assert any(e.card_id == CARD_ID and not e.mandatory for e in entries), entries
    # Not on the after-phase (the old, incorrect timing).
    after = TRIGGERS.get("after_bake_bread", [])
    assert not any(e.card_id == CARD_ID for e in after), after


# ---------------------------------------------------------------------------
# Prerequisite: "No Grain Field"
# ---------------------------------------------------------------------------

def test_prereq_met_with_no_fields():
    s = setup(seed=0)
    assert prereq_met(MINORS[CARD_ID], s, 0)


def test_prereq_met_with_empty_field():
    # A plowed-but-unsown field holds no grain -> prereq still met.
    from tests.factories import with_fields
    s = with_fields(setup(seed=0), 0, [(0, 0)])
    assert s.players[0].farmyard.grid[0][0].cell_type is CellType.FIELD
    assert s.players[0].farmyard.grid[0][0].grain == 0
    assert prereq_met(MINORS[CARD_ID], s, 0)


def test_prereq_met_with_veg_field():
    # A vegetable field has grain == 0 -> it is not a "grain field" -> prereq met.
    s = with_sown_fields(setup(seed=0), 0, veg_fields=[(0, 0)])
    assert s.players[0].farmyard.grid[0][0].veg == 2
    assert prereq_met(MINORS[CARD_ID], s, 0)


def test_prereq_blocked_by_grain_field():
    s = with_sown_fields(setup(seed=0), 0, grain_fields=[(0, 0)])
    assert s.players[0].farmyard.grid[0][0].grain == 3
    assert not prereq_met(MINORS[CARD_ID], s, 0)


# ---------------------------------------------------------------------------
# Firing (BEFORE-phase): exchange 1 grain -> +2 food + 1 banked bonus point,
# with the mandatory bake still legal afterward.
# ---------------------------------------------------------------------------

def test_offered_in_before_phase():
    s = _bake_setup(owner=0, grain=2)   # exchange spends 1, leaves 1 for the bake
    s = _bake_to_before_phase(s)
    la = legal_actions(s)
    # The BEFORE-phase surfaces the optional trigger alongside CommitBake options
    # (and, per the mandatory-bake host, NO Stop).
    assert FireTrigger(card_id=CARD_ID) in la
    assert any(isinstance(a, CommitBake) for a in la)
    assert Stop() not in la


def test_fires_in_before_phase_and_bake_remains_legal():
    s = _bake_setup(owner=0, grain=2)
    s = _bake_to_before_phase(s)
    grain0 = s.players[0].resources.grain
    food0 = s.players[0].resources.food
    assert grain0 == 2
    s = step(s, FireTrigger(card_id=CARD_ID))
    # Pure state edit: -1 grain, +2 food, +1 banked point.
    assert s.players[0].resources.grain == grain0 - 1   # 1 left
    assert s.players[0].resources.food == food0 + 2
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    # The mandatory bake is NOT stranded: a legal CommitBake remains (guard worked).
    la = legal_actions(s)
    assert CommitBake(grain=1) in la
    # Finish the turn: bake normally, then pop the bake host after-phase + the
    # Grain Utilization host.
    s = step(s, CommitBake(grain=1))
    assert s.players[0].resources.grain == 0            # the last grain baked
    s = step(s, Stop())   # pop bake host after-phase
    s = step(s, Stop())   # pop the Grain Utilization host; turn ends
    assert s.pending_stack == ()


def test_scores_banked_point():
    s = _bake_setup(owner=0, grain=2)
    s = _bake_to_before_phase(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    # A direct read of the registered scoring term confirms the +1 it contributes.
    fn = next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)
    assert fn(s, 0) == 1
    # And the +1 is included in the player's full end-game score (vs a cleared bank).
    cleared = fast_replace(
        s.players[0], card_state=s.players[0].card_state.set(CARD_ID, 0))
    s_cleared = fast_replace(
        s, players=tuple(cleared if i == 0 else s.players[i] for i in range(2)))
    assert score(s, 0)[0] == score(s_cleared, 0)[0] + 1


# ---------------------------------------------------------------------------
# Optionality: declinable by baking without firing (the bake is mandatory, so
# there is no Stop in the before-phase — declining = commit the bake directly).
# ---------------------------------------------------------------------------

def test_decline_by_baking():
    s = _bake_setup(owner=0, grain=2)
    s = _bake_to_before_phase(s)
    grain0 = s.players[0].resources.grain
    food0 = s.players[0].resources.food
    s = step(s, CommitBake(grain=2))   # bake both, decline the exchange
    s = step(s, Stop())                # pop the bake host after-phase
    s = step(s, Stop())                # pop the Grain Utilization host; turn ends
    assert s.pending_stack == ()
    assert s.players[0].resources.grain == 0            # both grain baked
    # Bake produced food but the exchange banked nothing.
    assert s.players[0].resources.food == food0 + 4     # Fireplace bakes 2 food/grain
    assert s.players[0].card_state.get(CARD_ID, 0) == 0   # no point banked


# ---------------------------------------------------------------------------
# Stranding guard: NOT offered when firing would strand the mandatory bake.
# ---------------------------------------------------------------------------

def test_not_offered_when_it_would_strand_the_bake():
    # Exactly 1 grain: firing (spends 1) would leave 0 grain -> the mandatory bake
    # would be stranded, so the trigger must NOT be offered. A CommitBake is.
    s = _bake_setup(owner=0, grain=1)
    s = _bake_to_before_phase(s)
    assert s.players[0].resources.grain == 1
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert CommitBake(grain=1) in la   # the mandatory bake is still legal


def test_not_offered_when_unowned():
    s = _bake_setup(owner=None, grain=2)
    s = _bake_to_before_phase(s)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_once_per_bake_action():
    # After firing once, the trigger is stamped in triggers_resolved -> not offered
    # again within the same Bake Bread action (even with grain still available).
    s = _bake_setup(owner=0, grain=3)   # exchange 1 (2 left), still >=2 grain
    s = _bake_to_before_phase(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[0].resources.grain == 2     # 3 - 1 exchanged
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert s.players[0].card_state.get(CARD_ID, 0) == 1   # only banked once


def test_re_eligible_on_a_new_bake_action():
    # "Each time you take a Bake Bread action" — a fresh PendingBakeBread has an
    # empty triggers_resolved, so the card re-becomes eligible on the next action.
    s = _bake_setup(owner=0, grain=4)
    s = _bake_to_before_phase(s)
    s = step(s, FireTrigger(card_id=CARD_ID))   # fire on action #1 (spends 1)
    assert s.players[0].resources.grain == 3
    s = step(s, CommitBake(grain=1))             # bake normally
    s = step(s, Stop())                          # pop bake host after-phase
    s = step(s, Stop())                          # end the Grain Utilization turn
    assert s.pending_stack == ()
    assert s.players[0].card_state.get(CARD_ID, 0) == 1
    assert s.players[0].resources.grain == 2     # 4 - 1 exchanged - 1 baked

    # Force a second independent Bake Bread action via a fresh bake frame.
    from agricola.pending import PendingBakeBread, push
    s = with_current_player(s, 0)
    s = push(s, PendingBakeBread(player_idx=0, initiated_by_id="space:grain_utilization"))
    assert s.pending_stack[-1].phase == "before"
    assert s.players[0].resources.grain == 2     # >=2 -> eligible again
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))     # fire on action #2
    assert s.players[0].card_state.get(CARD_ID, 0) == 2   # banked twice total
