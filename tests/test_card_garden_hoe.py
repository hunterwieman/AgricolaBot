"""Tests for Garden Hoe (minor A79): "Each time you take an unconditional 'Sow'
action planting vegetables in at least 1 field, you get 1 clay and 1 stone."

Modeled as a before/after pair of mandatory, choice-free automatic effects on the
Sow sub-action host (register_auto on before_sow + after_sow), using a CardStore
snapshot of the vegetable-bearing-field count to detect THIS sow's veg planting.
The grant is FLAT (+1 clay +1 stone once per qualifying sow, not per veg field).

Covers: registration; the grant firing via a real Grain Utilization veg sow AND a
real Cultivation veg sow; that a grain-only sow does NOT fire it; that it is flat
(planting two veg fields still grants exactly +1/+1); that it does not fire when the
card is not owned; the snapshot reset to a canonical 0; and re-firing on a fresh
independent sow ("each time").
"""
from __future__ import annotations

import agricola.cards.garden_hoe  # noqa: F401  (registers the card; not in __init__ yet)

from agricola.actions import ChooseSubAction, CommitSow, PlaceWorker
from agricola.cards.card_fields import card_holds, stacks_to_store
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_resources

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("garden_hoe",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _reveal(state, space_id):
    sp = fast_replace(get_space(state.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _with_empty_fields(state, idx, cells):
    """Place empty FIELD tiles at the given (row, col) cells, ready to sow into."""
    p = state.players[idx]
    grid = [[c for c in row] for row in p.farmyard.grid]
    for (r, c) in cells:
        grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return fast_replace(state, players=tuple(
        fast_replace(p, farmyard=fy) if i == idx else state.players[i] for i in range(2)))


def _to_before_sow(s, cp, space="grain_utilization"):
    """Place at `space`, choose sow -> PendingSow in its before-phase."""
    s = _reveal(s, space)
    s = step(s, PlaceWorker(space=space))
    s = step(s, ChooseSubAction(name="sow"))
    return s


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_garden_hoe_registered():
    assert "garden_hoe" in MINORS
    spec = MINORS["garden_hoe"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert not spec.passing_left
    assert spec.prereq is None
    bsow = {e.card_id for e in AUTO_EFFECTS.get("before_sow", [])}
    asow = {e.card_id for e in AUTO_EFFECTS.get("after_sow", [])}
    assert "garden_hoe" in bsow
    assert "garden_hoe" in asow


# ---------------------------------------------------------------------------
# The grant fires when vegetables are sown
# ---------------------------------------------------------------------------

def test_garden_hoe_grants_on_veg_sow_grain_utilization():
    s, cp = _card_state()
    s = _own_minor(s, cp, "garden_hoe")
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, veg=1, clay=0, stone=0)
    clay0 = s.players[cp].resources.clay
    stone0 = s.players[cp].resources.stone
    s = _to_before_sow(s, cp, "grain_utilization")
    # Sow 1 veg into the single field.
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow)
    # after_sow fired: +1 clay +1 stone.
    assert s.players[cp].resources.clay == clay0 + 1
    assert s.players[cp].resources.stone == stone0 + 1
    # The field is now veg-sown, confirming a real sow ran.
    assert s.players[cp].farmyard.grid[1][0].veg > 0
    # Snapshot reset to the canonical 0.
    assert s.players[cp].card_state.get("garden_hoe", 0) == 0


def test_garden_hoe_grants_on_veg_sow_cultivation():
    s, cp = _card_state()
    s = _own_minor(s, cp, "garden_hoe")
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, veg=1, clay=0, stone=0)
    s = _to_before_sow(s, cp, "cultivation")
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow)
    assert s.players[cp].resources.clay == 1
    assert s.players[cp].resources.stone == 1


# ---------------------------------------------------------------------------
# Eligibility boundaries: grain-only sow does NOT fire; flat grant
# ---------------------------------------------------------------------------

def test_garden_hoe_does_not_fire_on_grain_only_sow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "garden_hoe")
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, grain=1, clay=0, stone=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 1 and a.veg == 0)
    s = step(s, sow)
    # No vegetables planted -> no grant.
    assert s.players[cp].resources.clay == 0
    assert s.players[cp].resources.stone == 0
    assert s.players[cp].farmyard.grid[1][0].grain > 0   # a real grain sow ran


def test_garden_hoe_is_flat_two_veg_fields_one_grant():
    """Planting vegetables in TWO fields in one sow still grants exactly +1/+1."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "garden_hoe")
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, veg=2, clay=0, stone=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    # Sow 2 veg (one into each of the two empty fields).
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 2)
    s = step(s, sow)
    assert s.players[cp].resources.clay == 1     # flat, not 2
    assert s.players[cp].resources.stone == 1


# ---------------------------------------------------------------------------
# Not-owned: no grant
# ---------------------------------------------------------------------------

def test_garden_hoe_does_not_fire_when_not_owned():
    s, cp = _card_state()
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, veg=1, clay=0, stone=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow)
    assert s.players[cp].resources.clay == 0
    assert s.players[cp].resources.stone == 0


# ---------------------------------------------------------------------------
# "Each time": a fresh independent veg sow fires the grant again
# ---------------------------------------------------------------------------

def test_garden_hoe_fires_on_a_second_independent_sow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "garden_hoe")
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, veg=2, clay=0, stone=0)
    # First veg sow.
    s = _to_before_sow(s, cp, "grain_utilization")
    sow1 = next(a for a in legal_actions(s)
                if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow1)
    assert s.players[cp].resources.clay == 1
    # Drive a brand-new, independent PendingSow (Cultivation, fresh placement). The
    # field at (1,0) is now veg-sown, so the second sow's before-snapshot starts at 1.
    s = fast_replace(s, current_player=cp, pending_stack=())
    s = _to_before_sow(s, cp, "cultivation")
    # The before-snapshot must reflect the field already veg-sown in the first action.
    sow2 = next(a for a in legal_actions(s)
                if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow2)
    assert s.players[cp].resources.clay == 2     # the grant fired a second time
    assert s.players[cp].resources.stone == 2


# ---------------------------------------------------------------------------
# Card-fields (ruling 45, 2026-07-12): a veg sow onto a card-field is
# "planting vegetables in at least 1 field" — 1 per card (ruling 47).
# ---------------------------------------------------------------------------

def _own_card_field(s, idx, cid, stacks=None):
    """Give player `idx` the card-field `cid` in play, optionally with contents."""
    p = s.players[idx]
    store = (stacks_to_store(p.card_state, cid, stacks)
             if stacks is not None else p.card_state)
    p = fast_replace(p, minor_improvements=p.minor_improvements | {cid},
                     card_state=store)
    return fast_replace(
        s, players=tuple(p if i == idx else s.players[i] for i in range(2)))


def test_garden_hoe_fires_on_a_card_field_only_veg_sow():
    """A veg sow onto Beanfield ALONE (no grid fields anywhere) plants
    vegetables in a field and earns the +1 clay +1 stone — the pre-ruling-45
    counter saw no veg field appear and granted nothing."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "garden_hoe")
    s = _own_card_field(s, cp, "beanfield")
    s = with_resources(s, cp, veg=1, clay=0, stone=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 0
               and a.card_sows == (("beanfield", "veg"),))
    s = step(s, sow)
    # The beanfield got its veg (a real card sow ran)...
    assert card_holds(s.players[cp], "beanfield", "veg") == 2
    # ...and the flat grant fired.
    assert s.players[cp].resources.clay == 1
    assert s.players[cp].resources.stone == 1


def test_garden_hoe_does_not_fire_on_a_grain_only_card_field_sow():
    """A grain sow onto Artichoke Field plants no vegetables — no grant."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "garden_hoe")
    s = _own_card_field(s, cp, "artichoke_field")
    s = with_resources(s, cp, grain=1, veg=0, clay=0, stone=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 0
               and a.card_sows == (("artichoke_field", "grain"),))
    s = step(s, sow)
    assert card_holds(s.players[cp], "artichoke_field", "grain") == 3
    assert s.players[cp].resources.clay == 0
    assert s.players[cp].resources.stone == 0
