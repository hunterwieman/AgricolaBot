"""Tests for Child Ombudsman (occupation, D92).

Card text (verbatim): "From round 5 on, if you have room in your house, at the end of
each person action, you can take a 'Family Growth' action with that person. If you do,
you get 2 negative points."

Ruling 81 item 4 (2026-07-26): fires at `after_action_space` ("at the end of each person
action"); no per-round latch — it can fire on every qualifying person action (multiple
times a turn once a chained-use card like Job Contract exists). The growth is the
card-granted no-space form (`PendingFamilyGrowth(place_on_space=False)`) — nothing moves,
despite the "with that person" phrasing. "Room in your house" is the standard growth room
gate (housing capacity, so capacity cards extend it), and the meeple supply is the family
cap. Each use scores −2.
"""
import agricola.cards  # noqa: F401  -- registers the card (and everything else)

from agricola.actions import (
    CommitFamilyGrowth,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.child_ombudsman import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType
from agricola.engine import step
from agricola.helpers import placements_this_round
from agricola.legality import legal_actions
from agricola.pending import PendingFamilyGrowth
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import (
    with_current_player,
    with_grid,
    with_people,
    with_round,
)

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _p0(state):
    return state.players[0]


def _setup(*, round_number=5, rooms=3, total=2, supply=3, own=True, seed=11):
    """Card-mode WORK state, P0 to move, owning Child Ombudsman, with `rooms` rooms
    (default 3 > 2 people: room available)."""
    s, _env = setup_env(seed, card_pool=_POOL)
    s = with_current_player(s, 0)
    p0 = fast_replace(s.players[0], hand_occupations=frozenset(),
                      hand_minors=frozenset(),
                      occupations=frozenset({CARD_ID}) if own else frozenset())
    p1 = fast_replace(s.players[1], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    s = fast_replace(s, players=(p0, p1))
    s = with_round(s, round_number)
    s = with_people(s, 0, total=total, home=total, supply=supply)
    if rooms > 2:
        s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})   # a 3rd room
    return s


def _fires(state) -> bool:
    return any(isinstance(a, FireTrigger) and a.card_id == CARD_ID
               for a in legal_actions(state))


def _card_score(state, idx):
    return sum(fn(state, idx) for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _end_turn(state):
    """Drain the turn: Stop through the growth's and the host's after-phases."""
    from agricola.actions import Stop as _Stop
    while state.pending_stack:
        acts = legal_actions(state)
        state = step(state, _Stop() if _Stop() in acts else acts[0])
    return state


def _forest_after_window(state):
    """Place on the (hooked, hence hosted) Forest and advance to its after window."""
    state = step(state, PlaceWorker(space="forest"))
    state = step(state, Proceed())          # the atomic take runs; after window opens
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert any(cid == CARD_ID for cid, _fn in SCORING_TERMS)


# ---------------------------------------------------------------------------
# The real flow: fire after a person action, grow with no board placement
# ---------------------------------------------------------------------------

def test_fires_after_a_person_action_and_grows_without_placing():
    s = _forest_after_window(_setup())
    assert _fires(s)
    p_before = _p0(s)
    workers_before = sum(
        sp.workers[0] for sp in s.board.action_spaces)
    ordinal_before = placements_this_round(p_before)

    s = step(s, FireTrigger(card_id=CARD_ID))
    assert isinstance(s.pending_stack[-1], PendingFamilyGrowth)
    assert s.pending_stack[-1].place_on_space is False
    s = step(s, CommitFamilyGrowth())
    p = _p0(s)
    assert p.people_total == p_before.people_total + 1
    assert p.newborns == p_before.newborns + 1
    assert p.workers_in_supply == p_before.workers_in_supply - 1
    # Nothing moved and nothing was placed: no new board worker, no ordinal mint.
    assert sum(sp.workers[0] for sp in s.board.action_spaces) == workers_before
    assert placements_this_round(p) == ordinal_before
    # The use is scored −2.
    assert _card_score(s, 0) == -2


def test_declinable():
    s = _forest_after_window(_setup())
    assert _fires(s)
    s = step(s, Stop())                     # decline: end the turn instead
    p = _p0(s)
    assert p.people_total == 2
    assert _card_score(s, 0) == 0


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_before_round_5():
    s = _forest_after_window(_setup(round_number=4))
    assert not _fires(s)


def test_not_without_room():
    s = _forest_after_window(_setup(rooms=2))       # 2 rooms, 2 people: full house
    assert not _fires(s)


def test_not_without_a_supply_meeple():
    s = _forest_after_window(_setup(rooms=3, total=2, supply=0))
    assert not _fires(s)


def test_not_without_ownership():
    s = _setup(own=False)
    s = step(s, PlaceWorker(space="forest"))
    # Without the card, no hook: Forest resolves atomically — no host, no trigger.
    assert not s.pending_stack
    assert not _fires(s)


# ---------------------------------------------------------------------------
# No per-round latch: every qualifying person action offers it
# ---------------------------------------------------------------------------

def test_fires_on_a_second_person_action_in_the_same_round():
    """Two of the owner's turns in one round; both offer the growth (no latch —
    ruling 81 item 4). Take it both times: 2 -> 4 people, scored −4."""
    s = _setup(rooms=4, total=2, supply=3)
    s = with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.ROOM),
                         (0, 1): Cell(cell_type=CellType.ROOM)})   # 4 rooms
    s = _forest_after_window(s)
    assert _fires(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitFamilyGrowth())
    s = _end_turn(s)                                     # end P0's turn
    assert s.current_player == 1
    s = step(s, PlaceWorker(space="clay_pit"))           # P1's turn (atomic for them)
    s = _end_turn(s)
    assert s.current_player == 0
    s = step(s, PlaceWorker(space="reed_bank"))
    s = step(s, Proceed())
    assert _fires(s)                                     # offered AGAIN, same round
    s = step(s, FireTrigger(card_id=CARD_ID))
    s = step(s, CommitFamilyGrowth())
    p = _p0(s)
    assert p.people_total == 4
    assert _card_score(s, 0) == -4
