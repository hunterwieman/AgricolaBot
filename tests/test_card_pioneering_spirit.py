"""Pioneering Spirit (D23) — the round-windowed owner-only card space."""
from __future__ import annotations

import agricola.cards  # noqa: F401

from agricola.actions import CommitRenovate, PlaceWorker, Proceed
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingRenovate
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from tests.factories import with_current_player, with_house, with_resources

POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                minors=tuple(f"m{i}" for i in range(20)))

CARD_ID = "pioneering_spirit"


def _edit(state, idx, **ch):
    p = fast_replace(state.players[idx], **ch)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _ps_state(round_number, owner=0):
    s, _env = setup_env(11, card_pool=POOL)
    s = with_current_player(s, 0)
    s = fast_replace(s, round_number=round_number)
    for i in (0, 1):
        s = _edit(s, i, hand_occupations=frozenset(), hand_minors=frozenset())
    p = s.players[owner]
    return _edit(s, owner, minor_improvements=p.minor_improvements | {CARD_ID})


def _placements(state):
    return [a for a in legal_actions(state)
            if isinstance(a, PlaceWorker) and a.space == f"card:{CARD_ID}"]


def test_round_windows():
    assert not _placements(_ps_state(2))                       # pre-window: dead
    assert not _placements(_ps_state(10))                      # post-window: dead
    s = with_resources(_ps_state(4), 0, reed=1, clay=2)        # wood house, 2 rooms
    assert [a.picks for a in _placements(s)] == [None]         # the renovation
    s = with_house(_ps_state(4), 0, HouseMaterial.STONE)
    assert not _placements(s)                                  # nothing to renovate
    picks = {a.picks for a in _placements(_ps_state(7))}
    assert picks == {("veg",), ("boar",), ("cattle",)}         # the goods choice


def test_owner_only():
    s = with_current_player(_ps_state(7, owner=1), 0)
    assert not _placements(s)                                  # opponent never sees it


def test_renovation_window_grants_the_standard_renovate():
    s = with_resources(_ps_state(4), 0, reed=1, clay=2)
    s = step(s, _placements(s)[0])
    s = step(s, Proceed())
    assert isinstance(s.pending_stack[-1], PendingRenovate)
    commits = [a for a in legal_actions(s) if isinstance(a, CommitRenovate)]
    assert commits
    s = step(s, commits[0])
    assert s.players[0].house_material == HouseMaterial.CLAY


def test_goods_window_grants_the_pick():
    s = _ps_state(7)
    veg_before = s.players[0].resources.veg
    s = step(s, PlaceWorker(space=f"card:{CARD_ID}", picks=("veg",)))
    s = step(s, Proceed())
    assert s.players[0].resources.veg == veg_before + 1
