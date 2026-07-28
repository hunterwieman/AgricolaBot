"""Fishing Net (C51) — the first BOARD-space toll (ruling 86 item 9: paid at
the arrival before the space's before-window/effect; gates unpayable arrivals
liquidation-aware; the returning-home deposit for other-player-use rounds)."""
from __future__ import annotations

import agricola.cards  # noqa: F401

from agricola.actions import CommitFoodPayment, PlaceWorker
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingFoodPayment
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import with_animals, with_current_player, with_majors, \
    with_resources, with_space

POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                minors=tuple(f"m{i}" for i in range(20)))


def _edit(state, idx, **ch):
    p = fast_replace(state.players[idx], **ch)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _fn_state(owner=1):
    s, _env = setup_env(11, card_pool=POOL)
    s = with_current_player(s, 0)
    for i in (0, 1):
        s = _edit(s, i, hand_occupations=frozenset(), hand_minors=frozenset())
    p = s.players[owner]
    s = _edit(s, owner, minor_improvements=p.minor_improvements | {"fishing_net"})
    return with_space(s, "fishing", accumulated_amount=3)


def _fishing_placements(state):
    return [a for a in legal_actions(state)
            if isinstance(a, PlaceWorker) and a.space == "fishing"]


def test_unpayable_toll_forbids_the_placement():
    s = with_resources(_fn_state(), 0, food=0)
    assert not _fishing_placements(s)              # no food, no cookables
    s2 = with_resources(_fn_state(owner=0), 0, food=0)
    assert _fishing_placements(s2)                 # the OWNER is never gated


def test_toll_paid_before_the_sweep_and_flags_the_deposit():
    s = with_resources(_fn_state(), 0, food=1)
    owner_food = s.players[1].resources.food
    s = step(s, _fishing_placements(s)[0])
    assert s.players[1].resources.food == owner_food + 1
    assert s.players[0].resources.food == 3        # -1 toll, +3 swept
    assert s.players[1].card_state.get("fishing_net:board_toll_paid")


def test_food_short_raise_path():
    s = with_resources(_fn_state(), 0, food=0)
    s = with_animals(s, 0, sheep=1)
    s = with_majors(s, owner_by_idx={0: 0})        # Fireplace: sheep cookable
    placements = _fishing_placements(s)
    assert placements                              # liquidation-aware gate
    owner_food = s.players[1].resources.food
    s = step(s, placements[0])
    assert isinstance(s.pending_stack[-1], PendingFoodPayment)
    bundles = [a for a in legal_actions(s) if isinstance(a, CommitFoodPayment)]
    s = step(s, bundles[0])                        # cook, resume, pay, sweep
    assert s.players[1].resources.food == owner_food + 1
    assert get_space(s.board, "fishing").accumulated_amount == 0


def test_owner_use_sets_no_deposit_flag():
    s = with_resources(_fn_state(owner=0), 0, food=0)
    s = step(s, _fishing_placements(s)[0])
    assert not s.players[0].card_state.get("fishing_net:board_toll_paid", False)
