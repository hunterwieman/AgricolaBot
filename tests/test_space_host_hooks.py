"""Hook-firing coverage for every action-space host (SPACE_HOST_REFACTOR.md §2/§4/§11).

The space-host refactor gave every action-space parent a before/after host
lifecycle: a `before_action_space` automatic effect must fire when the host frame
is pushed, and an `after_action_space` automatic effect must fire at the host's
work-complete boundary (Proceed for atomic/Proceed-hosts, the commit for the
markets, the auto-advance for the Delegating hosts). The composite
`major_minor_improvement` frame fires its own `before_/after_major_minor_improvement`
event instead.

Before this file existed the test suite had NO test exercising a
before_/after_action_space card hook on the space hosts, so design-completeness
gaps (the five Proceed-hosts not firing `before_action_space` at push) slipped
through green gates. These tests register a synthetic automatic effect on the host
event with the test-scoped register + try/finally cleanup pattern from
`tests/test_cards_meeting_place.py::test_card_hook_fires_with_no_playable_minor`,
then assert it fires at the right point for every host — closing that gap.

Mechanism per host: the synthetic auto-effect bumps the owner's `stone` by 1 each
time it fires while the named host is the top frame. The `before` test asserts the
bump landed by the time the host's first decision is enumerated (i.e. at push); the
`after` test asserts the bump landed when the frame is in its after-phase (i.e. at
the work-complete boundary, before the trailing Stop).
"""
import contextlib

import pytest

from agricola.actions import (
    ChooseSubAction,
    CommitAccommodate,
    CommitBuildMajor,
    CommitFamilyGrowth,
    CommitPlayMinor,
    CommitPlayOccupation,
    CommitPlow,
    CommitRenovate,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.constants import CellType, GameMode, HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import (
    PendingActionSpace,
    PendingBasicWishForChildren,
    PendingCattleMarket,
    PendingCultivation,
    PendingFarmExpansion,
    PendingFarmRedevelopment,
    PendingGrainUtilization,
    PendingHouseRedevelopment,
    PendingMajorMinorImprovement,
    PendingMeetingPlace,
    PendingSubActionSpace,
)
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space

# A generous card pool so the owner has hand minors / occupations to play where a
# host needs one. Card ids o*/m* are unregistered, so they never get OFFERED — the
# hosts that need a playable minor/occupation get the registered ones explicitly.
_POOL = CardPool(
    occupations=("consultant",) + tuple(f"o{i}" for i in range(20)),
    minors=("market_stall",) + tuple(f"m{i}" for i in range(20)),
)

# The synthetic hook card id. It is granted as a played minor improvement so
# `_owns` (which reads occupations | minor_improvements) sees it.
_HOOK_CARD = "_test_space_host_hook"


@contextlib.contextmanager
def _registered_hook(event: str):
    """Register a synthetic automatic effect on `event` that bumps the owner's
    stone by 1 each time it fires, then clean it up. Mirrors the test-scoped
    register + try/finally pattern in test_cards_meeting_place.py."""
    from agricola.cards.triggers import AUTO_EFFECTS, register_auto

    def _elig(state, idx):
        return True

    def _apply(state, idx):
        p = state.players[idx]
        return fast_replace(
            state,
            players=tuple(
                fast_replace(q, resources=q.resources + Resources(stone=1))
                if i == idx else q
                for i, q in enumerate(state.players)
            ),
        )

    register_auto(event, _HOOK_CARD, _elig, _apply)
    try:
        yield
    finally:
        AUTO_EFFECTS[event] = [
            e for e in AUTO_EFFECTS.get(event, []) if e.card_id != _HOOK_CARD
        ]


def _base_card_state(seed=5):
    """A fresh card-mode game; the current player owns the synthetic hook card."""
    cs, env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {_HOOK_CARD})
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, env, cp


def _reveal(cs, space_id):
    sp = fast_replace(get_space(cs.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(cs, board=with_space(cs.board, space_id, sp))


# ---------------------------------------------------------------------------
# Per-host state builders. Each returns (state, cp) with the host's space legal
# and the current player owning the synthetic hook card. The list of host names
# maps 1:1 onto the audit's host roster.
# ---------------------------------------------------------------------------

def _setup_grain_utilization(cs, cp):
    # Sow-able: a 3rd plowed empty field + grain in supply.
    cs = _reveal(cs, "grain_utilization")
    cs = fast_replace(cs, board=with_space(
        cs.board, "grain_utilization", get_space(cs.board, "grain_utilization")))
    from tests.factories import with_fields, add_resources
    cs = with_fields(cs, cp, [(0, 2)])
    cs = add_resources(cs, cp, grain=1)
    return cs


def _setup_cultivation(cs, cp):
    cs = _reveal(cs, "cultivation")
    from tests.factories import with_fields, add_resources
    cs = with_fields(cs, cp, [(0, 2)])     # gives an empty field (sow) + a plow target nearby
    cs = add_resources(cs, cp, grain=1)
    return cs


def _setup_farm_expansion(cs, cp):
    cs = _reveal(cs, "farm_expansion")
    from tests.factories import add_resources
    cs = add_resources(cs, cp, wood=2)     # can build a stable (2 wood)
    return cs


def _setup_house_redevelopment(cs, cp):
    cs = _reveal(cs, "house_redevelopment")
    from tests.factories import add_resources
    # Wood house, 2 starting rooms → renovate costs 2 clay + 1 reed.
    cs = add_resources(cs, cp, clay=2, reed=1)
    return cs


def _setup_farm_redevelopment(cs, cp):
    cs = _reveal(cs, "farm_redevelopment")
    from tests.factories import add_resources
    cs = add_resources(cs, cp, clay=2, reed=1)
    return cs


def _setup_farmland(cs, cp):
    cs = _reveal(cs, "farmland")
    return cs   # an empty farm always has a legal first plow


def _setup_fencing(cs, cp):
    cs = _reveal(cs, "fencing")
    from tests.factories import add_resources
    cs = add_resources(cs, cp, wood=4)
    return cs


def _setup_major_improvement(cs, cp):
    cs = _reveal(cs, "major_improvement")
    from tests.factories import add_resources
    cs = add_resources(cs, cp, clay=2)     # affords a Fireplace (idx 0)
    return cs


def _setup_lessons(cs, cp):
    cs = _reveal(cs, "lessons")
    p = cs.players[cp]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {"consultant"})
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs


def _setup_meeting_place(cs, cp):
    cs = _reveal(cs, "meeting_place")
    return cs   # card meeting place always wraps


def _setup_basic_wish(cs, cp):
    cs = _reveal(cs, "basic_wish_for_children")
    from tests.factories import with_grid
    # Need people_total < num_rooms: add a 3rd room.
    cs = with_grid(cs, cp, {(0, 4): Cell(cell_type=CellType.ROOM)})
    return cs


def _setup_sheep_market(cs, cp):
    cs = _reveal(cs, "sheep_market")
    cs = fast_replace(cs, board=with_space(
        cs.board, "sheep_market",
        fast_replace(get_space(cs.board, "sheep_market"), accumulated_amount=2)))
    return cs


# Markets / atomic-host need PlaceWorker too. The map: space_id -> setup fn.
_SETUP = {
    "grain_utilization": _setup_grain_utilization,
    "cultivation": _setup_cultivation,
    "farm_expansion": _setup_farm_expansion,
    "house_redevelopment": _setup_house_redevelopment,
    "farm_redevelopment": _setup_farm_redevelopment,
    "farmland": _setup_farmland,
    "fencing": _setup_fencing,
    "major_improvement": _setup_major_improvement,
    "lessons": _setup_lessons,
    "meeting_place": _setup_meeting_place,
    "basic_wish_for_children": _setup_basic_wish,
    "sheep_market": _setup_sheep_market,
}

# Hosts that fire the coarse before_/after_action_space event.
_ACTION_SPACE_HOSTS = sorted(_SETUP.keys())


def _place(cs, space_id):
    return step(cs, PlaceWorker(space=space_id))


# ---------------------------------------------------------------------------
# before_action_space fires at push (the bug that slipped through).
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space_id", _ACTION_SPACE_HOSTS)
def test_before_action_space_fires_at_push(space_id):
    """For every action-space host, a before_action_space automatic effect must
    fire at the moment the host frame is pushed (i.e. it has fired by the time the
    host's first decision is enumerable). FAILS pre-fix for the five Proceed-hosts
    (grain_utilization / cultivation / farm_expansion / house_redevelopment /
    farm_redevelopment), which did not call apply_auto_effects at push."""
    with _registered_hook("before_action_space"):
        cs, _env, cp = _base_card_state()
        cs = _SETUP[space_id](cs, cp)
        pre = cs.players[cp].resources.stone
        cs = _place(cs, space_id)
        # The host frame is on the stack (these spaces all push one) and the
        # before-auto must already have fired exactly once.
        assert cs.pending_stack, f"{space_id} pushed no host frame"
        assert cs.players[cp].resources.stone == pre + 1, (
            f"{space_id}: before_action_space did not fire at push"
        )


# ---------------------------------------------------------------------------
# after_action_space fires at the work-complete boundary.
# ---------------------------------------------------------------------------

def _drive_to_after(cs, cp, space_id):
    """Place the worker and drive the host to its after-phase boundary, returning
    the state with the host frame on top in phase=='after' (before the trailing
    Stop). Per-host because the path to the work-complete boundary differs."""
    cs = _place(cs, space_id)

    if space_id == "grain_utilization":
        cs = step(cs, ChooseSubAction(name="sow"))
        # PendingSow before-phase: pick the smallest sow, then its after-Stop.
        from agricola.actions import CommitSow
        cs = step(cs, CommitSow(grain=1, veg=0))
        cs = step(cs, Stop())               # pop PendingSow after-phase
        cs = step(cs, Proceed())            # flip parent to after
        return cs
    if space_id == "cultivation":
        cs = step(cs, ChooseSubAction(name="plow"))
        # first legal plow
        plow = next(a for a in legal_actions(cs) if isinstance(a, CommitPlow))
        cs = step(cs, plow)
        cs = step(cs, Stop())               # pop PendingPlow after-phase
        cs = step(cs, Proceed())
        return cs
    if space_id == "farm_expansion":
        cs = step(cs, ChooseSubAction(name="build_stables"))
        from agricola.actions import CommitBuildStable
        bs = next(a for a in legal_actions(cs) if isinstance(a, CommitBuildStable))
        cs = step(cs, bs)
        cs = step(cs, Stop())               # finish the multi-shot build_stables
        cs = step(cs, Proceed())
        return cs
    if space_id in ("house_redevelopment", "farm_redevelopment"):
        cs = step(cs, ChooseSubAction(name="renovate"))
        cs = step(cs, CommitRenovate())
        cs = step(cs, Stop())               # pop PendingRenovate after-phase
        cs = step(cs, Proceed())            # flip parent to after
        return cs
    if space_id == "farmland":
        # Delegating host: plow then the child pops -> auto-advance to after.
        cs = step(cs, ChooseSubAction(name="plow"))
        plow = next(a for a in legal_actions(cs) if isinstance(a, CommitPlow))
        cs = step(cs, plow)
        cs = step(cs, Stop())               # pop PendingPlow; auto-advance flips parent
        return cs
    if space_id == "fencing":
        cs = step(cs, ChooseSubAction(name="build_fences"))
        from agricola.actions import CommitBuildPasture
        bp = next(a for a in legal_actions(cs) if isinstance(a, CommitBuildPasture))
        cs = step(cs, bp)
        cs = step(cs, Stop())               # finish build_fences; auto-advance flips parent
        return cs
    if space_id == "major_improvement":
        # Delegating host -> improvement -> PendingMajorMinorImprovement (composite);
        # choose build_major -> PendingBuildMajor; build a non-oven major, Stop pops
        # it, the composite auto-advances + Stop pops it, then the
        # PendingSubActionSpace auto-advances to its after-phase.
        cs = step(cs, ChooseSubAction(name="improvement"))
        cs = step(cs, ChooseSubAction(name="build_major"))
        cs = step(cs, CommitBuildMajor(major_idx=0, return_fireplace_idx=None))
        cs = step(cs, Stop())               # pop PendingBuildMajor after-phase
        cs = step(cs, Stop())               # pop the composite after-phase
        return cs
    if space_id == "lessons":
        cs = step(cs, ChooseSubAction(name="play_occupation"))
        cs = step(cs, CommitPlayOccupation(card_id="consultant"))
        cs = step(cs, Stop())               # pop PendingPlayOccupation; auto-advance flips parent
        return cs
    if space_id == "meeting_place":
        cs = step(cs, Proceed())            # decline minor -> flip to after
        return cs
    if space_id == "basic_wish_for_children":
        cs = step(cs, ChooseSubAction(name="family_growth"))
        cs = step(cs, CommitFamilyGrowth())
        cs = step(cs, Stop())               # pop PendingFamilyGrowth after-phase
        cs = step(cs, Proceed())            # flip parent to after
        return cs
    if space_id == "sheep_market":
        acc = next(a for a in legal_actions(cs) if isinstance(a, CommitAccommodate))
        cs = step(cs, acc)                  # commit pivots market to after
        return cs
    raise AssertionError(f"no after-drive for {space_id}")


@pytest.mark.parametrize("space_id", _ACTION_SPACE_HOSTS)
def test_after_action_space_fires_at_boundary(space_id):
    """For every action-space host, an after_action_space automatic effect must
    fire at the work-complete boundary (Proceed / commit / auto-advance), i.e. the
    host frame is in its after-phase before the trailing Stop and the bump landed."""
    with _registered_hook("after_action_space"):
        cs, _env, cp = _base_card_state()
        cs = _SETUP[space_id](cs, cp)
        pre = cs.players[cp].resources.stone
        cs = _drive_to_after(cs, cp, space_id)
        top = cs.pending_stack[-1]
        assert getattr(top, "phase", None) == "after", (
            f"{space_id}: host not in after-phase at boundary (top={top!r})"
        )
        assert cs.players[cp].resources.stone == pre + 1, (
            f"{space_id}: after_action_space did not fire at the work-complete boundary"
        )
        # The boundary surfaces only [Stop] (no after-trigger registered here).
        assert legal_actions(cs) == [Stop()]


# ---------------------------------------------------------------------------
# The composite host fires major_minor_improvement (NOT action_space).
# It is OUT of ACTION_SPACE_PENDING_IDS by design (§6) — under House Redev that
# keeps it from firing a second after_action_space on top of House Redev's own.
# ---------------------------------------------------------------------------

def test_major_minor_improvement_fires_its_own_after_event():
    """PendingMajorMinorImprovement fires after_major_minor_improvement at its
    Delegating auto-advance, NOT after_action_space."""
    with _registered_hook("after_major_minor_improvement"):
        cs, _env, cp = _base_card_state()
        cs = _setup_major_improvement(cs, cp)
        cs = _place(cs, "major_improvement")
        cs = step(cs, ChooseSubAction(name="improvement"))
        assert isinstance(cs.pending_stack[-1], PendingMajorMinorImprovement)
        pre = cs.players[cp].resources.stone
        cs = step(cs, ChooseSubAction(name="build_major"))
        cs = step(cs, CommitBuildMajor(major_idx=0, return_fireplace_idx=None))
        cs = step(cs, Stop())               # pop PendingBuildMajor; composite auto-advances
        # The composite frame auto-advanced to after, firing its own event.
        top = cs.pending_stack[-1]
        assert isinstance(top, PendingMajorMinorImprovement)
        assert top.phase == "after"
        assert cs.players[cp].resources.stone == pre + 1, (
            "after_major_minor_improvement did not fire at the composite boundary"
        )


def test_major_minor_improvement_before_event_fires_at_push():
    """before_major_minor_improvement fires when the composite frame is pushed (by
    the Delegating space host's `improvement` choose)."""
    with _registered_hook("before_major_minor_improvement"):
        cs, _env, cp = _base_card_state()
        cs = _setup_major_improvement(cs, cp)
        cs = _place(cs, "major_improvement")
        pre = cs.players[cp].resources.stone
        cs = step(cs, ChooseSubAction(name="improvement"))
        assert isinstance(cs.pending_stack[-1], PendingMajorMinorImprovement)
        assert cs.players[cp].resources.stone == pre + 1, (
            "before_major_minor_improvement did not fire when the composite was pushed"
        )


# ---------------------------------------------------------------------------
# Side Job is deliberately NOT a host (Stop-terminated, no phase, not in bucket).
# Verify it neither fires the action_space event nor carries a phase.
# ---------------------------------------------------------------------------

def test_side_job_is_not_a_host_behaviorally():
    """Side Job is deliberately Stop-terminated, not a before/after host: it has no
    `phase` field and its placement fires no before_action_space auto. (Note: the
    `side_job` PENDING_ID is currently still listed in ACTION_SPACE_PENDING_IDS, but
    that membership is INERT — PendingSideJob has no `phase`, so trigger_event /
    _enter_after_phase are never invoked on it, and the card board has no Side Job
    space at all. This test pins the behavior, not the stale set entry.)"""
    from agricola.pending import PendingSideJob

    assert "phase" not in PendingSideJob.__annotations__

    with _registered_hook("before_action_space"):
        from tests.factories import add_resources
        cs, env = setup_env(7)            # Family game
        assert cs.mode is GameMode.FAMILY
        cp = cs.current_player
        p = cs.players[cp]
        cs = fast_replace(cs, players=tuple(
            fast_replace(p, minor_improvements={_HOOK_CARD}) if i == cp else cs.players[i]
            for i in range(2)))
        cs = _reveal(cs, "side_job")
        cs = add_resources(cs, cp, wood=1)   # can build a stable at side job
        pre = cs.players[cp].resources.stone
        cs = _place(cs, "side_job")
        assert isinstance(cs.pending_stack[-1], PendingSideJob)
        assert cs.players[cp].resources.stone == pre, (
            "Side Job must not fire before_action_space (it is not a host)"
        )
