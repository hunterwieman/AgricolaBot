"""Tests for Chapel (A39) — the first FOR-ALL card action space and the toll
seam's first consumer (ruling 86): "This is an action space for all. A player
who uses it gets 3 bonus points. If another player uses it, they must first
pay you 1 grain."
"""
from __future__ import annotations

import agricola.cards  # noqa: F401  -- populate the registries

from agricola.actions import FireTrigger, PlaceWorker, Proceed
from agricola.cards.specs import MINORS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import with_current_player, with_resources, with_space

POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                minors=tuple(f"m{i}" for i in range(20)))


def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _cards_state(chapel_owner=0):
    s, _env = setup_env(11, card_pool=POOL)
    s = with_current_player(s, 0)
    for idx in (0, 1):
        s = _edit_player(s, idx, hand_occupations=frozenset(),
                         hand_minors=frozenset())
    p = s.players[chapel_owner]
    return _edit_player(s, chapel_owner,
                        minor_improvements=p.minor_improvements | {"chapel"})


def _chapel_placements(state):
    return [a for a in legal_actions(state)
            if isinstance(a, PlaceWorker) and a.space == "card:chapel"]


def test_registered_for_all_with_grain_toll():
    from agricola.cards.card_spaces import CARD_ACTION_SPACES
    assert "chapel" in MINORS
    spec = CARD_ACTION_SPACES["chapel"]
    assert spec.for_all
    assert spec.toll.resources == Resources(grain=1)


def test_owner_places_toll_free_and_the_user_banks_3():
    s = _cards_state(chapel_owner=0)
    grain_before = s.players[0].resources.grain
    placements = _chapel_placements(s)
    assert placements, "owner's own for-all space must be placeable"
    s = step(s, placements[0])
    top = s.pending_stack[-1]
    assert isinstance(top, PendingActionSpace) and top.space_id == "card:chapel"
    s = step(s, Proceed())
    assert s.players[0].resources.grain == grain_before   # no toll for the owner
    assert s.players[0].card_state.get("chapel_bonus") == 3


def test_nonowner_gated_on_the_toll_and_pays_before_the_use():
    s = _cards_state(chapel_owner=1)          # P0 is the NON-owner
    s = with_resources(s, 0, grain=0)
    assert not _chapel_placements(s)          # ruling 86: unpayable toll = illegal

    s = with_resources(s, 0, grain=1)
    placements = _chapel_placements(s)
    assert placements                          # for-all + toll payable
    p1_grain = s.players[1].resources.grain
    s = step(s, placements[0])
    # The toll transferred at the ARRIVAL, before any before-window effect:
    # the host is still in its before phase and the grain has already moved.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingActionSpace) and top.phase == "before"
    assert s.players[0].resources.grain == 0
    assert s.players[1].resources.grain == p1_grain + 1
    s = step(s, Proceed())
    assert s.players[0].card_state.get("chapel_bonus") == 3   # the USER banks


def test_banked_points_score_without_ownership():
    s = _cards_state(chapel_owner=1)
    base_total, _ = score(s, 0)
    p = s.players[0]
    s2 = _edit_player(s, 0, card_state=p.card_state.set("chapel_bonus", 6))
    total, _ = score(s2, 0)
    assert total == base_total + 6


def test_straw_hat_move_onto_opponents_chapel_pays_the_toll():
    s = _cards_state(chapel_owner=1)
    p0 = s.players[0]
    s = _edit_player(s, 0, minor_improvements=p0.minor_improvements | {"straw_hat"})
    s = fast_replace(s, phase=Phase.WORK, round_number=3, starting_player=0)
    # Drain the round: P0's person 1 on farmland, person 2 elsewhere; P1 placed.
    for idx, spaces in ((0, ("farmland", "day_laborer")), (1, ("clay_pit", "reed_bank"))):
        for sid in spaces:
            sp = get_space(s.board, sid)
            workers = tuple(w + (1 if j == idx else 0)
                            for j, w in enumerate(sp.workers))
            s = with_space(s, sid, workers=workers)
            p = s.players[idx]
            s = _edit_player(
                s, idx, people_home=p.people_home - 1,
                placements_this_round=p.placements_this_round + 1,
                standing_workers=p.standing_workers
                + ((p.placements_this_round + 1, sid),))

    s = with_resources(s, 0, grain=0)
    s = _advance_until_decision(s)
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == "end_of_work"
    fires = [a for a in legal_actions(s)
             if isinstance(a, FireTrigger) and a.card_id == "straw_hat"]
    assert not any(f.variant == "card:chapel" for f in fires)   # toll gates the move

    s = with_resources(s, 0, grain=1)
    fires = [a for a in legal_actions(s)
             if isinstance(a, FireTrigger) and a.card_id == "straw_hat"]
    assert any(f.variant == "card:chapel" for f in fires)
    p1_grain = s.players[1].resources.grain
    s = step(s, FireTrigger(card_id="straw_hat", variant="card:chapel"))
    assert s.players[0].resources.grain == 0                    # toll paid on arrival
    assert s.players[1].resources.grain == p1_grain + 1
    s = step(s, Proceed())
    assert s.players[0].card_state.get("chapel_bonus") == 3
    assert (1, "card:chapel") in s.players[0].standing_workers  # number preserved
