"""Tests for Interior Decorator (occupation, D111; Consul Dirigens; players 1+).

Card text: "Each time you renovate, place 1 food on each of the next 6 round
spaces. At the start of these rounds, you get the food."

A mandatory automatic on `before_renovate` that schedules 1 food onto rounds
R+1..R+6 via `schedule_resources` (slot r-1 holds round r; rounds past 14 are
silently dropped). Each test drives the real House Redevelopment / Farm
Redevelopment renovate flow, mirroring tests/test_card_roughcaster.py (the
renovate-hook drive) and tests/test_card_lumberjack.py (the schedule-slot and
round-start-collection assertions).
"""
import agricola.cards.interior_decorator  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import HouseMaterial, Phase
from agricola.engine import _complete_preparation, step
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_house, with_resources, with_space
from tests.test_utils import run_actions, sole_renovate

CARD_ID = "interior_decorator"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=0)
    # Drop both hands so plays come only from what a test grants.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_occ(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _food_schedule(state, idx):
    return [r.food for r in state.players[idx].future_resources]


def _renovate_setup(*, own_idx=0, **resources):
    """A card-mode state: wood house, house_redevelopment revealed, the card
    owned (played) by `own_idx` (None = nobody), and the given P0 resources."""
    cs = _card_state()
    cs = with_resources(cs, 0, **resources)
    cs = with_space(cs, "house_redevelopment", revealed=True)
    if own_idx is not None:
        cs = _own_occ(cs, own_idx)
    return cs


def _drive_renovate(state, space="house_redevelopment"):
    """Drive the given renovate space's flow to a turn-complete state (the
    roughcaster idiom: commit -> Stop pops PendingRenovate's after-phase ->
    Proceed flips the host -> Stop pops it)."""
    return run_actions(state, [
        PlaceWorker(space=space),
        ChooseSubAction(name="renovate"),
        sole_renovate,   # the unique legal CommitRenovate (applies the renovate)
        Stop(),          # pop PendingRenovate (after-phase)
        Proceed(),       # flip the host to its after-phase
        Stop(),          # pop the host -> turn complete
    ])


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    ids = {e.card_id for e in AUTO_EFFECTS.get("before_renovate", [])}
    assert CARD_ID in ids
    # Mandatory automatic -> not in the declinable TRIGGERS registry.
    declinable = {t.card_id for lst in TRIGGERS.values() for t in lst}
    assert CARD_ID not in declinable


def test_on_play_is_a_noop():
    cs = _card_state()
    assert OCCUPATIONS[CARD_ID].on_play(cs, 0) == cs


# ---------------------------------------------------------------------------
# The renovate hook — schedules 1 food on each of the next 6 round spaces
# ---------------------------------------------------------------------------

def test_renovate_schedules_next_six_rounds():
    # Round 1, wood->clay renovate (2 rooms: 2 clay + 1 reed) via House
    # Redevelopment -> 1 food on rounds 2..7 (slots 1..6), nothing else.
    cs = _renovate_setup(clay=2, reed=1)
    assert cs.round_number == 1
    cs = _drive_renovate(cs)
    assert cs.pending_stack == ()
    assert cs.players[0].house_material == HouseMaterial.CLAY
    f = _food_schedule(cs, 0)
    assert f[0] == 0                      # round 1 (current) untouched
    assert f[1:7] == [1, 1, 1, 1, 1, 1]   # rounds 2..7
    assert sum(f) == 6                    # rounds 8+ untouched


def test_late_renovate_clips_at_round_14():
    # Round 12: "next 6" = rounds 13..18, but only 13 and 14 exist.
    cs = _renovate_setup(clay=2, reed=1)
    cs = fast_replace(cs, round_number=12)
    cs = _drive_renovate(cs)
    f = _food_schedule(cs, 0)
    assert f[12] == 1 and f[13] == 1      # rounds 13, 14
    assert sum(f) == 2                    # rounds 15..18 dropped


def test_second_renovate_stacks_additively():
    # Two renovates in round 1: wood->clay at House Redevelopment, then (after
    # the opponent's turn) clay->stone at Farm Redevelopment. Both schedule
    # rounds 2..7, stacking to 2 food per slot.
    cs = _renovate_setup(clay=2, reed=2, stone=2)
    cs = with_space(cs, "farm_redevelopment", revealed=True)
    cs = _drive_renovate(cs)                              # renovate #1 (P0)
    assert cs.current_player == 1
    cs = step(cs, PlaceWorker(space="forest"))            # opponent's turn
    assert cs.current_player == 0
    cs = _drive_renovate(cs, space="farm_redevelopment")  # renovate #2 (P0)
    assert cs.players[0].house_material == HouseMaterial.STONE
    f = _food_schedule(cs, 0)
    assert f[1:7] == [2, 2, 2, 2, 2, 2]
    assert sum(f) == 12


def test_scheduled_food_collected_at_round_start():
    # Renovate in round 1, then drive the round-1 -> round-2 preparation
    # boundary: the round-2 slot's food is paid into the supply.
    cs = _renovate_setup(clay=2, reed=1)
    cs = _drive_renovate(cs)
    assert _food_schedule(cs, 0)[1] == 1                  # round 2 promised
    food_before = cs.players[0].resources.food
    cs = fast_replace(cs, phase=Phase.PREPARATION)        # round 1 completed
    out = _complete_preparation(cs)
    assert out.round_number == 2
    assert out.players[0].resources.food == food_before + 1
    assert _food_schedule(out, 0)[1] == 0                 # slot consumed


# ---------------------------------------------------------------------------
# Boundaries — opponent's renovate, unowned, hand-only
# ---------------------------------------------------------------------------

def test_opponents_renovate_schedules_nothing_for_owner():
    # P1 owns the card; P0 (not an owner) renovates. Neither player's schedule
    # gains anything: the effect fires only when the ACTING player owns it.
    cs = _renovate_setup(own_idx=1, clay=2, reed=1)
    cs = _drive_renovate(cs)
    assert cs.players[0].house_material == HouseMaterial.CLAY
    assert sum(_food_schedule(cs, 0)) == 0   # actor doesn't own it
    assert sum(_food_schedule(cs, 1)) == 0   # owner didn't renovate


def test_hand_only_card_is_inert():
    # The card sitting UNPLAYED in P0's hand fires nothing on P0's renovate.
    cs = _renovate_setup(own_idx=None, clay=2, reed=1)
    p0 = cs.players[0]
    p0 = fast_replace(p0, hand_occupations=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=(p0, cs.players[1]))
    cs = _drive_renovate(cs)
    assert cs.players[0].house_material == HouseMaterial.CLAY
    assert sum(_food_schedule(cs, 0)) == 0
