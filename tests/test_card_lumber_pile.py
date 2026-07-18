"""Tests for Lumber Pile (minor improvement, E76; Ephipparius Expansion).

Card text (verbatim): "When you play this card, you can immediately return up to
3 stables from your farmyard board to your supply and get 3 wood for each."
Cost / prerequisite / VPs / passing: all none.

User ruling 66 (2026-07-17): the on-play "immediately" adds/changes nothing.

The optional on-play choice surfaces WIDE via the minor play-variant seam
(`register_play_minor_variant`): one zero-surcharge `CommitPlayMinor(variant=...)`
per non-empty subset of built-stable cells of size 1..min(3, num_built) — "up to
3 stables" — plus an always-present "skip". The variant string encodes the chosen
cells ("r,c" joined by "+"). `on_play` empties those STABLE cells (STABLE ->
EMPTY, pastures recomputed), grants 3 wood per stable returned, and — when the
player holds animals — flags the accommodation barrier so the engine surfaces the
keep-which choice if capacity dropped below the herd.

Tests drive the real PendingPlayMinor frame through legal_actions / step:
registration, the subset enumeration (incl. the 3-stable cap and "skip"-only with
no stable), the 1/2/3-stable returns (wood, cells emptied, supply restored), the
fenced-stable eviction (PendingAccommodate surfaces and resolves), and decline.
"""
import json
from itertools import combinations
from pathlib import Path

import agricola.cards.lumber_pile  # noqa: F401  -- registers the card
import agricola.cards.social_benefits  # noqa: F401  -- ordinary-minor control

from agricola.actions import CommitAccommodate, CommitPlayMinor
from agricola.cards.lumber_pile import CARD_ID, _encode, _variants
from agricola.cards.social_benefits import CARD_ID as SOCIAL_BENEFITS
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS
from agricola.constants import CellType
from agricola.engine import step
from agricola.helpers import stables_built, stables_in_supply
from agricola.legality import legal_actions, playable_minors
from agricola.pasture import compute_pastures_from_arrays
from agricola.pending import PendingAccommodate, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import Cell, Farmyard
from agricola.setup import CardPool, setup_env

from tests.factories import (
    with_animals,
    with_grid,
    with_pending_stack,
    with_resources,
)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, SOCIAL_BENEFITS) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Lumber Pile")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _with_stables(state, idx, cells):
    """Place STABLE cells (standalone — no fences, so the pasture cache stays ())."""
    return with_grid(state, idx,
                     {rc: Cell(cell_type=CellType.STABLE) for rc in cells})


def _fence_1x1(state, idx, row, col):
    """Fence the single cell (row, col) into a 1x1 pasture, recomputing the
    pasture cache from the (now stable-bearing) grid."""
    p = state.players[idx]
    h = [list(r) for r in p.farmyard.horizontal_fences]
    v = [list(r) for r in p.farmyard.vertical_fences]
    h[row][col] = True
    h[row + 1][col] = True
    v[row][col] = True
    v[row][col + 1] = True
    h_t = tuple(tuple(r) for r in h)
    v_t = tuple(tuple(r) for r in v)
    new_fy = Farmyard(
        grid=p.farmyard.grid, horizontal_fences=h_t, vertical_fences=v_t,
        pastures=compute_pastures_from_arrays(p.farmyard.grid, h_t, v_t))
    p = fast_replace(p, farmyard=new_fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _at_play_minor_frame(*, hand=(CARD_ID,), stables=(), fenced_stable=None,
                         sheep=0, **res):
    """A prefabricated state at a PendingPlayMinor frame for the current player,
    holding `hand`, the given standalone `stables` (and optionally one FENCED 1x1
    stable at `fenced_stable`), `sheep`, and exactly the given resources."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset(hand))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(
        p if i == cp else opp for i in range(2)))
    if res:
        state = with_resources(state, cp, **res)
    if sheep:
        state = with_animals(state, cp, sheep=sheep)
    if stables:
        state = _with_stables(state, cp, stables)
    if fenced_stable is not None:
        state = _with_stables(state, cp, [fenced_stable])
        state = _fence_1x1(state, cp, *fenced_stable)
    state = with_pending_stack(state, (PendingPlayMinor(
        player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _plays(state, cid=CARD_ID):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == cid]


def _variants_offered(state, cid=CARD_ID):
    return {a.variant for a in _plays(state, cid)}


def _commit_for(state, variant):
    (c,) = [a for a in _plays(state) if a.variant == variant]
    return c


# ---------------------------------------------------------------------------
# Registration (spec vs the JSON row)
# ---------------------------------------------------------------------------

def test_json_row():
    """Pin the catalog row this module encodes (all-None fields, text verbatim)."""
    assert _ROW["cost"] is None
    assert _ROW["prerequisites"] is None
    assert _ROW["vps"] is None
    assert _ROW["passing_left"] is None
    assert _ROW["text"] == (
        "When you play this card, you can immediately return up to 3 stables "
        "from your farmyard board to your supply and get 3 wood for each.")
    # The module docstring quotes the printed text verbatim.
    import agricola.cards.lumber_pile as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered_spec():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()                 # no cost
    assert spec.alt_costs == ()
    assert spec.cost_fn is None
    assert spec.min_occupations == 0
    assert spec.max_occupations is None
    assert spec.prereq is None                 # no prerequisite
    assert spec.vps == 0                       # no printed VP
    assert spec.passing_left is False          # not passing
    assert CARD_ID in PLAY_MINOR_VARIANTS      # the wide on-play choice


# ---------------------------------------------------------------------------
# Variant enumeration: subsets of built-stable cells, size 1..3, plus "skip"
# ---------------------------------------------------------------------------

def test_no_stables_only_skip():
    """With no stable built, "skip" is the sole route."""
    state, cp = _at_play_minor_frame(stables=())
    assert [v for v, _s in _variants(state, cp)] == ["skip"]
    assert _variants_offered(state) == {"skip"}


def test_subsets_three_distinct_stables():
    """3 stables at distinct cells -> C(3,1)+C(3,2)+C(3,3)=7 subsets + skip = 8."""
    cells = [(0, 2), (0, 3), (0, 4)]
    state, cp = _at_play_minor_frame(stables=cells)
    expected = {"skip"} | {
        _encode(s) for k in (1, 2, 3)
        for s in combinations(cells, k)
    }
    got = {v for v, _s in _variants(state, cp)}
    assert got == expected
    assert len(expected) == 8
    # Real-flow legal_actions surface the same set, all zero-surcharge.
    assert _variants_offered(state) == expected
    for a in _plays(state):
        assert a.payment == Resources()        # returning stables costs nothing


def test_up_to_three_caps_four_stables():
    """4 stables -> subsets of size 1..3 only (never the size-4 full set): 14 + skip."""
    cells = [(0, 1), (0, 2), (0, 3), (0, 4)]
    state, cp = _at_play_minor_frame(stables=cells)
    variants = {v for v, _s in _variants(state, cp)}
    assert "skip" in variants
    assert _encode(cells) not in variants      # the 4-stable subset is NOT offered ("up to 3")
    # 4 + 6 + 4 = 14 non-skip subsets.
    assert len(variants) == 15
    # Every offered non-skip subset names 1..3 distinct built-stable cells.
    for v in variants - {"skip"}:
        parts = v.split("+")
        assert 1 <= len(parts) <= 3
        assert len(set(parts)) == len(parts)


# ---------------------------------------------------------------------------
# Real-flow returns: wood, cells emptied, supply restored
# ---------------------------------------------------------------------------

def test_return_one_stable():
    state, cp = _at_play_minor_frame(stables=[(0, 2), (0, 3), (0, 4)])
    assert stables_built(state.players[cp].farmyard) == 3
    assert stables_in_supply(state.players[cp]) == 1
    state = step(state, _commit_for(state, _encode([(0, 3)])))
    p = state.players[cp]
    assert CARD_ID in p.minor_improvements
    assert CARD_ID not in p.hand_minors
    assert p.resources.wood == 3                       # 3 wood for the one stable
    assert p.farmyard.grid[0][3].cell_type is CellType.EMPTY   # returned cell
    assert p.farmyard.grid[0][2].cell_type is CellType.STABLE  # untouched
    assert p.farmyard.grid[0][4].cell_type is CellType.STABLE
    assert stables_built(p.farmyard) == 2
    assert stables_in_supply(p) == 2                   # supply restored by one


def test_return_two_stables():
    state, cp = _at_play_minor_frame(stables=[(0, 2), (0, 3), (0, 4)])
    state = step(state, _commit_for(state, _encode([(0, 2), (0, 4)])))
    p = state.players[cp]
    assert p.resources.wood == 6                       # 3 wood x 2 stables
    assert p.farmyard.grid[0][2].cell_type is CellType.EMPTY
    assert p.farmyard.grid[0][4].cell_type is CellType.EMPTY
    assert p.farmyard.grid[0][3].cell_type is CellType.STABLE
    assert stables_built(p.farmyard) == 1
    assert stables_in_supply(p) == 3


def test_return_three_stables_restores_full_supply():
    state, cp = _at_play_minor_frame(stables=[(0, 2), (0, 3), (0, 4)])
    state = step(state, _commit_for(state, _encode([(0, 2), (0, 3), (0, 4)])))
    p = state.players[cp]
    assert p.resources.wood == 9                       # 3 wood x 3 stables
    assert all(p.farmyard.grid[0][c].cell_type is CellType.EMPTY for c in (2, 3, 4))
    assert stables_built(p.farmyard) == 0
    # Supply fully restored -> a stable is buildable again (build legality gates on this).
    assert stables_in_supply(p) == 4


def test_skip_declines():
    """The "skip" route plays the card and returns nothing — no wood, stables intact."""
    state, cp = _at_play_minor_frame(stables=[(0, 3)], wood=1)
    state = step(state, _commit_for(state, "skip"))
    p = state.players[cp]
    assert CARD_ID in p.minor_improvements
    assert p.resources.wood == 1                       # unchanged (no return)
    assert p.farmyard.grid[0][3].cell_type is CellType.STABLE
    assert stables_built(p.farmyard) == 1
    assert not p.animals_need_accommodation


# ---------------------------------------------------------------------------
# Eviction: returning a FENCED stable can strand animals over capacity
# ---------------------------------------------------------------------------

def test_return_fenced_stable_strands_animals():
    """A 1x1 pasture with a stable holds 4 sheep (capacity 2*1*2^1 = 4). Returning
    that stable halves the pasture to capacity 2 (+1 house-pet slot = 3), so 4
    sheep no longer fit -> the barrier surfaces PendingAccommodate at the next
    decision boundary, and the player resolves the keep-which choice."""
    state, cp = _at_play_minor_frame(fenced_stable=(0, 0), sheep=4)
    p = state.players[cp]
    # Precondition: with the fenced stable, the 4 sheep fit (capacity 4 + pet slot).
    assert len(p.farmyard.pastures) == 1
    assert p.farmyard.pastures[0].num_stables == 1
    assert p.farmyard.pastures[0].capacity == 4
    assert not p.animals_need_accommodation

    state = step(state, _commit_for(state, _encode([(0, 0)])))
    p = state.players[cp]
    assert p.resources.wood == 3                        # the returned stable's wood
    assert p.farmyard.grid[0][0].cell_type is CellType.EMPTY
    # Capacity dropped below the herd -> the barrier surfaced the keep-which frame.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingAccommodate) and top.player_idx == cp
    assert p.animals == Animals(sheep=4)               # animals NOT trimmed by the card

    # Resolve: pick any offered keep-config (the frontier over the now-3-capacity farm).
    accs = [a for a in legal_actions(state) if isinstance(a, CommitAccommodate)]
    assert accs
    kept_totals = {a.sheep for a in accs}
    assert max(kept_totals) == 3                        # the reduced sheep capacity
    state = step(state, accs[0])
    p = state.players[cp]
    assert not p.animals_need_accommodation
    assert not any(isinstance(f, PendingAccommodate) for f in state.pending_stack)
    assert p.animals.sheep <= 3                         # herd now fits


def test_return_unfenced_stable_no_eviction_when_herd_fits():
    """Returning a standalone stable (a flexible slot) when the herd still fits
    raises no PendingAccommodate."""
    # One standalone stable (flex capacity 2: the stable + the house pet), 1 sheep.
    state, cp = _at_play_minor_frame(stables=[(0, 3)], sheep=1)
    state = step(state, _commit_for(state, _encode([(0, 3)])))
    p = state.players[cp]
    assert p.resources.wood == 3
    assert not any(isinstance(f, PendingAccommodate) for f in state.pending_stack)
    # Flag either never set (1 sheep still fits in the house-pet slot) or cleared
    # by the barrier — never a lingering unreconciled True.
    assert not p.animals_need_accommodation


# ---------------------------------------------------------------------------
# The seam does not widen ordinary minors
# ---------------------------------------------------------------------------

def test_ordinary_minor_unaffected():
    """Social Benefits (no variants_fn): exactly one play, variant=None."""
    state, _cp = _at_play_minor_frame(hand=(SOCIAL_BENEFITS,), reed=1)
    plays = _plays(state, SOCIAL_BENEFITS)
    assert len(plays) == 1
    assert plays[0].variant is None
