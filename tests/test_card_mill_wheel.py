"""Tests for Mill Wheel (minor improvement, B64; Bubulcus Expansion).

Card text: "Each time you use the 'Grain Utilization' action space while the
'Fishing' accumulation space is occupied, you get an additional 2 food."

A Category-3 automatic-income card on a NON-atomic space (Grain Utilization)
with a CONDITIONAL clause (Fishing occupied): it registers a
`before_action_space` auto-effect WITHOUT an atomic action-space host hook,
since `_initiate_grain_utilization` pushes PendingGrainUtilization and fires the
before-automatics at the push. The grant lands the moment the worker is placed
(before any sow/bake sub-action), but only when Fishing carries a worker.

These tests build a genuinely-legal Grain Utilization placement from a Family
`setup()` (where the stage-1 grain_utilization space is revealed), occupy Fishing
via the test factory, and attach the minor to the player — a legal worker
placement, not the step()-skips-legality escape hatch.
"""
import agricola.cards.mill_wheel  # noqa: F401  (registers the card; not yet in cards/__init__.py)

from agricola.actions import PlaceWorker, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingGrainUtilization
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup
from tests.factories import with_current_player, with_majors, with_resources, with_space


def _gu_state(*, owner=None, current_player=0, fishing_occupied=True, grain=2, seed=0):
    """Family round-1 WORK state with a legal Grain Utilization placement
    (grain + a Fireplace so `_can_bake_bread`), `owner` (idx or None) holding the
    Mill Wheel minor, and Fishing occupied iff `fishing_occupied`."""
    s = setup(seed=seed)
    s = with_current_player(s, current_player)
    s = with_resources(s, current_player, grain=grain)
    s = with_majors(s, owner_by_idx={0: current_player})   # Fireplace (idx 0)
    if fishing_occupied:
        s = with_space(s, "fishing", workers=(0, 1))       # someone on Fishing
    if owner is not None:
        p = fast_replace(s.players[owner],
                         minor_improvements=s.players[owner].minor_improvements | {"mill_wheel"})
        s = fast_replace(s, players=tuple(
            p if i == owner else s.players[i] for i in range(2)))
    return s


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "mill_wheel" in MINORS
    spec = MINORS["mill_wheel"]
    assert spec.cost.resources == Resources(wood=2)
    assert spec.vps == 1
    assert not spec.passing_left
    # AUTO_EFFECTS is event-keyed; mill_wheel lives in the before_action_space bucket.
    entries = AUTO_EFFECTS.get("before_action_space", [])
    assert any(e.card_id == "mill_wheel" for e in entries), entries


# ---------------------------------------------------------------------------
# Effect via a real (legal) Grain Utilization placement
# ---------------------------------------------------------------------------

def test_mill_wheel_grants_food_when_fishing_occupied():
    s = _gu_state(owner=0, fishing_occupied=True)
    assert PlaceWorker(space="grain_utilization") in legal_actions(s)
    before = s.players[0].resources
    out = step(s, PlaceWorker(space="grain_utilization"))
    # before_action_space fires at the push → +2 food immediately.
    assert isinstance(out.pending_stack[-1], PendingGrainUtilization)
    assert out.players[0].resources.food == before.food + 2


def test_mill_wheel_grant_independent_of_sub_actions():
    """The grant lands once per use regardless of whether sow/bake is taken —
    drive the full turn (place → Stop, no sub-action) and confirm exactly +2."""
    s = _gu_state(owner=0, fishing_occupied=True)
    before = s.players[0].resources
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, Stop())   # pop the parent without sowing/baking; turn ends
    assert not s.pending_stack
    assert s.players[0].resources.food == before.food + 2


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_mill_wheel_does_not_fire_when_fishing_empty():
    """Fishing unoccupied → the conditional clause fails, no food granted."""
    s = _gu_state(owner=0, fishing_occupied=False)
    # Sanity: Fishing is genuinely empty in this state.
    from agricola.state import get_space
    assert get_space(s.board, "fishing").workers == (0, 0)
    before = s.players[0].resources
    out = step(s, PlaceWorker(space="grain_utilization"))
    assert out.players[0].resources.food == before.food


def test_mill_wheel_does_not_fire_on_other_space():
    """A different non-atomic space (Farmland) must not grant food, even with
    Fishing occupied."""
    s = _gu_state(owner=0, fishing_occupied=True)
    assert PlaceWorker(space="farmland") in legal_actions(s)
    before = s.players[0].resources
    out = step(s, PlaceWorker(space="farmland"))
    assert out.players[0].resources.food == before.food


def test_mill_wheel_does_not_fire_without_card():
    """No owner → Grain Utilization grants nothing extra (even with Fishing busy)."""
    s = _gu_state(owner=None, fishing_occupied=True)
    before = s.players[0].resources
    out = step(s, PlaceWorker(space="grain_utilization"))
    assert out.players[0].resources.food == before.food


def test_mill_wheel_fires_for_owner_only():
    """Owned by P0; when P1 (non-owner) uses Grain Utilization, no grant for
    either player (any_player=False — owner's effect doesn't fire off-turn)."""
    s = _gu_state(owner=0, current_player=1, fishing_occupied=True)
    before1 = s.players[1].resources
    before0 = s.players[0].resources
    out = step(s, PlaceWorker(space="grain_utilization"))
    assert out.players[1].resources.food == before1.food
    assert out.players[0].resources.food == before0.food
