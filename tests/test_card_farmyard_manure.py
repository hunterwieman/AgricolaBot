"""Tests for Farmyard Manure (minor improvement, A43; Artifex): "Each time you build
1 or more stables in one turn, you place 1 food on each of the next 3 round spaces.
At the start of these rounds, you get the food." Clarification: off-turn stable
builds (Stable Planner A089 / Groom B089) do NOT trigger it. Cost: free; prereq 1
Animal; no VP.

The Food-Provider twin of Stable Tree A74 (schedules FOOD, not wood), plus a
"1 Animal" have-check prerequisite. Coverage: registration; the prereq (playable
only with >= 1 animal held); the schedule via the REAL Farm Expansion build-stables
flow; the OFF-TURN gate (a PREPARATION-phase build does NOT schedule); owner-only.
"""
import agricola.cards.farmyard_manure  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildStable,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import Phase
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingBuildStables, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import (
    with_animals,
    with_current_player,
    with_pending_stack,
    with_phase,
    with_resources,
    with_space,
)
from tests.test_utils import run_actions

CARD_ID = "farmyard_manure"

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


def _food_sched(state, idx=0):
    return [r.food for r in state.players[idx].future_resources]


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
    assert spec.cost == Cost()          # free
    assert spec.vps == 0
    assert spec.prereq is not None      # "1 Animal"
    entry = next(e for e in AUTO_EFFECTS.get("after_build_stables", [])
                 if e.card_id == CARD_ID)
    assert not entry.any_player


# ---------------------------------------------------------------------------
# Prerequisite: 1 Animal (a have-check, any kind)
# ---------------------------------------------------------------------------

def test_prereq_requires_an_animal():
    spec = MINORS[CARD_ID]
    cs = _card_state()
    cp = cs.current_player
    # No animals -> not met.
    assert not prereq_met(spec, cs, cp)
    # Any single animal -> met.
    for kind in ("sheep", "boar", "cattle"):
        s = with_animals(cs, cp, **{kind: 1})
        assert prereq_met(spec, s, cp)


def test_not_playable_without_animal():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}), animals=Animals())
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    assert CARD_ID not in playable_minors(cs, cp)
    # With an animal, it becomes playable.
    cs2 = with_animals(cs, cp, sheep=1)
    assert CARD_ID in playable_minors(cs2, cp)


# ---------------------------------------------------------------------------
# The schedule via the real Farm Expansion build-stables flow
# ---------------------------------------------------------------------------

def test_building_stable_schedules_food_on_next_3_rounds():
    cs = _expansion_setup(wood=2)
    before = _food_sched(cs)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable, Proceed(), Stop(), Proceed(), Stop(),
    ])
    f = _food_sched(cs)
    assert f[1] == before[1] + 1
    assert f[2] == before[2] + 1
    assert f[3] == before[3] + 1
    assert f[4] == before[4]


def test_food_collected_at_round_start():
    from agricola.engine import _complete_preparation
    cs = _expansion_setup(wood=2)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable, Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _food_sched(cs)[1] == 1
    food_before = cs.players[0].resources.food
    cs = fast_replace(cs, round_number=1, phase=Phase.PREPARATION)
    cs = _complete_preparation(cs)
    assert cs.round_number == 2
    assert cs.players[0].resources.food == food_before + 1


# ---------------------------------------------------------------------------
# THE OFF-TURN GATE
# ---------------------------------------------------------------------------

def test_off_turn_preparation_build_does_not_schedule():
    cs = _card_state()
    cs = _own(cs, 0)
    cs = with_current_player(cs, 0)
    cs = with_resources(cs, 0)
    cs = with_phase(cs, Phase.PREPARATION)
    cs = with_pending_stack(cs, [PendingBuildStables(
        player_idx=0, initiated_by_id="card:groom",
        cost=Resources(), max_builds=1)])
    before = _food_sched(cs)
    cs = run_actions(cs, [_next_stable, Proceed()])
    assert _food_sched(cs) == before


# ---------------------------------------------------------------------------
# Ownership boundary
# ---------------------------------------------------------------------------

def test_opponent_build_pays_owner_nothing():
    cs = _card_state()
    cs = _own(cs, 0)
    cs = with_current_player(cs, 1)
    cs = with_resources(cs, 1, wood=2)
    cs = with_space(cs, "farm_expansion", revealed=True)
    before0 = _food_sched(cs, 0)
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_stables"),
        _next_stable, Proceed(), Stop(), Proceed(), Stop(),
    ])
    assert _food_sched(cs, 0) == before0
