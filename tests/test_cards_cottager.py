"""Tests for Cottager (occupation, B87) — the build-room-OR-renovate choice on the
Day Laborer action space.

Cottager is the Category-4 card that grants a *choice* between two different
primitives, modeled as a play-variant trigger (like Scholar) on the action-space
host: an OPTIONAL `before_action_space` trigger on `day_laborer` that the host
enumerator expands into `FireTrigger(variant="room")` / `FireTrigger(variant="renovate")`,
with the host's Proceed as the decline. Firing pushes the standard
`PendingBuildRooms(max_builds=1)` / `PendingRenovate` with the normal cost. The host's
`triggers_resolved` gives once-per-use semantics.
"""
from __future__ import annotations

from agricola.actions import (
    CommitBuildRoom,
    CommitRenovate,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import PLAY_VARIANT_TRIGGERS, TRIGGERS
from agricola.constants import CellType, HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBuildRooms, PendingRenovate
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup_env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_resources(state, idx, **kw):
    p = fast_replace(state.players[idx], resources=Resources(**kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _num_rooms(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type == CellType.ROOM)


def _at_day_laborer(idx=0, **resources):
    """Own Cottager + the given resources, then place on Day Laborer (its host)."""
    s, _env = setup_env(0)
    ap = idx
    s = fast_replace(s, current_player=ap)
    s = _own(s, ap, "cottager")
    if resources:
        s = _set_resources(s, ap, **resources)
    s = step(s, PlaceWorker(space="day_laborer"))
    return s, ap


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_cottager_registered():
    assert "cottager" in OCCUPATIONS
    assert "cottager" in PLAY_VARIANT_TRIGGERS
    bas = {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert "cottager" in bas


# ---------------------------------------------------------------------------
# Variant surfacing
# ---------------------------------------------------------------------------

def test_cottager_surfaces_both_variants_plus_decline():
    # Afford a room (5 wood + 2 reed) AND a renovate (clay per room + reed).
    s, ap = _at_day_laborer(0, wood=10, clay=10, stone=10, reed=10)
    la = legal_actions(s)
    assert FireTrigger(card_id="cottager", variant="room") in la
    assert FireTrigger(card_id="cottager", variant="renovate") in la
    assert Proceed() in la            # optional → decline is the host's Proceed


def test_cottager_only_renovate_when_room_unaffordable():
    # Clay + reed afford a wood->clay renovate (2 rooms => 2 clay + 1 reed) but there
    # is no wood for a room (room = 5 wood + 2 reed).
    s, ap = _at_day_laborer(0, clay=2, reed=1)
    la = legal_actions(s)
    assert FireTrigger(card_id="cottager", variant="renovate") in la
    assert FireTrigger(card_id="cottager", variant="room") not in la


def test_cottager_no_variants_when_nothing_affordable():
    # No building materials → neither grant is legal → Cottager isn't offered; the
    # host is still pushed (Cottager is owned), so only its Proceed is legal.
    s, ap = _at_day_laborer(0)   # zero resources
    assert legal_actions(s) == [Proceed()]


# ---------------------------------------------------------------------------
# Build-room route — exactly one room
# ---------------------------------------------------------------------------

def test_cottager_build_room_exactly_one():
    s, ap = _at_day_laborer(0, wood=20, reed=4)
    rooms0 = _num_rooms(s, ap)
    s = step(s, FireTrigger(card_id="cottager", variant="room"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms) and top.max_builds == 1
    cells = [(a.row, a.col) for a in legal_actions(s) if isinstance(a, CommitBuildRoom)]
    s = step(s, CommitBuildRoom(row=cells[0][0], col=cells[0][1]))
    # max_builds=1 saturates → only Proceed (the multi-shot work-complete flip).
    assert legal_actions(s) == [Proceed()]
    s = step(s, Proceed())   # flip PendingBuildRooms to after
    s = step(s, Stop())      # pop PendingBuildRooms → back at the day_laborer host
    assert _num_rooms(s, ap) == rooms0 + 1
    # Once-per-use: Cottager is no longer offered at the host.
    la = legal_actions(s)
    assert not any(isinstance(a, FireTrigger) for a in la)
    assert Proceed() in la


def test_cottager_build_room_charges_cost_and_day_laborer_still_pays():
    s, ap = _at_day_laborer(0, wood=20, reed=4)
    wood0 = s.players[ap].resources.wood
    reed0 = s.players[ap].resources.reed
    food0 = s.players[ap].resources.food
    s = step(s, FireTrigger(card_id="cottager", variant="room"))
    cells = [(a.row, a.col) for a in legal_actions(s) if isinstance(a, CommitBuildRoom)]
    s = step(s, CommitBuildRoom(row=cells[0][0], col=cells[0][1]))
    s = step(s, Proceed())
    s = step(s, Stop())
    # Wood house room cost = 5 wood + 2 reed.
    assert s.players[ap].resources.wood == wood0 - 5
    assert s.players[ap].resources.reed == reed0 - 2
    # Finish the Day Laborer turn → +2 food.
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    assert s.players[ap].resources.food == food0 + 2


# ---------------------------------------------------------------------------
# Renovate route
# ---------------------------------------------------------------------------

def test_cottager_renovate_upgrades_house():
    # Default 2-room wood house → wood->clay costs 2 clay + 1 reed.
    s, ap = _at_day_laborer(0, clay=5, reed=2)
    assert s.players[ap].house_material is HouseMaterial.WOOD
    clay0 = s.players[ap].resources.clay
    s = step(s, FireTrigger(card_id="cottager", variant="renovate"))
    assert isinstance(s.pending_stack[-1], PendingRenovate)
    s = step(s, CommitRenovate())
    s = step(s, Stop())   # pop PendingRenovate's after-phase
    assert s.players[ap].house_material is HouseMaterial.CLAY
    assert s.players[ap].resources.clay == clay0 - 2   # 1 clay per room (2 rooms)


# ---------------------------------------------------------------------------
# Decline
# ---------------------------------------------------------------------------

def test_cottager_decline_via_proceed():
    s, ap = _at_day_laborer(0, wood=20, clay=20, stone=20, reed=20)
    rooms0 = _num_rooms(s, ap)
    mat0 = s.players[ap].house_material
    food0 = s.players[ap].resources.food
    s = step(s, Proceed())   # decline both grants; applies Day Laborer +2 food
    while s.pending_stack:
        s = step(s, legal_actions(s)[0])
    assert _num_rooms(s, ap) == rooms0          # no room built
    assert s.players[ap].house_material is mat0  # not renovated
    assert s.players[ap].resources.food == food0 + 2
