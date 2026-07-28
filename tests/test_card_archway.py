"""Archway (D51) — the for-all park-then-relocate card space (rulings 86 + the
resolved after_work × last-use question: Straw Hat's coupling, verbatim)."""
from __future__ import annotations

import agricola.cards  # noqa: F401

from agricola.actions import FireTrigger, PlaceWorker, Proceed
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingHarvestWindow
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import with_current_player, with_majors, with_resources, \
    with_space

POOL = CardPool(occupations=tuple(f"o{i}" for i in range(20)),
                minors=tuple(f"m{i}" for i in range(20)))
CARD_ID = "archway"


def _edit(state, idx, **ch):
    p = fast_replace(state.players[idx], **ch)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _base(owner=1):
    s, _env = setup_env(11, card_pool=POOL)
    s = with_current_player(s, 0)
    for i in (0, 1):
        s = _edit(s, i, hand_occupations=frozenset(), hand_minors=frozenset())
    p = s.players[owner]
    return _edit(s, owner, minor_improvements=p.minor_improvements | {CARD_ID})


def _fab_board(state, idx, space_id):
    sp = get_space(state.board, space_id)
    workers = tuple(w + (1 if j == idx else 0) for j, w in enumerate(sp.workers))
    state = with_space(state, space_id, workers=workers)
    p = state.players[idx]
    return _edit(state, idx, people_home=p.people_home - 1,
                 placements_this_round=p.placements_this_round + 1,
                 standing_workers=p.standing_workers
                 + ((p.placements_this_round + 1, space_id),))


def _fab_parked(state, idx):
    """P`idx`'s person parked on Archway (marker + ledger + bookkeeping)."""
    p = state.players[idx]
    return _edit(state, idx, people_home=p.people_home - 1,
                 placements_this_round=p.placements_this_round + 1,
                 standing_workers=p.standing_workers
                 + ((p.placements_this_round + 1, f"card:{CARD_ID}"),),
                 card_state=p.card_state.set(f"card_space_worker:{CARD_ID}", 1))


def _drained(owner=1, parked_idx=0, foreclosed=False):
    s = _base(owner=owner)
    s = fast_replace(s, phase=Phase.WORK, round_number=4,
                     starting_player=0, current_player=1)
    s = _fab_parked(s, parked_idx)
    s = _fab_board(s, parked_idx, "day_laborer")
    s = _fab_board(s, 1 - parked_idx, "clay_pit")
    s = _fab_board(s, 1 - parked_idx, "reed_bank")
    if foreclosed:
        s = _edit(s, parked_idx, last_use_committed=True)
    assert all(p.people_home == 0 for p in s.players)
    return s


def _arch_fires(state):
    return [a for a in legal_actions(state)
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID]


def test_park_grants_food_to_either_player():
    s = _base(owner=1)                                  # P0 is the NON-owner
    food = s.players[0].resources.food
    s = step(s, PlaceWorker(space="card:archway"))      # for-all, no toll
    s = step(s, Proceed())
    assert s.players[0].resources.food == food + 1
    from agricola.cards.card_spaces import card_space_worker_count
    assert card_space_worker_count(s.players[0], CARD_ID) == 1   # parked


def test_after_work_offers_the_move_to_the_parked_player():
    s = _advance_until_decision(_drained())
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "after_work" and top.player_idx == 0
    variants = {f.variant for f in _arch_fires(s)}
    assert "forest" in variants                         # unoccupied + legal
    assert "clay_pit" not in variants                   # occupied


def test_foreclosed_by_a_committed_last_use():
    s = _advance_until_decision(_drained(foreclosed=True))
    assert not any(isinstance(f, PendingHarvestWindow) and f.window_id == "after_work"
                   for f in s.pending_stack)            # no move: no window at all


def test_move_takes_the_destination_and_reopens_steam_machine():
    s = _drained()
    p0 = s.players[0]
    s = _edit(s, 0, minor_improvements=p0.minor_improvements | {"steam_machine"})
    s = with_majors(s, owner_by_idx={0: 0})
    s = with_resources(s, 0, grain=1)
    s = _advance_until_decision(s)
    wood_on_forest = get_space(s.board, "forest").accumulated.wood

    s = step(s, FireTrigger(card_id=CARD_ID, variant="forest"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingActionSpace) and top.space_id == "forest"
    s = step(s, Proceed())
    p = s.players[0]
    assert p.resources.wood == wood_on_forest           # the take resolved
    assert (1, "forest") in p.standing_workers          # number PRESERVED
    from agricola.cards.card_spaces import card_space_worker_count
    assert card_space_worker_count(p, CARD_ID) == 0     # off the card
    # The ruled coupling: the relocated last use re-opens Steam Machine.
    sm = [a for a in legal_actions(s)
          if isinstance(a, FireTrigger) and a.card_id == "steam_machine"]
    assert sm
    s = step(s, sm[0])
    assert s.players[0].last_use_committed


def test_declining_sends_the_person_home_at_the_reset():
    s = _advance_until_decision(_drained())
    s = step(s, Proceed())                              # decline the move
    s = _advance_until_decision(s)
    p = s.players[0]
    assert p.people_home == p.people_total              # went home with the reset
    from agricola.cards.card_spaces import card_space_worker_count
    assert card_space_worker_count(p, CARD_ID) == 0
