"""Tests for Hand Truck (minor B67): "Each time before you take a 'Bake Bread'
action, you also get 1 grain for each of your people occupying an accumulation
space." Clarification: "You must bake if you receive the grain." Cost 1 wood.

Modeled as a mandatory, choice-free `before_bake_bread` automatic effect
(register_auto) — the +N grain (N = the owner's people on accumulation spaces)
lands at the PendingBakeBread push (the sub-action before-phase), before
CommitBake, with no declinable FireTrigger.

Covers: registration; the grant firing via a real Grain Utilization bake; that
the count scales with the number of the owner's people on accumulation spaces and
ignores the opponent's people; that only the OWNER's accumulation-space workers
count (the bake host itself is not an accumulation space → no self-count); the
eligibility boundary (no grant when zero people on accumulation spaces); that the
grain is on hand BEFORE CommitBake (it is bakeable this action); and that it does
not fire when the card is not owned.
"""
from __future__ import annotations

import agricola.cards.hand_truck  # noqa: F401  (registers the card; not in __init__ yet)

from agricola.actions import ChooseSubAction, CommitBake, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBakeBread
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors, with_resources, with_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("hand_truck",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=0)
    # Drop both hands so nothing else is deterministically playable.
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _put_workers(state, space_id, workers):
    """Place `workers` = (p0_count, p1_count) on `space_id` (an accumulation space)."""
    return with_space(state, space_id, revealed=True, workers=workers)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_hand_truck_registered():
    assert "hand_truck" in MINORS
    spec = MINORS["hand_truck"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert not spec.passing_left
    assert spec.prereq is None
    before = {e.card_id for e in AUTO_EFFECTS.get("before_bake_bread", [])}
    assert "hand_truck" in before


# ---------------------------------------------------------------------------
# The grant fires via a real Bake Bread flow (before the commit)
# ---------------------------------------------------------------------------

def _to_before_bake(cs):
    """Place at Grain Utilization and choose bake_bread → PendingBakeBread before-phase."""
    cs = with_space(cs, "grain_utilization", revealed=True)
    cs = step(cs, PlaceWorker(space="grain_utilization"))
    cs = step(cs, ChooseSubAction(name="bake_bread"))
    return cs


def test_hand_truck_grants_grain_before_bake():
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})           # Fireplace (1 grain -> 2 food)
    cs = _own_minor(cs, 0, "hand_truck")
    # Two of P0's people on accumulation spaces (forest + clay_pit), start with 0 grain.
    cs = _put_workers(cs, "forest", (1, 0))
    cs = _put_workers(cs, "clay_pit", (1, 0))
    assert cs.players[0].resources.grain == 0
    cs = _to_before_bake(cs)
    # The auto fired at the PendingBakeBread push: +2 grain on hand BEFORE any CommitBake.
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingBakeBread)
    assert cs.players[0].resources.grain == 2
    # The granted grain is bakeable this action.
    assert any(isinstance(a, CommitBake) for a in legal_actions(cs))
    # Bake 1 of the 2 granted grain via the Fireplace -> +2 food, 1 grain left.
    food_before = cs.players[0].resources.food
    cs = step(cs, CommitBake(grain=1))
    assert cs.players[0].resources.food == food_before + 2
    assert cs.players[0].resources.grain == 1


def test_hand_truck_count_scales_with_people():
    """The grant equals the number of the OWNER's people on accumulation spaces."""
    for n in (1, 3):
        cs = _card_state()
        cs = with_majors(cs, owner_by_idx={0: 0})
        cs = _own_minor(cs, 0, "hand_truck")
        cs = _put_workers(cs, "forest", (n, 0))
        cs = _to_before_bake(cs)
        assert isinstance(cs.pending_stack[-1], PendingBakeBread)
        assert cs.players[0].resources.grain == n, f"n={n}"


def test_hand_truck_ignores_opponent_people():
    """Only the OWNER's people on accumulation spaces are counted, not the opponent's."""
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})
    cs = _own_minor(cs, 0, "hand_truck")
    # P0 has 1 on forest; P1 has 3 across accumulation spaces (must not be counted).
    cs = _put_workers(cs, "forest", (1, 2))
    cs = _put_workers(cs, "clay_pit", (0, 1))
    cs = _to_before_bake(cs)
    assert cs.players[0].resources.grain == 1            # only P0's single worker


def test_hand_truck_excludes_bake_host_worker():
    """The bake host (Grain Utilization) is not an accumulation space, so the worker
    that initiates the bake is not self-counted: 0 people on accumulation spaces ->
    no grain even though a worker now sits on Grain Utilization."""
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})
    cs = _own_minor(cs, 0, "hand_truck")
    # Give 1 grain so a bake is reachable with zero accumulation-space people.
    cs = with_resources(cs, 0, grain=1)
    cs = _to_before_bake(cs)
    assert isinstance(cs.pending_stack[-1], PendingBakeBread)
    # No grant: the only placed worker is on Grain Utilization (not an accumulation space).
    assert cs.players[0].resources.grain == 1


def test_hand_truck_no_grant_when_no_people_on_accumulation_spaces():
    """Eligibility gates on count > 0, so an empty +0 grant is never applied."""
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})
    cs = _own_minor(cs, 0, "hand_truck")
    cs = with_resources(cs, 0, grain=2)                 # seed grain so a bake is possible
    cs = _to_before_bake(cs)
    assert isinstance(cs.pending_stack[-1], PendingBakeBread)
    assert cs.players[0].resources.grain == 2           # unchanged: nobody on accum spaces


def test_hand_truck_does_not_fire_when_not_owned():
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})
    # Card NOT owned; people are on accumulation spaces but no grant should fire.
    cs = _put_workers(cs, "forest", (2, 0))
    cs = with_resources(cs, 0, grain=1)                 # seed grain so a bake is reachable
    cs = _to_before_bake(cs)
    assert isinstance(cs.pending_stack[-1], PendingBakeBread)
    assert cs.players[0].resources.grain == 1           # only the seed grain, no grant


def test_hand_truck_enables_bake_at_zero_grain():
    """The whole point of the clarification: with a baker + >=1 person on an accumulation
    space, the owner can take a Bake Bread action even at 0 grain (to harvest Hand Truck's
    grain, then bake it). legal_actions must OFFER bake_bread at the Grain Utilization parent
    despite 0 grain — exercised through the real legality gate (_can_bake_bread extension),
    not a force-step."""
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})           # Fireplace (a baker)
    cs = _own_minor(cs, 0, "hand_truck")
    cs = _put_workers(cs, "forest", (1, 0))             # 1 person on an accumulation space
    assert cs.players[0].resources.grain == 0
    cs = with_space(cs, "grain_utilization", revealed=True)
    cs = step(cs, PlaceWorker(space="grain_utilization"))
    assert ChooseSubAction(name="bake_bread") in legal_actions(cs)


def test_hand_truck_does_not_over_enable_bake_at_zero_grain():
    """The extension does not over-enable: at 0 grain with NO people on accumulation
    spaces, Bake Bread stays illegal (the grant could not supply any grain)."""
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})           # has a baker
    cs = _own_minor(cs, 0, "hand_truck")
    assert cs.players[0].resources.grain == 0           # and nobody on accumulation spaces
    cs = with_space(cs, "grain_utilization", revealed=True)
    cs = step(cs, PlaceWorker(space="grain_utilization"))
    assert ChooseSubAction(name="bake_bread") not in legal_actions(cs)


def test_hand_truck_fires_each_bake_action():
    """'Each time' — a second, independent Bake Bread action fires the grant again."""
    cs = _card_state()
    cs = with_majors(cs, owner_by_idx={0: 0})
    cs = _own_minor(cs, 0, "hand_truck")
    cs = _put_workers(cs, "forest", (1, 0))
    # First bake action: +1 grain, then bake it away.
    cs = _to_before_bake(cs)
    assert cs.players[0].resources.grain == 1
    cs = step(cs, CommitBake(grain=1))                  # consume the granted grain
    assert cs.players[0].resources.grain == 0
    # Drive a brand-new, independent Bake Bread action (fresh PendingBakeBread push).
    cs = fast_replace(cs, current_player=0, pending_stack=())
    cs = with_space(cs, "grain_utilization", revealed=True)
    cs = step(cs, PlaceWorker(space="grain_utilization"))
    cs = step(cs, ChooseSubAction(name="bake_bread"))
    assert isinstance(cs.pending_stack[-1], PendingBakeBread)
    assert cs.players[0].resources.grain == 1           # the grant fired again
