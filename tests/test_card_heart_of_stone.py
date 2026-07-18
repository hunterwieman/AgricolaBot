"""Tests for Heart of Stone (minor improvement, C21; Corbarius Expansion).

Card text (verbatim): "Each time a "Quarry" accumulation space is revealed, if
you have room in your house, you can immediately take a "Family Growth" action
without placing a person."
Cost: 4 Food. No prerequisite / VPs / passing.

The effect rides the preparation ladder's ``reveal`` window (ruling 54,
2026-07-14 as revised): an OPTIONAL Family-Growth trigger gated on "a "Quarry"
(stone accumulation space) was revealed by THIS round's preparation" —
``revealed_round == state.round_number`` (user decision 2026-07-15; at the
``reveal`` window the round increment has already run) — AND the printed "room
in your house" condition (a meeple left in supply AND a free room). Firing
pushes the card-granted family-growth primitive
(``PendingFamilyGrowth(place_on_space=False)``, Group A1 ruling 2026-07-03), so
"without placing a person" is literal: the newborn occupies NO action space.
"Immediately" adds nothing (ruling 66, 2026-07-17). The window host's Proceed is
the decline.

These tests drive a REAL preparation: a state paused at the round-card reveal
(``PendingReveal`` up), stepped with ``RevealCard(card="western_quarry")`` (or
``eastern_quarry``), letting the ladder walk run — mirroring the reveal idiom of
tests/test_card_task_artisan.py (the sibling ``reveal``-window card).
"""
from __future__ import annotations

import agricola.cards.heart_of_stone  # noqa: F401  (registers the card)

from agricola.actions import (
    ChooseSubAction,
    CommitFamilyGrowth,
    FireTrigger,
    PlaceWorker,
    Proceed,
    RevealCard,
    Stop,
)
from agricola.cards.specs import MINORS, OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, TRIGGERS
from agricola.constants import CellType, STAGE_CARDS, Phase, stage_of_round
from agricola.engine import _advance_until_decision, step
from agricola.legality import _num_rooms, legal_actions
from agricola.pending import PendingFamilyGrowth, PendingHarvestWindow, PendingReveal
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, get_space, with_space
from tests.test_utils import sole_play_minor

CARD_ID = "heart_of_stone"

# Cells to add ROOMs into (the default farm already has rooms at (1,0),(2,0)).
_EXTRA_ROOM_CELLS = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edit_player(state, idx, **changes):
    p = fast_replace(state.players[idx], **changes)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return _edit_player(state, idx, minor_improvements=p.minor_improvements | {card_id})


def _give_hand_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return _edit_player(state, idx, hand_minors=p.hand_minors | {card_id})


def _add_rooms(state, idx, n):
    """Add `n` extra ROOM cells to player `idx`'s farm (so `_num_rooms` grows by
    n above the default 2), without changing people_total."""
    p = state.players[idx]
    grid = p.farmyard.grid
    overrides = {(r, c): Cell(cell_type=CellType.ROOM)
                 for (r, c) in _EXTRA_ROOM_CELLS[:n]}
    new_grid = tuple(
        tuple(overrides.get((r, c), grid[r][c]) for c in range(5))
        for r in range(3))
    new_farmyard = fast_replace(p.farmyard, grid=new_grid)
    return _edit_player(state, idx, farmyard=new_farmyard)


def _mark_revealed(state, card_id, round_number):
    sp = get_space(state.board, card_id)
    return fast_replace(state, board=with_space(state.board, card_id, fast_replace(
        sp, revealed=True, revealed_round=round_number)))


def _reveal_pause(state, prev_round, pinned=None):
    """Advance `state` to the reveal nature pause for entering round
    `prev_round + 1`: mark stage cards revealed for rounds 2..prev_round (any
    `pinned` {round: card_id} first, generic fillers for the rest — setup
    already revealed round 1's card), then run the preparation walk, which
    parks at the PendingReveal (mirrors test_card_task_artisan._reveal_pause)."""
    pinned = pinned or {}
    for r, cid in pinned.items():
        state = _mark_revealed(state, cid, r)
    for r in range(2, prev_round + 1):
        if r in pinned:
            continue
        stage = stage_of_round(r)
        cid = next(c for c in STAGE_CARDS[stage]
                   if not get_space(state.board, c).revealed)
        state = _mark_revealed(state, cid, r)
    state = fast_replace(state, phase=Phase.PREPARATION, round_number=prev_round)
    state = _advance_until_decision(state)
    assert isinstance(state.pending_stack[-1], PendingReveal)
    return state


def _owner_with_room_at_reveal(seat=0, *, prev_round=4):
    """Player `seat` owns Heart of Stone and has a free room (a 3rd ROOM, so
    people_total(2) < num_rooms(3)), paused at the reveal for the next round."""
    s = _own_minor(setup(0), seat)
    s = _add_rooms(s, seat, 1)
    assert s.players[seat].people_total < _num_rooms(s.players[seat])
    return _reveal_pause(s, prev_round=prev_round)


def _board_workers(state):
    """Total meeples sitting on action spaces (workers[0] is the count)."""
    return sum(sp.workers[0] for sp in state.board.action_spaces)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor_reveal_trigger():
    assert CARD_ID in MINORS
    assert CARD_ID not in OCCUPATIONS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(food=4)
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.prereq is None
    # Optional trigger on the `reveal` window — a TRIGGER, never an AUTO.
    assert CARD_ID in {e.card_id for e in TRIGGERS.get("reveal", ())}
    assert CARD_ID not in {e.card_id for e in AUTO_EFFECTS.get("reveal", ())}


# ---------------------------------------------------------------------------
# The recurring effect via the REAL preparation walk
# ---------------------------------------------------------------------------

def test_quarry_reveal_offers_growth():
    s = _owner_with_room_at_reveal(seat=0)
    out = step(s, RevealCard(card="western_quarry"))
    assert out.round_number == 5
    assert out.phase is Phase.PREPARATION           # walk paused at the window
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "reveal" and top.player_idx == 0
    la = legal_actions(out)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Proceed() in la                          # optional → declinable


def test_eastern_quarry_also_triggers():
    # eastern_quarry is a stage-4 card (rounds 10-11); reveal it entering round 10.
    s = _owner_with_room_at_reveal(seat=0, prev_round=9)
    out = step(s, RevealCard(card="eastern_quarry"))
    assert out.round_number == 10
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "reveal" and top.player_idx == 0
    assert FireTrigger(card_id=CARD_ID) in legal_actions(out)


def test_fire_grows_family_without_placing_a_person():
    s = _owner_with_room_at_reveal(seat=0)
    s = step(s, RevealCard(card="western_quarry"))
    p_before = s.players[0]
    board_before = s.board
    workers_before = _board_workers(s)

    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFamilyGrowth)
    assert top.place_on_space is False              # "without placing a person"
    assert top.initiated_by_id == "card:heart_of_stone"
    assert top.player_idx == 0

    s = step(s, CommitFamilyGrowth())
    p_after = s.players[0]
    # The newborn: people_total/newborns up by one, a meeple leaves the supply.
    assert p_after.people_total == p_before.people_total + 1
    assert p_after.newborns == p_before.newborns + 1
    assert p_after.workers_in_supply == p_before.workers_in_supply - 1
    # No board placement: the growth touched no action space.
    assert s.board == board_before
    assert _board_workers(s) == workers_before == 0

    # After-phase of the growth pops on Stop; back at the window host the trigger
    # is spent (once per window), Proceed completes the ladder to WORK.
    s = step(s, Stop())
    top = s.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow) and top.window_id == "reveal"
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la
    assert Proceed() in la
    s = step(s, Proceed())
    assert s.phase is Phase.WORK
    assert s.pending_stack == ()


def test_owner_seat_one_also_offered():
    s = _owner_with_room_at_reveal(seat=1)
    out = step(s, RevealCard(card="western_quarry"))
    top = out.pending_stack[-1]
    assert isinstance(top, PendingHarvestWindow)
    assert top.window_id == "reveal" and top.player_idx == 1
    assert FireTrigger(card_id=CARD_ID) in legal_actions(out)


def test_decline_via_proceed_grows_nothing():
    s = _owner_with_room_at_reveal(seat=0)
    people_before = s.players[0].people_total
    supply_before = s.players[0].workers_in_supply
    s = step(s, RevealCard(card="western_quarry"))
    s = step(s, Proceed())                          # decline the growth
    assert s.phase is Phase.WORK
    assert all(not isinstance(f, PendingFamilyGrowth) for f in s.pending_stack)
    assert s.players[0].people_total == people_before
    assert s.players[0].workers_in_supply == supply_before


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_non_quarry_reveal_offers_nothing():
    s = _owner_with_room_at_reveal(seat=0)
    people_before = s.players[0].people_total
    out = step(s, RevealCard(card="basic_wish_for_children"))   # not a quarry
    assert out.round_number == 5
    assert out.phase is Phase.WORK
    assert out.pending_stack == ()
    assert out.players[0].people_total == people_before


def test_no_room_not_offered():
    # Default farm: 2 people in 2 rooms → people_total(2) < num_rooms(2) is False.
    s = _own_minor(setup(0), 0)                     # no extra room
    assert s.players[0].people_total == _num_rooms(s.players[0])
    s = _reveal_pause(s, prev_round=4)
    out = step(s, RevealCard(card="western_quarry"))
    assert out.phase is Phase.WORK                  # no frame surfaced
    assert out.pending_stack == ()


def test_full_house_five_people_not_offered():
    # Five people (the family cap) with room to spare (6 rooms): the room clause
    # passes but the family cap `workers_in_supply > 0` fails → not offered.
    s = _own_minor(setup(0), 0)
    s = _add_rooms(s, 0, 4)                          # 2 default + 4 = 6 rooms
    s = _edit_player(s, 0, people_total=5, workers_in_supply=0)
    assert s.players[0].people_total < _num_rooms(s.players[0])   # room clause OK
    s = _reveal_pause(s, prev_round=4)
    out = step(s, RevealCard(card="western_quarry"))
    assert out.phase is Phase.WORK
    assert out.pending_stack == ()


def test_quarry_from_earlier_round_does_not_refire():
    # western_quarry appeared in round 5 (revealed_round=5); entering round 6
    # reveals a non-quarry — revealed_round(5) < round_number(6), so nothing.
    s = _own_minor(setup(0), 0)
    s = _add_rooms(s, 0, 1)                          # room to spare
    s = _reveal_pause(s, prev_round=5, pinned={5: "western_quarry"})
    out = step(s, RevealCard(card="house_redevelopment"))
    assert out.round_number == 6
    assert out.phase is Phase.WORK
    assert out.pending_stack == ()


def test_hand_only_is_inert():
    # The card sitting UNPLAYED in the hand fires nothing on a quarry reveal.
    s = _give_hand_minor(setup(0), 0)               # in hand, not played
    s = _add_rooms(s, 0, 1)
    s = _reveal_pause(s, prev_round=4)
    people_before = s.players[0].people_total
    out = step(s, RevealCard(card="western_quarry"))
    assert out.phase is Phase.WORK
    assert out.pending_stack == ()
    assert out.players[0].people_total == people_before


# ---------------------------------------------------------------------------
# Real play-via-a-minor flow (cards mode) — the 4-food cost is paid here
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def test_played_via_minor_action_costs_4_food():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))
    cs = _edit_player(cs, cp, resources=cs.players[cp].resources + Resources(food=4))
    food0 = cs.players[cp].resources.food

    # Play Heart of Stone via Meeting Place's play-a-minor branch.
    cs = step(cs, PlaceWorker(space="meeting_place"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    assert CARD_ID in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.food == food0 - 4    # 4 Food paid at play
