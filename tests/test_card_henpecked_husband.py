"""Tests for Henpecked Husband (occupation, D94).

Card text (verbatim): "Each time you take a "Build Rooms" action with the
second person you place, return the first person you placed home, unless it
is on the "Meeting Place" action space."

Ruling 74 (user 2026-07-21): a mandatory `after_build_rooms` AUTO gated on a
NAMED Build Rooms action (`build_rooms_action == True`) taken on the turn
initiated by the owner's SECOND placement this round; the first placement's
space is recorded per-round in CardStore; no return when that space is
Meeting Place; a first person already home means nothing to return (silent
no-fire). Room-effect builds (the Cottager flag-False shape) never count.
Each real-flow test drives the actual placement/build machinery end-to-end.
"""
import agricola.cards.henpecked_husband  # noqa: F401  -- registers the card (not in cards/__init__ yet)
import agricola.cards.cottager  # noqa: F401  -- the flag-False granted-build exemplar

from agricola.actions import (
    ChooseSubAction,
    CommitBuildRoom,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.henpecked_husband import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.constants import CellType, HouseMaterial, SPACE_IDS
from agricola.legality import _is_available, legal_actions
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space
from tests.factories import (
    with_current_player,
    with_house,
    with_people,
    with_resources,
    with_round,
    with_space,
)
from tests.test_utils import run_actions

_POOL = CardPool(
    occupations=(CARD_ID, "cottager") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = with_current_player(cs, 0)
    p0 = fast_replace(cs.players[0], hand_occupations=frozenset(), hand_minors=frozenset())
    p1 = fast_replace(cs.players[1], hand_occupations=frozenset(), hand_minors=frozenset())
    return fast_replace(cs, players=(p0, p1))


def _own_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _setup(*, wood=5, reed=2):
    """Card-mode state: P0 owns Henpecked Husband, wood house, room affordable."""
    cs = _card_state()
    cs = with_house(cs, 0, HouseMaterial.WOOD)
    cs = with_resources(cs, 0, wood=wood, reed=reed)
    cs = _own_occ(cs, 0, CARD_ID)
    return cs


# P0's hosted atomic own-placement turn (every own space is hosted while the
# card is owned — the full-SPACE_IDS hook): place, Proceed (the space effect),
# Stop (pop; turn ends).
def _hosted_atomic_turn(space):
    return [PlaceWorker(space=space), Proceed(), Stop()]


# The Farm Expansion named Build Rooms turn, up to the after-flip that fires
# after_build_rooms (asserts go right after this; Stop/Proceed/Stop end it).
_BUILD_ROOMS_TO_FLIP = [
    PlaceWorker(space="farm_expansion"),
    ChooseSubAction(name="build_rooms"),
    CommitBuildRoom(row=0, col=0),
    Proceed(),    # flip PendingBuildRooms to after -> after_build_rooms fires
]
_END_BUILD_TURN = [Stop(), Proceed(), Stop()]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    before_cards = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    after_cards = {e.card_id for e in AUTO_EFFECTS.get("after_build_rooms", ())}
    assert CARD_ID in before_cards     # the recording auto
    assert CARD_ID in after_cards      # the return auto
    # Hooked over EVERY canonical space id (own-use), so every own placement
    # is hosted and the first placement can be recorded.
    for space_id in SPACE_IDS:
        assert CARD_ID in OWN_ACTION_HOOK_CARDS.get(space_id, set())


# ---------------------------------------------------------------------------
# The real flow: 1st person on Forest, 2nd person takes Build Rooms ->
# the Forest worker returns home and Forest is open again
# ---------------------------------------------------------------------------

def test_build_rooms_with_second_person_returns_first_home():
    cs = _setup()
    # P0's 1st placement: Forest (hosted). The record is stamped at the push.
    cs = run_actions(cs, _hosted_atomic_turn("forest"))
    assert cs.players[0].card_state.get(CARD_ID) == (1, "forest")
    assert get_space(cs.board, "forest").workers[0] == 1
    # P1's turn (unhosted atomic: single step).
    cs = run_actions(cs, [PlaceWorker(space="day_laborer")])
    # P0's 2nd placement: Farm Expansion, named Build Rooms.
    cs = run_actions(cs, _BUILD_ROOMS_TO_FLIP)
    # At the after-flip the first person came home automatically (mandatory).
    assert cs.players[0].people_home == 1
    assert get_space(cs.board, "forest").workers[0] == 0
    assert get_space(cs.board, "farm_expansion").workers[0] == 1
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    cs = run_actions(cs, _END_BUILD_TURN)
    # The vacated Forest is OPEN again — unoccupied, no residual "used this
    # round" block (the Tea Time open-space ruling: placement legality is
    # worker-presence). It is absent from legal_placements right now only
    # because P0's take emptied its stock and the engine prunes placement on
    # an EMPTY accumulation space (`_legal_forest` — placing there would gain
    # nothing); that pruning is orthogonal to occupancy, so restocked it is
    # immediately placeable by either player.
    assert get_space(cs.board, "forest").workers == (0, 0)
    assert _is_available(cs, "forest")
    cs = with_space(cs, "forest", accumulated=Resources(wood=3))
    assert PlaceWorker(space="forest") in legal_actions(cs)   # P1 could take it
    cs = run_actions(cs, [PlaceWorker(space="fishing")])      # P1 goes elsewhere
    # P0 re-places the returned first person — on Forest itself.
    assert PlaceWorker(space="forest") in legal_actions(cs)
    cs = run_actions(cs, [PlaceWorker(space="forest")])
    assert get_space(cs.board, "forest").workers[0] == 1
    assert cs.players[0].people_home == 0


# ---------------------------------------------------------------------------
# The printed exception: first person on Meeting Place -> no return
# ---------------------------------------------------------------------------

def test_meeting_place_exception_no_return():
    cs = _setup()
    # P0's 1st placement: Meeting Place (cards mode: become-SP at push; no
    # playable minor -> Proceed is the decline; Stop pops).
    cs = run_actions(cs, _hosted_atomic_turn("meeting_place"))
    assert cs.players[0].card_state.get(CARD_ID) == (1, "meeting_place")
    cs = run_actions(cs, [PlaceWorker(space="day_laborer")])
    cs = run_actions(cs, _BUILD_ROOMS_TO_FLIP)
    # The room was built, but the Meeting Place worker stays put.
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert get_space(cs.board, "meeting_place").workers[0] == 1
    assert cs.players[0].people_home == 0


# ---------------------------------------------------------------------------
# Ordinal gate: Build Rooms on the 1st placement -> no fire
# ---------------------------------------------------------------------------

def test_build_rooms_on_first_placement_no_fire():
    cs = _setup()
    # P0's FIRST placement is the Build Rooms action itself.
    cs = run_actions(cs, _BUILD_ROOMS_TO_FLIP)
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    # Nothing returned: the one placed worker stays, the other never left home.
    assert cs.players[0].people_home == 1
    assert get_space(cs.board, "farm_expansion").workers[0] == 1


# ---------------------------------------------------------------------------
# Ordinal gate: Build Rooms on the 3rd placement -> no fire
# ---------------------------------------------------------------------------

def test_build_rooms_on_third_placement_no_fire():
    cs = _setup()
    cs = with_people(cs, 0, total=3, home=3)
    cs = run_actions(cs, _hosted_atomic_turn("forest"))          # P0 1st
    cs = run_actions(cs, [PlaceWorker(space="day_laborer")])     # P1
    cs = run_actions(cs, _hosted_atomic_turn("grain_seeds"))     # P0 2nd
    cs = run_actions(cs, [PlaceWorker(space="fishing")])         # P1
    cs = run_actions(cs, _BUILD_ROOMS_TO_FLIP)                   # P0 3rd
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    # No return: both earlier workers stay placed.
    assert get_space(cs.board, "forest").workers[0] == 1
    assert get_space(cs.board, "grain_seeds").workers[0] == 1
    assert cs.players[0].people_home == 0


# ---------------------------------------------------------------------------
# Flag gate: a flag-False granted room build (Cottager) on the 2nd placement
# never counts as a named Build Rooms action
# ---------------------------------------------------------------------------

def test_flag_false_granted_build_no_fire():
    cs = _setup()
    cs = _own_occ(cs, 0, "cottager")
    cs = run_actions(cs, _hosted_atomic_turn("forest"))          # P0 1st (recorded)
    cs = run_actions(cs, [PlaceWorker(space="fishing")])         # P1
    # P0's 2nd placement: Day Laborer; Cottager's granted room build pushes
    # PendingBuildRooms with build_rooms_action=False (a room effect, not the
    # named action).
    cs = run_actions(cs, [
        PlaceWorker(space="day_laborer"),
        FireTrigger(card_id="cottager", variant="room"),
        CommitBuildRoom(row=0, col=0),
        Proceed(),    # flip the granted frame -> after_build_rooms fires
    ])
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    # Flag False -> no return, despite ordinal 2 and a live record.
    assert get_space(cs.board, "forest").workers[0] == 1
    assert cs.players[0].people_home == 0


# ---------------------------------------------------------------------------
# Per-round record: a stale prior-round record never fires
# ---------------------------------------------------------------------------

def test_stale_prior_round_record_never_fires():
    cs = _setup()
    # Round 2, one P0 worker already placed this round (on Forest), but the
    # stored record is from ROUND 1 — the round gate must block the return.
    cs = with_round(cs, 2)
    cs = with_people(cs, 0, home=1)
    cs = with_space(cs, "forest", workers=(1, 0))
    p0 = cs.players[0]
    p0 = fast_replace(p0, card_state=p0.card_state.set(CARD_ID, (1, "forest")))
    cs = fast_replace(cs, players=(p0, cs.players[1]))
    cs = run_actions(cs, _BUILD_ROOMS_TO_FLIP)   # P0's 2nd placement this round
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    assert get_space(cs.board, "forest").workers[0] == 1   # NOT returned
    assert cs.players[0].people_home == 0


# ---------------------------------------------------------------------------
# First person already home -> nothing to return: no crash, no fire
# ---------------------------------------------------------------------------

def test_first_person_already_home_no_crash_no_fire():
    cs = _setup()
    cs = run_actions(cs, _hosted_atomic_turn("forest"))          # P0 1st (recorded)
    cs = run_actions(cs, [PlaceWorker(space="day_laborer")])     # P1
    cs = run_actions(cs, [
        PlaceWorker(space="farm_expansion"),
        ChooseSubAction(name="build_rooms"),
    ])
    # The first person goes home some other way mid-turn (a Tea-Time-style
    # return: worker off the space, people_home +1).
    cs = with_space(cs, "forest", workers=(0, 0))
    cs = with_people(cs, 0, home=cs.players[0].people_home + 1)
    cs = run_actions(cs, [CommitBuildRoom(row=0, col=0), Proceed()])   # no crash
    assert cs.players[0].farmyard.grid[0][0].cell_type == CellType.ROOM
    # Nothing (further) returned: people_home unchanged by the flip.
    assert cs.players[0].people_home == 1
    assert get_space(cs.board, "forest").workers[0] == 0
