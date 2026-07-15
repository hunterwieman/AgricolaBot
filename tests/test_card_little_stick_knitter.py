"""Tests for Little Stick Knitter (occupation, B92; Bubulcus Expansion).

Card text: "From Round 5 on, each time you use the "sheep Market" accumulation
space, you can also take a "Family Growth with Room Only" action."

An OPTIONAL `before_action_space` FireTrigger (user confirmation 2026-07-14: the
growth is an option, never a mandatory push) on the non-atomic Sheep Market host,
eligible from round 5 with the Room Only gate (people_total < 5 AND a free room).
Firing pushes the card-granted family-growth primitive
(`PendingFamilyGrowth(place_on_space=False)`, Group A1 ruling 2026-07-03: the
newborn occupies NO action space).
"""
import agricola.cards.little_stick_knitter  # noqa: F401  (registers the card)

from agricola.actions import (
    CommitAccommodate,
    CommitFamilyGrowth,
    FireTrigger,
    PlaceWorker,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import CARDS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingFamilyGrowth, PendingSheepMarket
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import (
    with_current_player,
    with_grid,
    with_people,
    with_resources,
    with_round,
    with_space,
)

CARD_ID = "little_stick_knitter"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_occupation(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _hand_occupation(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, hand_occupations=p.hand_occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _market_state(*, owner=0, round_number=5, accumulated=1, spare_room=True,
                  played=True):
    """`owner` is active with the card played (or in hand if not `played`);
    the Sheep Market (a Stage-1 space) is revealed and stocked; a third ROOM
    at (0, 0) provides the free room the growth needs (2 people, 3 rooms)."""
    state = setup(seed=0)
    state = with_current_player(state, owner)
    state = with_round(state, round_number)
    state = with_space(state, "sheep_market", revealed=True,
                       accumulated_amount=accumulated)
    if spare_room:
        state = with_grid(state, owner, {(0, 0): Cell(cell_type=CellType.ROOM)})
    if played:
        state = _own_occupation(state, owner)
    else:
        state = _hand_occupation(state, owner)
    return state


def _drive_accommodate(state):
    """Take the market's animals (keep maximum), then pop the market host frame."""
    keep = max(
        (a for a in legal_actions(state) if isinstance(a, CommitAccommodate)),
        key=lambda a: getattr(a, "sheep", 0),
    )
    state = step(state, keep)
    if isinstance(state.pending_stack[-1], PendingSheepMarket):
        assert legal_actions(state) == [Stop()]
        state = step(state, Stop())
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in CARDS
    assert any(e.card_id == CARD_ID for e in TRIGGERS["before_action_space"])
    # Optional trigger (user confirmation 2026-07-14), never mandatory.
    assert CARDS[CARD_ID].mandatory is False
    # On-play is a no-op (the effect is purely recurring).
    state = setup(seed=0)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) == state


# ---------------------------------------------------------------------------
# "From Round 5 on" — the round gate
# ---------------------------------------------------------------------------

def test_not_offered_before_round_5():
    s = _market_state(round_number=4)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert isinstance(s.pending_stack[-1], PendingSheepMarket)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_offered_at_round_5_with_room():
    s = _market_state(round_number=5)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_offered_in_later_rounds():
    s = _market_state(round_number=11)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


# ---------------------------------------------------------------------------
# "with Room Only" — the room / family-cap gate
# ---------------------------------------------------------------------------

def test_not_offered_without_spare_room():
    # 2 rooms, 2 people: no free room -> not offered.
    s = _market_state(round_number=5, spare_room=False)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_at_five_people():
    # 6 rooms but the 5-person family cap is reached -> not offered.
    s = _market_state(round_number=5)
    s = with_grid(s, 0, {(0, c): Cell(cell_type=CellType.ROOM)
                         for c in range(1, 4)})   # (0,0) already a room -> 6 rooms
    s = with_people(s, 0, total=5, home=5)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Firing: the growth is real, and the newborn occupies no action space
# ---------------------------------------------------------------------------

def test_fire_grows_family_and_market_still_resolves():
    s = _market_state(round_number=5, accumulated=1)
    s = step(s, PlaceWorker(space="sheep_market"))
    workers_after_placement = tuple(sp.workers for sp in s.board.action_spaces)

    s = step(s, FireTrigger(card_id=CARD_ID))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFamilyGrowth)
    assert top.place_on_space is False
    assert top.initiated_by_id == f"card:{CARD_ID}"
    assert top.player_idx == 0

    assert legal_actions(s) == [CommitFamilyGrowth()]
    s = step(s, CommitFamilyGrowth())
    assert s.players[0].people_total == 3
    assert s.players[0].newborns == 1
    # The newborn occupies NO action space (Group A1 ruling 2026-07-03).
    assert tuple(sp.workers for sp in s.board.action_spaces) == workers_after_placement

    s = step(s, Stop())   # pop the growth frame -> back to the market host
    assert isinstance(s.pending_stack[-1], PendingSheepMarket)

    # The market's own take still resolves after the growth.
    s = _drive_accommodate(s)
    assert not s.pending_stack
    assert s.players[0].animals.sheep == 1
    assert s.players[0].people_total == 3


# ---------------------------------------------------------------------------
# Once per use
# ---------------------------------------------------------------------------

def test_once_per_use():
    s = _market_state(round_number=5)
    s = step(s, PlaceWorker(space="sheep_market"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitFamilyGrowth())
    s = step(s, Stop())
    # Back at the market host: not offered again on this same use. (Here the
    # room gate also fails at 3 people / 3 rooms; the next test isolates the
    # latch with the room gate still passing.)
    assert isinstance(s.pending_stack[-1], PendingSheepMarket)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_once_per_use_with_room_still_free():
    # Two spare rooms, so the room gate still holds after one growth: the
    # latch alone must block a second fire on the same use.
    s = _market_state(round_number=5)
    s = with_grid(s, 0, {(0, 1): Cell(cell_type=CellType.ROOM)})   # 4 rooms
    s = step(s, PlaceWorker(space="sheep_market"))
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitFamilyGrowth())
    s = step(s, Stop())
    p = s.players[0]
    assert p.people_total == 3 and p.people_total < 4   # gate would still pass
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Optionality: declinable (take the sheep without firing)
# ---------------------------------------------------------------------------

def test_grant_is_declinable():
    s = _market_state(round_number=5, accumulated=1)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    # Decline by going straight to the market's accommodation.
    s = _drive_accommodate(s)
    assert not s.pending_stack
    assert s.players[0].people_total == 2
    assert s.players[0].newborns == 0
    assert s.players[0].animals.sheep == 1


# ---------------------------------------------------------------------------
# Eligibility boundaries: owner-only, sheep-market-only, played-only
# ---------------------------------------------------------------------------

def test_opponent_use_offers_nothing():
    # P0 owns the card; P1 (active) uses the Sheep Market -> no trigger.
    s = _market_state(owner=0, round_number=5)
    s = with_current_player(s, 1)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert isinstance(s.pending_stack[-1], PendingSheepMarket)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_not_offered_on_other_markets():
    s = _market_state(round_number=5)
    s = with_space(s, "pig_market", revealed=True, accumulated_amount=1)
    s = step(s, PlaceWorker(space="pig_market"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_hand_only_is_inert():
    # The card sits in the owner's HAND (never played) -> no trigger.
    s = _market_state(round_number=5, played=False)
    s = step(s, PlaceWorker(space="sheep_market"))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
