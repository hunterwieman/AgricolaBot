"""Lifecycle tests for the action-space host refactor (SPACE_HOST_REFACTOR.md).

B1 introduces the **Proceed-host** action-space parents: the and/or spaces (Grain
Utilization, Cultivation, Farm Expansion) and the and-then spaces (House
Redevelopment, Farm Redevelopment). Each has a before-phase (its sub-actions +
``Proceed`` once the gate is met) and an after-phase (after-triggers + ``Stop``);
``Proceed`` flips the host to its after-phase, ``Stop`` pops it.

B2 introduces the **Delegating** hosts: the generic ``PendingSubActionSpace``
(Farmland, Fencing, the Major Improvement space, Lessons) and
``PendingMajorMinorImprovement`` (the composite major/minor action). A Delegating
host has NO ``Proceed`` — when its single mandatory child sub-action pops, the
engine AUTO-ADVANCES the host to its after-phase (a silent step), whose ``Stop``
pops it. The Major Improvement space is the three-layer nesting:
``PendingSubActionSpace`` → ``PendingMajorMinorImprovement`` → ``PendingBuildMajor``.

Covered here:
  - an and/or ``Proceed`` walk, both options and one option (Grain Utilization,
    Cultivation);
  - an and-then walk (House Redevelopment, both steps and mandatory-only);
  - the firing migration's ordering: ``Stop`` is now a pure pop (no after-auto at
    Stop) and the Family before-phase ends in ``Proceed`` not ``Stop``;
  - the Major Improvement three-layer auto-advance nesting, and the same
    ``PendingMajorMinorImprovement`` reused under House Redevelopment.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitBuildMajor,
    CommitPlow,
    CommitRenovate,
    CommitSow,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingBuildMajor,
    PendingCultivation,
    PendingFarmExpansion,
    PendingGrainUtilization,
    PendingHouseRedevelopment,
    PendingMajorMinorImprovement,
    PendingSubActionSpace,
)
from agricola.resources import Resources
from agricola.setup import setup

from tests.factories import (
    with_current_player,
    with_fields,
    with_majors,
    with_resources,
    with_space,
)


def _commit_plow(state):
    plow = next(a for a in legal_actions(state) if isinstance(a, CommitPlow))
    return step(state, plow)


# ---------------------------------------------------------------------------
# and/or Proceed walk — Grain Utilization (sow + bake), BOTH options
# ---------------------------------------------------------------------------

def test_grain_util_both_options_proceed_walk():
    """sow then bake then Proceed (after) then Stop. The before-phase ends with
    Proceed, never Stop; the after-phase is a singleton [Stop]."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, grain=2)
    # Fireplace via with_majors so a bake is legal AND a field to sow.
    from tests.factories import with_majors
    state = with_majors(state, owner_by_idx={0: 0})
    state = with_fields(state, 0, [(0, 0)])

    state = step(state, PlaceWorker(space="grain_utilization"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingGrainUtilization) and top.phase == "before"

    # Sow.
    state = step(state, ChooseSubAction(name="sow"))
    state = step(state, CommitSow(grain=1, veg=0))
    state = step(state, Stop())          # pop PendingSow's after-phase
    # Back at the parent before-phase: sow done, so Proceed is now offered.
    la = legal_actions(state)
    assert Proceed() in la
    assert Stop() not in la              # never Stop at the before-phase

    # Bake.
    assert ChooseSubAction(name="bake_bread") in la
    state = step(state, ChooseSubAction(name="bake_bread"))
    from agricola.actions import CommitBake
    state = step(state, CommitBake(grain=1))
    state = step(state, Stop())          # pop PendingBakeBread's after-phase

    # Both sub-actions done; only Proceed left in the before-phase.
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())       # flip parent to after-phase

    top = state.pending_stack[-1]
    assert isinstance(top, PendingGrainUtilization) and top.phase == "after"
    assert legal_actions(state) == [Stop()]   # after-phase singleton
    state = step(state, Stop())          # pop parent; turn ends
    assert not state.pending_stack


# ---------------------------------------------------------------------------
# and/or Proceed walk — Cultivation (plow only), ONE option
# ---------------------------------------------------------------------------

def test_cultivation_one_option_proceed_walk():
    """plow then Proceed then Stop — the one-option and/or walk."""
    state = setup(seed=0)
    state = with_current_player(state, 0)

    state = step(state, PlaceWorker(space="cultivation"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingCultivation) and top.phase == "before"

    state = step(state, ChooseSubAction(name="plow"))
    state = _commit_plow(state)
    state = step(state, Stop())          # pop PendingPlow's after-phase

    # plow done -> Proceed offered (sow still optional, but we decline it).
    la = legal_actions(state)
    assert Proceed() in la
    state = step(state, Proceed())       # flip to after-phase
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack


# ---------------------------------------------------------------------------
# and/or — Farm Expansion: Proceed gate requires a sub-action first
# ---------------------------------------------------------------------------

def test_farm_expansion_proceed_gated_on_a_sub_action():
    """At Farm Expansion's before-phase, Proceed is NOT offered until at least one
    sub-action (rooms/stables) has been entered (the 'must do at least one' gate)."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Enough wood for a stable (2 wood). Reveal so it's a usable space.
    state = with_resources(state, 0, wood=2)

    state = step(state, PlaceWorker(space="farm_expansion"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingFarmExpansion) and top.phase == "before"
    # Nothing chosen yet -> Proceed is NOT legal (gate unmet).
    la = legal_actions(state)
    assert Proceed() not in la
    assert Stop() not in la
    assert ChooseSubAction(name="build_stables") in la


# ---------------------------------------------------------------------------
# and-then walk — House Redevelopment, both steps and mandatory-only
# ---------------------------------------------------------------------------

def _house_redev_setup():
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # A wood house with 2 rooms; clay + reed to renovate to clay.
    state = with_resources(state, 0, clay=5, reed=2, wood=0)
    return state


def test_house_redev_mandatory_only_proceed_walk():
    """renovate (mandatory) then Proceed — declining the optional improvement."""
    state = _house_redev_setup()
    state = step(state, PlaceWorker(space="house_redevelopment"))
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHouseRedevelopment) and top.phase == "before"
    # Renovate is mandatory-first: no Proceed until it has run.
    la = legal_actions(state)
    assert ChooseSubAction(name="renovate") in la
    assert Proceed() not in la

    state = step(state, ChooseSubAction(name="renovate"))
    state = step(state, CommitRenovate())
    state = step(state, Stop())          # pop PendingRenovate's after-phase

    # Renovate done -> Proceed offered (improvement optional, declined here).
    la = legal_actions(state)
    assert Proceed() in la
    state = step(state, Proceed())       # flip to after-phase
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    assert state.players[0].house_material == HouseMaterial.CLAY


# ---------------------------------------------------------------------------
# B2 — the Major Improvement three-layer Delegating auto-advance nesting
# ---------------------------------------------------------------------------

def _mi_setup(**res):
    state = setup(seed=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, **res)
    state = with_space(state, "major_improvement", revealed=True)
    return state


def test_major_space_three_layer_auto_advance():
    """The Major Improvement space wraps three Delegating layers:
      PendingSubActionSpace -> PendingMajorMinorImprovement -> PendingBuildMajor.
    Building a (non-oven) major auto-advances both upper hosts; the trace needs
    three trailing Stops (one per host's after-phase), with the auto-advance flips
    happening silently between them."""
    state = _mi_setup(clay=2)   # Fireplace (idx 0) costs 2 clay

    state = step(state, PlaceWorker(space="major_improvement"))
    # Layer 1: the space host, before-phase, single mandatory ChooseSubAction.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace)
    assert top.space_id == "major_improvement"
    assert top.phase == "before" and not top.subaction_complete
    assert legal_actions(state) == [ChooseSubAction(name="improvement")]

    state = step(state, ChooseSubAction(name="improvement"))
    # Layer 2: the composite host, before-phase, build_major offered.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement)
    assert top.phase == "before" and not top.subaction_complete
    assert ChooseSubAction(name="build_major") in legal_actions(state)

    state = step(state, ChooseSubAction(name="build_major"))
    # Layer 3: the build-major primitive.
    assert isinstance(state.pending_stack[-1], PendingBuildMajor)
    state = step(state, CommitBuildMajor(major_idx=0, return_fireplace_idx=None))
    # PendingBuildMajor flipped to its after-phase (sub-action pass).
    assert state.pending_stack[-1].phase == "after"
    assert state.board.major_improvement_owners[0] == 0

    # Stop 1: pop PendingBuildMajor. The auto-advance then flips the composite
    # host (layer 2) to its after-phase BEFORE the next decision is offered.
    state = step(state, Stop())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement) and top.phase == "after"
    assert legal_actions(state) == [Stop()]

    # Stop 2: pop the composite host. The auto-advance flips the space host
    # (layer 1) to its after-phase.
    state = step(state, Stop())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace) and top.phase == "after"
    assert legal_actions(state) == [Stop()]

    # Stop 3: pop the space host; turn ends.
    state = step(state, Stop())
    assert not state.pending_stack


def test_major_minor_host_reused_under_house_redevelopment():
    """House Redevelopment's optional improvement step pushes the SAME
    PendingMajorMinorImprovement (NOT a PendingSubActionSpace — House Redev is its
    own Proceed-host space). After the major builds, the composite host
    auto-advances to its after-phase and its Stop pops it; control returns to House
    Redev's before-phase where Proceed is offered."""
    state = setup(seed=0)
    state = with_current_player(state, 0)
    # Wood house, 2 rooms: clay+reed to renovate to clay, then clay for Fireplace.
    state = with_resources(state, 0, clay=5, reed=2)
    state = with_space(state, "house_redevelopment", revealed=True)

    state = step(state, PlaceWorker(space="house_redevelopment"))
    assert isinstance(state.pending_stack[-1], PendingHouseRedevelopment)
    state = step(state, ChooseSubAction(name="renovate"))
    state = step(state, CommitRenovate())
    state = step(state, Stop())          # pop PendingRenovate's after-phase

    # House Redev before-phase: the optional improvement + Proceed.
    la = legal_actions(state)
    assert ChooseSubAction(name="improvement") in la
    assert Proceed() in la

    state = step(state, ChooseSubAction(name="improvement"))
    # The SHARED composite host — pushed directly by House Redev, NOT wrapped in a
    # PendingSubActionSpace (so no Major-Improvement-space event fires here).
    assert isinstance(state.pending_stack[-1], PendingMajorMinorImprovement)
    assert not any(isinstance(f, PendingSubActionSpace) for f in state.pending_stack)

    state = step(state, ChooseSubAction(name="build_major"))
    state = step(state, CommitBuildMajor(major_idx=0, return_fireplace_idx=None))
    state = step(state, Stop())          # pop PendingBuildMajor; auto-advance flips composite host
    top = state.pending_stack[-1]
    assert isinstance(top, PendingMajorMinorImprovement) and top.phase == "after"
    state = step(state, Stop())          # pop the composite host -> back at House Redev before-phase

    # Back at House Redev: improvement done, Proceed remains.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingHouseRedevelopment) and top.phase == "before"
    assert Proceed() in legal_actions(state)
    state = step(state, Proceed())       # flip House Redev to after
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    assert state.board.major_improvement_owners[0] == 0
