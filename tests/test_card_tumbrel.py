"""Tests for Tumbrel (minor improvement, B54; Bubulcus): "When you play this card,
you immediately get 2 food. Each time after you take an unconditional 'Sow'
action, you get 1 food for each stable you have."

Two effects:
  - On play (one-shot): +2 food immediately (modeled as `on_play`).
  - A repeating income on every unconditional Sow: after each Sow action, gain
    1 food per BUILT stable (register_auto on after_sow). Zero stables -> +0.

Covers: registration; the +2 on-play gain via a real play-minor engine flow; the
after_sow grant firing per built stable via real Grain Utilization AND Cultivation
sows; that the grant scales with built-stable count (0 stables -> +0, 2 stables ->
+2 food per sow); that it does not fire when the card is not owned; and that it
re-fires on a fresh, independent sow ("each time").
"""
from __future__ import annotations

import agricola.cards.tumbrel  # noqa: F401  (registers the card; not in __init__ yet)

from agricola.actions import ChooseSubAction, CommitSow, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_pending_stack, with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("tumbrel",) + tuple(f"m{i}" for i in range(20)),
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


def _with_stables(state, idx, cells):
    """Place STABLE tiles at the given (row, col) cells (built stables)."""
    p = state.players[idx]
    grid = [[c for c in row] for row in p.farmyard.grid]
    for (r, c) in cells:
        grid[r][c] = Cell(cell_type=CellType.STABLE)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return fast_replace(state, players=tuple(
        fast_replace(p, farmyard=fy) if i == idx else state.players[i] for i in range(2)))


def _to_before_sow(s, cp, space="grain_utilization"):
    """Place at `space`, choose sow -> PendingSow in its before-phase."""
    s = _reveal(s, space)
    s = step(s, PlaceWorker(space=space))
    s = step(s, ChooseSubAction(name="sow"))
    return s


def _drive_sow(s, grain, veg):
    """Apply the legal CommitSow with the given grain/veg counts."""
    sow = next(a for a in legal_actions(s)
               if isinstance(a, CommitSow) and a.grain == grain and a.veg == veg)
    return step(s, sow)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_tumbrel_registered():
    assert "tumbrel" in MINORS
    spec = MINORS["tumbrel"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert not spec.passing_left
    assert spec.prereq is None
    asow = {e.card_id for e in AUTO_EFFECTS.get("after_sow", [])}
    assert "tumbrel" in asow


# ---------------------------------------------------------------------------
# On-play: +2 food via a real play-minor engine flow
# ---------------------------------------------------------------------------

def test_tumbrel_on_play_grants_two_food():
    cs, cp = _card_state()
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({"tumbrel"}),
                     resources=Resources(wood=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    food0 = cs.players[cp].resources.food
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp,
                              initiated_by_id="space:meeting_place_cards"),))
    assert legal_actions(cs) == [sole_play_minor(cs, "tumbrel")]
    cs = step(cs, sole_play_minor(cs, "tumbrel"))
    p = cs.players[cp]
    assert p.resources.food == food0 + 2     # immediate +2 food
    assert p.resources.wood == 0             # paid the 1 wood
    assert "tumbrel" in p.minor_improvements  # kept (not passing)


# ---------------------------------------------------------------------------
# after_sow: +1 food per built stable, on real sow flows
# ---------------------------------------------------------------------------

def test_tumbrel_grants_food_per_stable_grain_utilization():
    s, cp = _card_state()
    s = _own_minor(s, cp, "tumbrel")
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = _with_stables(s, cp, [(2, 0), (2, 1)])   # 2 built stables
    s = with_resources(s, cp, grain=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = _drive_sow(s, grain=1, veg=0)
    # after_sow fired: +1 food per stable = +2 food.
    assert s.players[cp].resources.food == 2
    assert s.players[cp].farmyard.grid[1][0].grain > 0   # a real grain sow ran


def test_tumbrel_grants_food_per_stable_cultivation():
    s, cp = _card_state()
    s = _own_minor(s, cp, "tumbrel")
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = _with_stables(s, cp, [(2, 0), (2, 1), (2, 2)])   # 3 built stables
    s = with_resources(s, cp, veg=1, food=0)
    s = _to_before_sow(s, cp, "cultivation")
    s = _drive_sow(s, grain=0, veg=1)
    assert s.players[cp].resources.food == 3


# ---------------------------------------------------------------------------
# Eligibility / scaling boundary: zero stables -> harmless +0
# ---------------------------------------------------------------------------

def test_tumbrel_zero_stables_grants_no_food():
    s, cp = _card_state()
    s = _own_minor(s, cp, "tumbrel")
    s = _with_empty_fields(s, cp, [(1, 0)])
    # No stables placed.
    s = with_resources(s, cp, grain=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = _drive_sow(s, grain=1, veg=0)
    assert s.players[cp].resources.food == 0   # +0, the sow still ran
    assert s.players[cp].farmyard.grid[1][0].grain > 0


# ---------------------------------------------------------------------------
# Not owned: no grant
# ---------------------------------------------------------------------------

def test_tumbrel_does_not_fire_when_not_owned():
    s, cp = _card_state()
    # Card NOT owned, but two stables present.
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = _with_stables(s, cp, [(2, 0), (2, 1)])
    s = with_resources(s, cp, grain=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = _drive_sow(s, grain=1, veg=0)
    assert s.players[cp].resources.food == 0


# ---------------------------------------------------------------------------
# "Each time": a fresh independent sow fires the grant again
# ---------------------------------------------------------------------------

def test_tumbrel_fires_on_a_second_independent_sow():
    s, cp = _card_state()
    s = _own_minor(s, cp, "tumbrel")
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = _with_stables(s, cp, [(2, 0)])           # 1 built stable
    s = with_resources(s, cp, grain=2, food=0)
    # First sow.
    s = _to_before_sow(s, cp, "grain_utilization")
    s = _drive_sow(s, grain=1, veg=0)
    assert s.players[cp].resources.food == 1
    # Drive a brand-new, independent sow (Cultivation, fresh placement).
    s = fast_replace(s, current_player=cp, pending_stack=())
    s = _to_before_sow(s, cp, "cultivation")
    s = _drive_sow(s, grain=1, veg=0)
    assert s.players[cp].resources.food == 2     # fired a second time
