"""Tests for Gritter (minor D58): "At the end of each action in which you sow
vegetables in a field, you get 1 food for each vegetable field you have (including
the new ones)." Cost 1 wood; prereq play in round 5 or later.

Modeled as a before/after pair of mandatory, choice-free automatic effects on the
Sow sub-action host (register_auto on before_sow + after_sow), using a CardStore
snapshot of the vegetable-bearing-field count to detect THIS sow's veg planting.
The payout is 1 food per vegetable-bearing field the player CURRENTLY has (the
post-sow count, including the newly-sown fields).

Covers: registration + prereq; the grant firing via a real Grain Utilization veg
sow AND a real Cultivation veg sow; that it pays the full current veg-field count
including a pre-existing field; that a grain-only sow does NOT fire it; that it
does not fire when the card is not owned; the snapshot reset to a canonical 0;
re-firing on a fresh independent sow ("each time"); and the round-5 prereq.
"""
from __future__ import annotations

import agricola.cards.gritter  # noqa: F401  (registers the card; not in __init__ yet)

from agricola.actions import ChooseSubAction, CommitSow, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
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
    minors=("gritter",) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, round_number=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0, round_number=round_number), 0


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


def _with_veg_fields(state, idx, cells):
    """Place already-veg-sown FIELD tiles at the given (row, col) cells."""
    p = state.players[idx]
    grid = [[c for c in row] for row in p.farmyard.grid]
    for (r, c) in cells:
        grid[r][c] = Cell(cell_type=CellType.FIELD, veg=2)
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
# Registration & prerequisite
# ---------------------------------------------------------------------------

def test_gritter_registered():
    assert "gritter" in MINORS
    spec = MINORS["gritter"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert not spec.passing_left
    assert spec.prereq is not None
    bsow = {e.card_id for e in AUTO_EFFECTS.get("before_sow", [])}
    asow = {e.card_id for e in AUTO_EFFECTS.get("after_sow", [])}
    assert "gritter" in bsow
    assert "gritter" in asow


def test_gritter_prereq_round_5_or_later():
    spec = MINORS["gritter"]
    s_early, cp = _card_state(round_number=4)
    assert not prereq_met(spec, s_early, cp)
    s_ok, cp = _card_state(round_number=5)
    assert prereq_met(spec, s_ok, cp)
    s_late, cp = _card_state(round_number=10)
    assert prereq_met(spec, s_late, cp)


# ---------------------------------------------------------------------------
# The grant fires when vegetables are sown
# ---------------------------------------------------------------------------

def test_gritter_grants_one_food_per_veg_field_grain_utilization():
    s, cp = _card_state()
    s = _own_minor(s, cp, "gritter")
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, veg=1, food=0)
    food0 = s.players[cp].resources.food
    s = _to_before_sow(s, cp, "grain_utilization")
    # Sow 1 veg into the single field.
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow)
    # after_sow fired: +1 food (exactly one veg field now).
    assert s.players[cp].resources.food == food0 + 1
    # The field is now veg-sown, confirming a real sow ran.
    assert s.players[cp].farmyard.grid[1][0].veg > 0
    # Snapshot reset to the canonical 0.
    assert s.players[cp].card_state.get("gritter", 0) == 0


def test_gritter_grants_on_veg_sow_cultivation():
    s, cp = _card_state()
    s = _own_minor(s, cp, "gritter")
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, veg=1, food=0)
    s = _to_before_sow(s, cp, "cultivation")
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow)
    assert s.players[cp].resources.food == 1


def test_gritter_pays_full_current_count_including_existing_field():
    """One pre-existing veg field + one newly-sown veg field => 2 food
    ("1 food for each vegetable field you have, including the new ones")."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "gritter")
    # Pre-existing veg field at (1,0); an empty field at (1,1) to sow into.
    s = _with_veg_fields(s, cp, [(1, 0)])
    s = _with_empty_fields(s, cp, [(1, 1)])
    s = with_resources(s, cp, veg=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow)
    # 2 veg fields now: the pre-existing one + the new one.
    assert s.players[cp].resources.food == 2


def test_gritter_pays_for_two_new_veg_fields_in_one_sow():
    """Sowing veg into two empty fields in one action pays for both (2 food)."""
    s, cp = _card_state()
    s = _own_minor(s, cp, "gritter")
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, veg=2, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 2)
    s = step(s, sow)
    assert s.players[cp].resources.food == 2


# ---------------------------------------------------------------------------
# Eligibility boundaries: grain-only sow does NOT fire
# ---------------------------------------------------------------------------

def test_gritter_does_not_fire_on_grain_only_sow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "gritter")
    # A pre-existing veg field exists, but this sow plants only grain — so no
    # NEW veg field is planted and nothing is paid.
    s = _with_veg_fields(s, cp, [(1, 0)])
    s = _with_empty_fields(s, cp, [(1, 1)])
    s = with_resources(s, cp, grain=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 1 and a.veg == 0)
    s = step(s, sow)
    # No vegetables planted this action -> no grant.
    assert s.players[cp].resources.food == 0
    assert s.players[cp].farmyard.grid[1][1].grain > 0   # a real grain sow ran


# ---------------------------------------------------------------------------
# Not-owned: no grant
# ---------------------------------------------------------------------------

def test_gritter_does_not_fire_when_not_owned():
    s, cp = _card_state()
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, veg=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow)
    assert s.players[cp].resources.food == 0


# ---------------------------------------------------------------------------
# "Each time": a fresh independent veg sow fires the grant again
# ---------------------------------------------------------------------------

def test_gritter_fires_on_a_second_independent_sow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "gritter")
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, veg=2, food=0)
    # First veg sow: plants 1 veg field -> +1 food.
    s = _to_before_sow(s, cp, "grain_utilization")
    sow1 = next(a for a in legal_actions(s)
                if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow1)
    assert s.players[cp].resources.food == 1
    # Drive a brand-new, independent PendingSow. The field at (1,0) is now veg-sown,
    # so the second sow's before-snapshot starts at 1 and the payout is the new
    # 2-field count.
    s = fast_replace(s, current_player=cp, pending_stack=())
    s = _to_before_sow(s, cp, "cultivation")
    sow2 = next(a for a in legal_actions(s)
                if isinstance(a, CommitSow) and a.grain == 0 and a.veg == 1)
    s = step(s, sow2)
    # +2 food (now two veg fields), so total 1 + 2 = 3.
    assert s.players[cp].resources.food == 3
