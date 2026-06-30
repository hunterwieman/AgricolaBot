"""Stable (minor C2; Consul Dirigens): a free, MANDATORY granted Build-Stable on play.

Card text: "Immediately build 1 stable. (The stable costs you nothing, but you must pay
the cost shown on this card.)" Cost: 1 Wood.
"""
from __future__ import annotations

import agricola.cards.stable  # noqa: F401  (registers the card)

from agricola.actions import CommitBuildStable, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.stable import CARD_ID, FRAME_ID
from agricola.constants import CellType, GameMode
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBuildStables
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import setup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cards(wood=1):
    """A fresh CARDS-mode state (P0 to move) with the given wood. The default farm has empty
    cells and 4 stables in supply, so a free stable is buildable."""
    state = fast_replace(setup(0), mode=GameMode.CARDS)
    p = fast_replace(state.players[0], resources=fast_replace(
        state.players[0].resources, wood=wood))
    return fast_replace(state, players=tuple(
        p if i == 0 else state.players[i] for i in range(2)))


def _set_grid(state, idx, cells, cell_type):
    """Overwrite `cells` (an iterable of (r, c)) on player `idx`'s grid with `cell_type`."""
    p = state.players[idx]
    grid = [list(row) for row in p.farmyard.grid]
    for (r, c) in cells:
        grid[r][c] = fast_replace(grid[r][c], cell_type=cell_type)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    p = fast_replace(p, farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _fill_empty(state, idx, cell_type):
    empties = [(r, c) for r in range(3) for c in range(5)
               if state.players[idx].farmyard.grid[r][c].cell_type == CellType.EMPTY]
    return _set_grid(state, idx, empties, cell_type)


def _play(s, i=0): return MINORS[CARD_ID].on_play(s, i)


# ---------------------------------------------------------------------------
# Registration + cost
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS


def test_registration_cost():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.min_occupations == 0 and spec.max_occupations is None


# ---------------------------------------------------------------------------
# Playability prereq (mandatory: unplayable if no free stable can be built)
# ---------------------------------------------------------------------------

def test_prereq_playable_on_fresh_farm():
    # Default farm: empty cells + 4 stables in supply -> a free stable is buildable.
    assert prereq_met(MINORS[CARD_ID], _cards(), 0)


def test_prereq_playable_even_with_zero_wood():
    # The build itself is FREE; the 1-wood card cost is paid by the play-minor path, not the
    # prereq. So even with no wood the playability gate (a buildable stable) is satisfied.
    assert prereq_met(MINORS[CARD_ID], _cards(wood=0), 0)


def test_prereq_unplayable_with_no_empty_cell():
    # Fill every empty cell with FIELD -> no legal stable cell -> unplayable.
    s = _fill_empty(_cards(), 0, CellType.FIELD)
    assert not prereq_met(MINORS[CARD_ID], s, 0)


def test_prereq_unplayable_with_no_stable_in_supply():
    # Build 4 stables (exhausting the supply of 4) on a corner block; empty cells remain
    # elsewhere, so the ONLY thing missing is a stable in supply -> unplayable.
    s = _set_grid(_cards(), 0, [(0, 4), (1, 4), (2, 4), (0, 3)], CellType.STABLE)
    from agricola.helpers import stables_in_supply
    assert stables_in_supply(s.players[0].farmyard) == 0
    assert not prereq_met(MINORS[CARD_ID], s, 0)


# ---------------------------------------------------------------------------
# The grant: a free stable, mandatory, exactly one
# ---------------------------------------------------------------------------

def test_on_play_pushes_free_stable_grant():
    s = _play(_cards())
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildStables)
    assert top.player_idx == 0
    assert top.initiated_by_id == FRAME_ID
    assert top.cost == Resources()              # the stable is FREE
    assert top.max_builds == 1
    assert top.build_stables_action is False    # a card effect, not the literal action
    assert top.num_built == 0


def test_grant_is_mandatory_only_commits_no_decline():
    # At num_built=0 the enumerator offers ONLY CommitBuildStable cells (no Proceed/Stop),
    # so the build is forced -- "Immediately build 1 stable".
    s = _play(_cards())
    la = legal_actions(s)
    assert la and all(isinstance(a, CommitBuildStable) for a in la)
    assert not any(isinstance(a, (Proceed, Stop)) for a in la)


def test_build_is_free_and_completes():
    s = _play(_cards(wood=1))
    before_wood = s.players[0].resources.wood
    # Find an empty cell to build on.
    rc = next((r, c) for r in range(3) for c in range(5)
              if s.players[0].farmyard.grid[r][c].cell_type == CellType.EMPTY)
    s = step(s, CommitBuildStable(row=rc[0], col=rc[1]))
    top = s.pending_stack[-1]
    assert top.num_built == 1
    # After one build the cap is saturated -> only Proceed (no further commits).
    nxt = legal_actions(s)
    assert not any(isinstance(a, CommitBuildStable) for a in nxt)
    assert any(isinstance(a, Proceed) for a in nxt)
    s = step(s, Proceed())   # flip to after-phase
    s = step(s, Stop())      # pop the build host
    # The stable now sits on the chosen cell and NO wood was spent by the build.
    assert s.players[0].farmyard.grid[rc[0]][rc[1]].cell_type == CellType.STABLE
    assert s.players[0].resources.wood == before_wood
    assert all(not isinstance(f, PendingBuildStables) for f in s.pending_stack)


def test_grant_respects_empty_cells_only():
    # An occupied cell (FIELD) is never a legal stable target.
    s = _set_grid(_cards(), 0, [(1, 1)], CellType.FIELD)
    s = _play(s)
    commits = {(a.row, a.col) for a in legal_actions(s) if isinstance(a, CommitBuildStable)}
    assert (1, 1) not in commits
    assert commits  # other empty cells remain
