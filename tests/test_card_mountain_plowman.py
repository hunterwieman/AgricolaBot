"""Tests for Mountain Plowman (occupation, E164; Ephipparius Expansion).

Card text: "Each time you plow at least 1 field tile, you get 1 sheep for each
field tile that you just plowed."

An `after_plow` automatic effect granting 1 sheep per plowed tile (via
grant_animals). A real Farmland plow drives the single-tile case; the per-tile
count is checked directly on a multi-tile PendingPlow frame (the Barrow Pusher
shape).
"""
from __future__ import annotations

import agricola.cards.mountain_plowman  # noqa: F401  (registers the card)

import pytest

import agricola.cards.mountain_plowman as mod
from agricola.actions import ChooseSubAction, CommitPlow, PlaceWorker, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.constants import CellType
from agricola.pending import PendingPlow
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import run_actions

_POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                 minors=tuple(f"m{i}" for i in range(20)))


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own_occ(state, idx, card_id="mountain_plowman"):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, occupations=p.occupations | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _plow_via_farmland(state, row, col):
    return run_actions(state, [
        PlaceWorker(space="farmland"),
        ChooseSubAction(name="plow"),
        CommitPlow(row=row, col=col),
        Stop(),   # pop PendingPlow's after-phase
        Stop(),   # pop the parent
    ])


# --- Registration -----------------------------------------------------------

def test_registered():
    assert "mountain_plowman" in OCCUPATIONS
    assert "mountain_plowman" in {e.card_id for e in AUTO_EFFECTS.get("after_plow", [])}


# --- Single-tile plow through the real engine flow --------------------------

def test_single_plow_grants_one_sheep():
    s = _own_occ(_card_state(), 0)
    before = s.players[0].animals.sheep
    s = _plow_via_farmland(s, 0, 2)
    assert s.players[0].farmyard.grid[0][2].cell_type == CellType.FIELD
    assert s.players[0].animals.sheep == before + 1   # 1 sheep fits the pet slot


def test_non_owner_plow_grants_nothing():
    s = _card_state()   # player 0 does NOT own the card
    before = s.players[0].animals.sheep
    s = _plow_via_farmland(s, 0, 2)
    assert s.players[0].animals.sheep == before


# --- Per-tile count on a multi-tile PendingPlow frame -----------------------

def test_per_tile_count_two_tiles():
    """A multi-shot granted plow (one PendingPlow, num_plowed=2, ONE after_plow
    flip) grants 1 sheep per TILE -> 2 sheep. `_apply` reads num_plowed off the
    frame on top (grant is synchronous; accommodation is separate)."""
    s = _own_occ(setup(0), 0)
    s = with_pending_stack(s, (PendingPlow(
        player_idx=0, initiated_by_id="card:test_grant", num_plowed=2),))
    before = s.players[0].animals.sheep
    after = mod._apply(s, 0)
    assert after.players[0].animals.sheep == before + 2


def test_base_single_plow_frame_counts_one():
    """A base single-shot plow has num_plowed == 0 -> exactly 1 sheep."""
    s = _own_occ(setup(0), 0)
    s = with_pending_stack(s, (PendingPlow(
        player_idx=0, initiated_by_id="space:farmland"),))
    before = s.players[0].animals.sheep
    after = mod._apply(s, 0)
    assert after.players[0].animals.sheep == before + 1


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
