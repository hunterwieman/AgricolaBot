import agricola.cards.bed_maker  # noqa: F401  (registers the card — not yet wired into cards/__init__.py)
"""Tests for Bed Maker (occupation, deck A #93; Artifex Expansion).

Card text: "Each time you add rooms to your house, you can also pay 1 wood and
1 grain to immediately get a "Family Growth with Room Only" action."
Clarification: "This card allows exactly 1 growth action regardless of how many
rooms are built."

User ruling 2026-07-21 (ruling 74): the trigger fires in the
``after_build_rooms`` window (deliberate override of the bare-"each time"
before default — the room gate reads post-build state). Standing ruling: the
card-granted growth is ``PendingFamilyGrowth(place_on_space=False)`` (no board
placement). Flagged driver reading: fires on ANY rooms addition, regardless of
``build_rooms_action`` (Cottager's granted room build qualifies too).
"""
import agricola.cards.cottager  # noqa: F401  (the non-named-action rooms addition)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    CommitFamilyGrowth,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, CARDS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBuildRooms, PendingFamilyGrowth, PendingFarmExpansion
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import Cell

from tests.factories import (
    with_current_player,
    with_grid,
    with_people,
    with_resources,
)

CARD_ID = "bed_maker"

# Dummy pools — the tests inject ownership directly; the pool only feeds the
# CARDS-mode hand deal.
_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers (the family_friendly_home test idioms, CARDS mode)
# ---------------------------------------------------------------------------

def _replace_player(state, idx, p):
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_occupation(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return _replace_player(
        state, idx, fast_replace(p, occupations=p.occupations | {card_id}))


def _hand_occupation(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return _replace_player(
        state, idx, fast_replace(p, hand_occupations=p.hand_occupations | {card_id}))


def _base_state(*, owner=0, extra_rooms=0, wood=15, reed=6, grain=2, played=True):
    """CARDS-mode round-1 WORK state; `owner` active with Bed Maker played (or
    in hand if not `played`); the base farm (2 rooms at (1,0)/(2,0), 2 people)
    plus `extra_rooms` extra ROOM cells chained along row 0; resources set to
    exactly (wood, reed, grain)."""
    state, _env = setup_env(seed=0, card_pool=_POOL)
    state = with_current_player(state, owner)
    if extra_rooms:
        state = with_grid(state, owner, {
            (0, c): Cell(cell_type=CellType.ROOM) for c in range(extra_rooms)})
    state = with_resources(state, owner, wood=wood, reed=reed, grain=grain)
    if played:
        state = _own_occupation(state, owner)
    else:
        state = _hand_occupation(state, owner)
    return state


def _enter_build_rooms(state):
    """Drive the real Farm Expansion flow to the Build Rooms host push."""
    state = step(state, PlaceWorker(space="farm_expansion"))
    assert isinstance(state.pending_stack[-1], PendingFarmExpansion)
    state = step(state, ChooseSubAction(name="build_rooms"))
    assert isinstance(state.pending_stack[-1], PendingBuildRooms)
    return state


def _commit_any_room(state):
    build = next(a for a in legal_actions(state) if isinstance(a, CommitBuildRoom))
    return step(state, build)


def _num_rooms(state, idx):
    g = state.players[idx].farmyard.grid
    return sum(1 for r in range(3) for c in range(5)
               if g[r][c].cell_type == CellType.ROOM)


def _walk_out(state):
    """Exit every open frame (Proceed/Stop) until the turn ends."""
    while state.pending_stack:
        la = legal_actions(state)
        if Stop() in la:
            state = step(state, Stop())
        elif Proceed() in la:
            state = step(state, Proceed())
        else:
            raise AssertionError(f"cannot exit frame: {la}")
    return state


def _to_after_window(state):
    """Build one room, then Proceed — opening the after-window (ruling 74's
    instant)."""
    state = _commit_any_room(state)
    state = step(state, Proceed())
    top = state.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms) and top.phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration (subset checks, never exact-set)
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    # On-play is a no-op (the effect is purely recurring).
    state, _env = setup_env(seed=0, card_pool=_POOL)
    assert OCCUPATIONS[CARD_ID].on_play(state, 0) == state
    # An optional (never mandatory) trigger on after_build_rooms (ruling 74) —
    # and NOT on the before-window, and not an automatic effect.
    assert CARD_ID in CARDS
    assert CARDS[CARD_ID].mandatory is False
    assert any(e.card_id == CARD_ID for e in TRIGGERS["after_build_rooms"])
    assert not any(e.card_id == CARD_ID
                   for e in TRIGGERS.get("before_build_rooms", ()))
    for event, entries in AUTO_EFFECTS.items():
        assert not any(e.card_id == CARD_ID for e in entries), event


# ---------------------------------------------------------------------------
# The real engine flow: after-window only (ruling 74), debit, newborn off-board
# ---------------------------------------------------------------------------

def test_fires_in_after_window_full_flow():
    s = _base_state()                     # 2 rooms, 2 people; wood 15, grain 2
    s = _enter_build_rooms(s)
    # Ruling 74: NOT offered in the before-window ...
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _commit_any_room(s)               # 3 rooms now
    # ... nor between room commits (Build Rooms is ONE action).
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = step(s, Proceed())                # the work-complete flip
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)

    wood_before = s.players[0].resources.wood
    grain_before = s.players[0].resources.grain
    s = step(s, FireTrigger(card_id=CARD_ID))
    # The debit: exactly 1 wood + 1 grain.
    assert s.players[0].resources.wood == wood_before - 1
    assert s.players[0].resources.grain == grain_before - 1
    # The growth primitive: card-granted, no board placement.
    top = s.pending_stack[-1]
    assert isinstance(top, PendingFamilyGrowth)
    assert top.place_on_space is False
    assert top.initiated_by_id == f"card:{CARD_ID}"
    assert top.player_idx == 0

    home_before = s.players[0].people_home
    workers_before = tuple(sp.workers for sp in s.board.action_spaces)
    assert legal_actions(s) == [CommitFamilyGrowth()]
    s = step(s, CommitFamilyGrowth())
    p = s.players[0]
    assert p.people_total == 3
    assert p.newborns == 1
    # The newborn occupies NO action space: people_home + board untouched.
    assert p.people_home == home_before
    assert tuple(sp.workers for sp in s.board.action_spaces) == workers_before

    s = step(s, Stop())                   # pop the growth frame
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms) and top.phase == "after"
    # Latched for the rest of the host visit.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _walk_out(s)
    assert s.players[0].people_total == 3
    assert s.players[0].newborns == 1


# ---------------------------------------------------------------------------
# Once per action (the printed clarification): 2 rooms, 1 fire
# ---------------------------------------------------------------------------

def test_once_per_action_two_rooms():
    s = _base_state(grain=3)              # wood 15 covers 2 rooms + the fire
    s = _enter_build_rooms(s)
    s = _commit_any_room(s)
    s = _commit_any_room(s)               # 4 rooms, 2 people — ONE action
    s = step(s, Proceed())
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitFamilyGrowth())
    s = step(s, Stop())                   # back at the after-phase host
    # Every eligibility clause still holds (4 rooms > 3 people, wood + grain
    # on hand, supply left) — ONLY the once-per-action latch blocks a refire.
    p = s.players[0]
    assert _num_rooms(s, 0) == 4 and p.people_total == 3
    assert p.resources.wood >= 1 and p.resources.grain >= 1
    assert p.workers_in_supply > 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _walk_out(s)
    assert s.players[0].people_total == 3


# ---------------------------------------------------------------------------
# Eligibility boundaries (all measured at the after-window)
# ---------------------------------------------------------------------------

def test_no_wood_not_offered():
    # Exactly the room's price: after the build, wood == 0.
    s = _base_state(wood=5, reed=2, grain=1)
    s = _enter_build_rooms(s)
    s = _to_after_window(s)
    assert s.players[0].resources.wood == 0
    assert s.players[0].resources.grain == 1
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_no_grain_not_offered():
    s = _base_state(grain=0)
    s = _enter_build_rooms(s)
    s = _to_after_window(s)
    assert s.players[0].resources.wood >= 1
    assert s.players[0].resources.grain == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_rooms_equal_people_after_build_not_offered():
    # 2 rooms, 3 people; build 1 room -> 3 rooms == 3 people post-build: the
    # growth's room gate (rooms > people, read on post-build state) fails.
    s = _base_state()
    s = with_people(s, 0, total=3, home=3)
    s = _enter_build_rooms(s)
    s = _to_after_window(s)
    assert _num_rooms(s, 0) == 3 and s.players[0].people_total == 3
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_at_family_cap_not_offered():
    # 6 rooms, 5 people (supply == 0): rooms > people holds after the build and
    # wood/grain are on hand, but no meeple remains — the growth is illegal.
    s = _base_state(extra_rooms=4)
    s = with_people(s, 0, total=5, home=5)
    s = _enter_build_rooms(s)
    s = _to_after_window(s)
    p = s.players[0]
    assert _num_rooms(s, 0) == 7 and p.people_total == 5
    assert p.workers_in_supply == 0
    assert p.resources.wood >= 1 and p.resources.grain >= 1
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Decline path: Stop without firing — no debit, no newborn
# ---------------------------------------------------------------------------

def test_decline_via_stop():
    s = _base_state()
    s = _enter_build_rooms(s)
    s = _to_after_window(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    wood_before = s.players[0].resources.wood
    grain_before = s.players[0].resources.grain
    s = step(s, Stop())                   # decline: exit without firing
    s = _walk_out(s)
    p = s.players[0]
    assert p.resources.wood == wood_before
    assert p.resources.grain == grain_before
    assert p.people_total == 2 and p.newborns == 0


# ---------------------------------------------------------------------------
# Any rooms addition (flagged driver reading): Cottager's granted build fires
# ---------------------------------------------------------------------------

def test_fires_on_cottager_granted_build():
    s = _base_state()
    s = _own_occupation(s, 0, "cottager")
    s = step(s, PlaceWorker(space="day_laborer"))
    s = step(s, FireTrigger(card_id="cottager", variant="room"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms)
    assert top.build_rooms_action is False   # NOT the named action
    s = _commit_any_room(s)
    s = step(s, Proceed())
    # The driver reading: any rooms addition qualifies.
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitFamilyGrowth())
    assert s.players[0].people_total == 3
    assert s.players[0].newborns == 1


# ---------------------------------------------------------------------------
# Ownership boundaries: hand-only inert, opponent's build fires nothing
# ---------------------------------------------------------------------------

def test_hand_only_is_inert():
    s = _base_state(played=False)         # in hand, never played
    s = _enter_build_rooms(s)
    s = _to_after_window(s)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_opponent_build_fires_nothing():
    s = _base_state(owner=0)              # P0 owns the card
    s = with_current_player(s, 1)
    # Give P1 (the builder) everything the eligibility would need — only
    # ownership must block the fire.
    s = with_resources(s, 1, wood=15, reed=6, grain=2)
    s = _enter_build_rooms(s)
    s = _to_after_window(s)
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _walk_out(s)
    assert s.players[0].people_total == 2 and s.players[1].people_total == 2
