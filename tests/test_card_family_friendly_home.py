"""Tests for Family Friendly Home (minor improvement, deck A #21; Base Revised).

Card text: "Each time you take a "Build Rooms" action while having more rooms
than people already, you also get a "Family Growth" action and 1 food."
Clarification: "This card allows exactly 1 growth action regardless of how many
rooms are built."

User rulings (2026-07-20): the rooms>people measure occurs BEFORE the build
rooms action (before the first room is built); the food is given whether or not
the family growth is accepted; "take a 'Build Rooms' action" is the NAMED
action only (``PendingBuildRooms.build_rooms_action`` — Cottager's granted
room build does not count).

Two registrations on ``before_build_rooms``: an automatic +1 food at the host
push, and an optional FireTrigger that pushes the card-granted family-growth
primitive (``PendingFamilyGrowth(place_on_space=False)``, Group A1).
"""
import agricola.cards.family_friendly_home  # noqa: F401  (registers the card)
import agricola.cards.cottager  # noqa: F401  (the named-action contrast case)

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    CommitFamilyGrowth,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS, CARDS, TRIGGERS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingBuildRooms, PendingFamilyGrowth, PendingFarmExpansion
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import setup
from agricola.state import Cell

from tests.factories import (
    with_current_player,
    with_grid,
    with_people,
    with_resources,
)

CARD_ID = "family_friendly_home"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _replace_player(state, idx, p):
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _own_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return _replace_player(
        state, idx, fast_replace(p, minor_improvements=p.minor_improvements | {card_id}))


def _hand_minor(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    return _replace_player(
        state, idx, fast_replace(p, hand_minors=p.hand_minors | {card_id}))


def _own_occupation(state, idx, card_id):
    p = state.players[idx]
    return _replace_player(
        state, idx, fast_replace(p, occupations=p.occupations | {card_id}))


def _base_state(*, owner=0, extra_rooms=1, played=True):
    """`owner` active with the card played (or in hand if not `played`); the
    base farm (2 rooms at (1,0)/(2,0), 2 people) plus `extra_rooms` extra ROOM
    cells chained along row 0 — so the default (1) gives 3 rooms > 2 people;
    0 gives rooms == people. Wood + reed cover several room builds."""
    state = setup(seed=0)
    state = with_current_player(state, owner)
    state = with_grid(state, owner, {
        (0, c): Cell(cell_type=CellType.ROOM) for c in range(extra_rooms)})
    state = with_resources(state, owner, wood=15, reed=6)
    if played:
        state = _own_minor(state, owner)
    else:
        state = _hand_minor(state, owner)
    return state


def _enter_build_rooms(state):
    """Drive the real named-action flow: Farm Expansion, then the Build Rooms
    category (the host push that opens the before-window)."""
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


# ---------------------------------------------------------------------------
# Registration (subset checks, never exact-set)
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.min_occupations == 1      # prereq "1 Occupation"
    assert spec.cost == Cost()            # no cost
    assert spec.vps == 0                  # no printed VP
    # The growth trigger: optional (never mandatory), on before_build_rooms.
    assert CARD_ID in CARDS
    assert CARDS[CARD_ID].mandatory is False
    assert any(e.card_id == CARD_ID for e in TRIGGERS["before_build_rooms"])
    # The food: an automatic effect on the same before-window.
    assert any(e.card_id == CARD_ID for e in AUTO_EFFECTS["before_build_rooms"])
    # On-play is a no-op (the effect is purely recurring).
    state = setup(seed=0)
    assert spec.on_play(state, 0) == state


# ---------------------------------------------------------------------------
# rooms > people at entry: food at category entry + the growth on offer
# ---------------------------------------------------------------------------

def test_food_and_growth_offered_when_rooms_exceed_people():
    s = _base_state()                     # 3 rooms, 2 people
    s = _enter_build_rooms(s)
    # +1 food the instant the Build Rooms host is pushed (before any build).
    assert s.players[0].resources.food == 1
    # The growth is offered before the first room commit.
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)


def test_trigger_window_closes_after_first_room():
    s = _enter_build_rooms(_base_state())
    s = _commit_any_room(s)
    # The before-window closed at the first commit (engine num_built gate).
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    # The food was granted once, not per room.
    s = _commit_any_room(s)
    assert s.players[0].resources.food == 1


# ---------------------------------------------------------------------------
# rooms <= people at entry: neither fires — even if the build itself creates
# rooms > people mid-action (ruling 1: measured BEFORE the action)
# ---------------------------------------------------------------------------

def test_neither_fires_at_rooms_equal_people():
    s = _base_state(extra_rooms=0)        # 2 rooms, 2 people
    s = _enter_build_rooms(s)
    assert s.players[0].resources.food == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    # Build a room: now 3 rooms > 2 people, but the measure was pre-action.
    s = _commit_any_room(s)
    assert _num_rooms(s, 0) == 3 and s.players[0].people_total == 2
    assert s.players[0].resources.food == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = _walk_out(s)
    assert s.players[0].resources.food == 0
    assert s.players[0].people_total == 2 and s.players[0].newborns == 0


# ---------------------------------------------------------------------------
# Growth declined: the food is kept (ruling 2)
# ---------------------------------------------------------------------------

def test_growth_declined_food_kept():
    s = _enter_build_rooms(_base_state())
    assert s.players[0].resources.food == 1
    s = _commit_any_room(s)               # decline by building instead of firing
    s = _walk_out(s)
    assert s.players[0].resources.food == 1
    assert s.players[0].people_total == 2 and s.players[0].newborns == 0


# ---------------------------------------------------------------------------
# Growth accepted: a real newborn, no board placement, exactly one per action
# ---------------------------------------------------------------------------

def test_growth_accepted():
    # 4 rooms, 2 people: rooms > people still holds AFTER the growth, so the
    # once-per-action latch (not the condition) must block a second fire.
    s = _base_state(extra_rooms=2)
    s = _enter_build_rooms(s)
    assert s.players[0].resources.food == 1

    s = step(s, FireTrigger(card_id=CARD_ID))
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
    # The newborn is NOT placeable: people_home and the board are untouched.
    assert p.people_home == home_before
    assert tuple(sp.workers for sp in s.board.action_spaces) == workers_before

    s = step(s, Stop())                   # pop the growth frame
    assert isinstance(s.pending_stack[-1], PendingBuildRooms)
    # Exactly 1 growth per action (clarification): 4 rooms > 3 people still,
    # but the triggers_resolved latch blocks a second fire.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    # The Build Rooms action itself still proceeds normally.
    assert any(isinstance(a, CommitBuildRoom) for a in legal_actions(s))
    s = _commit_any_room(s)
    s = _walk_out(s)
    assert s.players[0].people_total == 3
    assert s.players[0].resources.food == 1


# ---------------------------------------------------------------------------
# At the family cap: the food still fires, the growth does not
# ---------------------------------------------------------------------------

def test_at_family_cap_food_only():
    s = _base_state(extra_rooms=4)        # 6 rooms
    s = with_people(s, 0, total=5, home=5)  # cap reached (supply == 0)
    s = _enter_build_rooms(s)
    assert s.players[0].resources.food == 1   # 6 rooms > 5 people: food fires
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Named action only (ruling 3): Cottager's granted room build fires nothing
# ---------------------------------------------------------------------------

def test_cottager_granted_build_fires_neither():
    s = _base_state()                     # 3 rooms > 2 people: condition holds
    s = _own_occupation(s, 0, "cottager")
    s = step(s, PlaceWorker(space="day_laborer"))
    food_before = s.players[0].resources.food
    s = step(s, FireTrigger(card_id="cottager", variant="room"))
    top = s.pending_stack[-1]
    assert isinstance(top, PendingBuildRooms)
    assert top.build_rooms_action is False
    # Not the named action: no food, no growth offer.
    assert s.players[0].resources.food == food_before
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


# ---------------------------------------------------------------------------
# Ownership boundaries: hand-only inert, opponent's build fires nothing
# ---------------------------------------------------------------------------

def test_hand_only_is_inert():
    s = _base_state(played=False)         # in hand, never played
    s = _enter_build_rooms(s)
    assert s.players[0].resources.food == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)


def test_opponent_build_fires_nothing():
    s = _base_state(owner=0)              # P0 owns the card
    s = with_current_player(s, 1)
    # Give P1 (the builder) rooms > people + materials, so the condition would
    # hold for the acting player — only ownership must block the fire.
    s = with_grid(s, 1, {(0, 0): Cell(cell_type=CellType.ROOM)})
    s = with_resources(s, 1, wood=15, reed=6)
    s = _enter_build_rooms(s)
    assert s.players[0].resources.food == 0
    assert s.players[1].resources.food == 0
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
