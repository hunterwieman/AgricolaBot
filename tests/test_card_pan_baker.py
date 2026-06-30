"""Tests for Pan Baker (occupation, A122; Artifex Expansion).

Card text: "Each time you use the 'Grain Utilization' action space, you also get
2 clay and 1 wood."

A Category-3 automatic income card on a NON-atomic space (Grain Utilization), so
it registers a `before_action_space` auto-effect WITHOUT an atomic action-space
host hook: `_initiate_grain_utilization` pushes PendingGrainUtilization and fires
the before-automatics at the push, so the +2 clay/+1 wood lands the moment the
worker is placed (before any sow/bake sub-action).

The card effect reads `p.occupations`, which is mode-independent, so these tests
build a genuinely-legal Grain Utilization placement from a Family `setup()` (where
the stage-1 grain_utilization space is revealed) and attach the occupation to the
player — a legal worker placement, not the step()-skips-legality escape hatch.
"""
import agricola.cards.pan_baker  # noqa: F401  (registers the card; not yet in cards/__init__.py)

from agricola.actions import PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingGrainUtilization
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_current_player, with_majors, with_resources


def _gu_state(*, owner=None, current_player=0, grain=2, seed=0):
    """Family round-1 WORK state with a legal Grain Utilization placement
    (grain + a Fireplace so `_can_bake_bread`), and `owner` (idx or None) holding
    the Pan Baker occupation."""
    s = setup(seed=seed)
    s = with_current_player(s, current_player)
    s = with_resources(s, current_player, grain=grain)
    s = with_majors(s, owner_by_idx={0: current_player})   # Fireplace (idx 0)
    if owner is not None:
        p = fast_replace(s.players[owner],
                         occupations=s.players[owner].occupations | {"pan_baker"})
        s = fast_replace(s, players=tuple(
            p if i == owner else s.players[i] for i in range(2)))
    return s


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert "pan_baker" in OCCUPATIONS
    # AUTO_EFFECTS is event-keyed; pan_baker lives in the before_action_space bucket.
    entries = AUTO_EFFECTS.get("before_action_space", [])
    assert any(e.card_id == "pan_baker" for e in entries), entries


# ---------------------------------------------------------------------------
# Effect via a real (legal) Grain Utilization placement
# ---------------------------------------------------------------------------

def test_pan_baker_grants_clay_and_wood_on_grain_utilization():
    s = _gu_state(owner=0)
    assert PlaceWorker(space="grain_utilization") in legal_actions(s)
    before = s.players[0].resources
    out = step(s, PlaceWorker(space="grain_utilization"))
    # before_action_space fires at the push → +2 clay, +1 wood immediately.
    assert isinstance(out.pending_stack[-1], PendingGrainUtilization)
    assert out.players[0].resources.clay == before.clay + 2
    assert out.players[0].resources.wood == before.wood + 1


def test_pan_baker_grant_independent_of_sub_actions():
    """The grant lands once per use regardless of whether sow/bake is taken —
    drive the full turn (place → Stop, no sub-action) and confirm exactly +2/+1."""
    s = _gu_state(owner=0)
    before = s.players[0].resources
    s = step(s, PlaceWorker(space="grain_utilization"))
    s = step(s, Stop())   # pop the parent without sowing/baking; turn ends
    assert not s.pending_stack
    assert s.players[0].resources.clay == before.clay + 2
    assert s.players[0].resources.wood == before.wood + 1


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_pan_baker_does_not_fire_on_other_space():
    """A different non-atomic space (Farmland) must not grant clay/wood."""
    s = _gu_state(owner=0)
    assert PlaceWorker(space="farmland") in legal_actions(s)
    before = s.players[0].resources
    out = step(s, PlaceWorker(space="farmland"))
    assert out.players[0].resources.clay == before.clay
    assert out.players[0].resources.wood == before.wood


def test_pan_baker_does_not_fire_without_card():
    """No owner → Grain Utilization grants nothing extra."""
    s = _gu_state(owner=None)
    before = s.players[0].resources
    out = step(s, PlaceWorker(space="grain_utilization"))
    assert out.players[0].resources.clay == before.clay
    assert out.players[0].resources.wood == before.wood


def test_pan_baker_fires_for_owner_only():
    """Owned by P0; when P1 (non-owner) uses Grain Utilization, no grant for
    either player (any_player=False — owner's effect doesn't fire off-turn)."""
    s = _gu_state(owner=0, current_player=1)
    before1 = s.players[1].resources
    before0 = s.players[0].resources
    out = step(s, PlaceWorker(space="grain_utilization"))
    assert out.players[1].resources.clay == before1.clay
    assert out.players[1].resources.wood == before1.wood
    assert out.players[0].resources.clay == before0.clay
    assert out.players[0].resources.wood == before0.wood
