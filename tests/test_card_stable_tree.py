"""Tests for Stable Tree (minor improvement, A74; Artifex): "Each time you build 1
or more stables on your turn, place 1 wood on each of the next 3 round spaces. At
the start of these rounds, you get the wood." Clarification: stables built off-turn
(Stable Planner A089 / Groom B089) do NOT trigger it. Cost 1 Wood; no prereq; no VP.

An `after_build_stables` automatic effect that schedules 1 wood onto the next 3
round spaces, gated to the owner's OWN work-phase build. Coverage: registration; the
schedule via the REAL Farm Expansion build-stables flow; that a multi-stable action
still schedules ONCE (per action, not per stable); the scheduled wood is collected
at round start; the OFF-TURN gate (a PREPARATION-phase build does NOT schedule);
owner-only + hand-inert.
"""
import agricola.cards.stable_tree  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildStable,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.legality import legal_actions
from agricola.pending import PendingBuildStables
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import (
    with_current_player,
    with_pending_stack,
    with_phase,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions

CARD_ID = "stable_tree"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own(state, idx):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _wood_sched(state, idx=0):
    return [r.wood for r in state.players[idx].future_resources]


def _next_stable(state):
    return next(a for a in legal_actions(state) if isinstance(a, CommitBuildStable))


def _expansion_setup(*, idx=0, own=True, **resources):
    cs = _card_state()
    cs = with_current_player(cs, idx)
    cs = with_resources(cs, idx, **resources)
    cs = with_space(cs, "farm_expansion", revealed=True)
    if own:
        cs = _own(cs, idx)
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    entry = next(e for e in AUTO_EFFECTS.get("after_build_stables", [])
                 if e.card_id == CARD_ID)
    assert not entry.any_player   # "each time YOU build" -> owner only


# ---------------------------------------------------------------------------
# The schedule via the real Farm Expansion build-stables flow (round 1)
# ---------------------------------------------------------------------------

def test_building_one_stable_schedules_wood_on_next_3_rounds():
    cs = _expansion_setup(wood=2)   # 1 wood pays the stable; the card costs are pre-owned
    before = _wood_sched(cs)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable,
        Proceed(),   # flip PendingBuildStables -> after -> the auto schedules
        Stop(),
        Proceed(),
        Stop(),
    ])
    w = _wood_sched(cs)
    R = 1
    # Rounds 2, 3, 4 (slots 1, 2, 3) each +1 wood; round 5 (slot 4) NOT.
    assert w[1] == before[1] + 1
    assert w[2] == before[2] + 1
    assert w[3] == before[3] + 1
    assert w[4] == before[4]


def test_multi_stable_action_schedules_once():
    """Two stables built in ONE action still schedules 1 wood x3 (per ACTION, not
    per stable)."""
    cs = _expansion_setup(wood=4)
    before = _wood_sched(cs)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable, _next_stable,
        Proceed(), Stop(), Proceed(), Stop(),
    ])
    w = _wood_sched(cs)
    assert w[1] == before[1] + 1   # not +2
    assert w[2] == before[2] + 1
    assert w[3] == before[3] + 1


def test_wood_collected_at_round_start():
    from agricola.engine import _complete_preparation
    cs = _expansion_setup(wood=2)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable, Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _wood_sched(cs)[1] == 1
    wood_before = cs.players[0].resources.wood
    cs = fast_replace(cs, round_number=1, phase=Phase.PREPARATION)
    cs = _complete_preparation(cs)
    assert cs.round_number == 2
    assert cs.players[0].resources.wood == wood_before + 1
    assert _wood_sched(cs)[1] == 0


# ---------------------------------------------------------------------------
# THE OFF-TURN GATE — a PREPARATION-phase build must NOT schedule
# ---------------------------------------------------------------------------

def test_off_turn_preparation_build_does_not_schedule():
    """A stable built off-turn (as Stable Planner / Groom do: a PendingBuildStables
    pushed during the round_space_collection window, phase == PREPARATION) must NOT
    trigger Stable Tree — the clarification's exclusion."""
    cs = _card_state()
    cs = _own(cs, 0)
    cs = with_current_player(cs, 0)
    cs = with_resources(cs, 0)          # free grant
    cs = with_phase(cs, Phase.PREPARATION)
    cs = with_pending_stack(cs, [PendingBuildStables(
        player_idx=0, initiated_by_id="card:stable_planner",
        cost=Resources(), max_builds=1)])
    before = _wood_sched(cs)
    cs = run_actions(cs, [_next_stable, Proceed()])   # build + flip
    # No schedule: the build was off-turn (PREPARATION), not a work-phase turn.
    assert _wood_sched(cs) == before


def test_on_turn_card_granted_build_does_schedule():
    """Contrast: the SAME free PendingBuildStables during the WORK phase (an on-turn
    card grant) DOES schedule — the gate is the phase, not the build source."""
    cs = _card_state()
    cs = _own(cs, 0)
    cs = with_current_player(cs, 0)
    cs = with_resources(cs, 0)
    cs = with_phase(cs, Phase.WORK)
    cs = with_pending_stack(cs, [PendingBuildStables(
        player_idx=0, initiated_by_id="card:test",
        cost=Resources(), max_builds=1)])
    before = _wood_sched(cs)
    cs = run_actions(cs, [_next_stable, Proceed()])
    assert _wood_sched(cs)[1] == before[1] + 1


# ---------------------------------------------------------------------------
# Ownership boundaries
# ---------------------------------------------------------------------------

def test_opponent_build_pays_owner_nothing():
    cs = _card_state()
    cs = _own(cs, 0)                    # player 0 owns
    cs = with_current_player(cs, 1)     # player 1 builds
    cs = with_resources(cs, 1, wood=2)
    cs = with_space(cs, "farm_expansion", revealed=True)
    before0 = _wood_sched(cs, 0)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable, Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _wood_sched(cs, 0) == before0


def test_hand_only_is_inert():
    cs = _expansion_setup(wood=2, own=False)
    p0 = fast_replace(cs.players[0], hand_minors=cs.players[0].hand_minors | {CARD_ID})
    cs = fast_replace(cs, players=(p0, cs.players[1]))
    before = _wood_sched(cs)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable, Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _wood_sched(cs) == before
