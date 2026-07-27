"""Tests for Motivator (occupation, E93).

Card text (verbatim): "On your first turn each round, if you have no unused farmyard
spaces, you can place a person from your supply."

The first card of the supply-loaner family: a meeple from SUPPLY works for one round
without joining the family. Ruled semantics (user 2026-07-21): it returns to supply at
returning-home, is never fed and never scored, and while it is out it occupies a physical
meeple — so Family Growth to a 5th person is blocked, which makes DECLINING sometimes
strictly optimal and therefore always available. Ruled 2026-07-24: the loaner is placed on
the player's first turn (an extra worker, not two placements in a row), and it ADVANCES
the "Nth person you place this round" ordinal.

The offer is a start-of-turn `PendingCardChoice` ("take" / "decline"); taking it moves one
meeple supply -> hand, after which it is fungible with a family worker and rides the
ordinary placement path.
"""
import agricola.cards  # noqa: F401  -- registers Motivator (and everything else)

from agricola.actions import CommitCardChoice, FireTrigger, PlaceWorker
from agricola.cards.motivator import CARD_ID, DECLINE, TAKE, _OPTIONS
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.turn_offers import TURN_START_OFFERS
from agricola.engine import _advance_until_decision, step
from agricola.helpers import placements_this_round
from agricola.legality import legal_actions
from agricola.pending import PendingCardChoice
from agricola.replace import fast_replace
from agricola.constants import CellType
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import (
    with_animals,
    with_current_player,
    with_grid,
    with_people,
    with_resources,
    with_space,
)

_SHEEP_INSPECTOR = "sheep_inspector"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)

_TAKE_IDX = _OPTIONS.index(TAKE)
_DECLINE_IDX = _OPTIONS.index(DECLINE)

_ALL_CELLS = [(r, c) for r in range(3) for c in range(5)]


def _fill_farm(state, *, rooms=5, leave_empty=0):
    """Use up every farmyard cell — `rooms` of them ROOMs (housing capacity, so growth
    stays possible) and the rest FIELDs — optionally leaving `leave_empty` cells EMPTY
    to break the "no unused farmyard spaces" condition."""
    cells = _ALL_CELLS[:len(_ALL_CELLS) - leave_empty]
    return with_grid(state, 0, {
        cell: Cell(cell_type=(CellType.ROOM if i < rooms else CellType.FIELD))
        for i, cell in enumerate(cells)
    })


def _setup(*, own=True, supply=1, total=4, rooms=5, leave_empty=0, seed=11):
    """Card-mode state, P0 to move: owns Motivator, farmyard fully used, `supply`
    meeples left. total=4 + supply=1 is the sharp case — the last meeple is the one
    both the loaner and a 5th family member want.

    `basic_wish_for_children` is a ROUND card (not revealed in round 1), so it is
    force-revealed here: the growth tests need it available to exercise the real
    wish-space gate.
    """
    s, _env = setup_env(seed, card_pool=_POOL)
    s = with_current_player(s, 0)
    p0 = fast_replace(s.players[0], hand_occupations=frozenset(),
                      hand_minors=frozenset(),
                      occupations=frozenset({CARD_ID}) if own else frozenset())
    s = fast_replace(s, players=(p0, s.players[1]))
    s = with_people(s, 0, total=total, home=total, supply=supply)
    s = with_space(s, "basic_wish_for_children", revealed=True)
    s = _fill_farm(s, rooms=rooms, leave_empty=leave_empty)
    return _advance_until_decision(s)


def _p0(state):
    return state.players[0]


def _offer_up(state) -> bool:
    return bool(state.pending_stack) and isinstance(
        state.pending_stack[-1], PendingCardChoice)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in TURN_START_OFFERS


# ---------------------------------------------------------------------------
# The offer surfaces, and is declinable
# ---------------------------------------------------------------------------

def test_offer_surfaces_on_the_first_turn():
    s = _setup()
    assert _offer_up(s)
    assert legal_actions(s) == [CommitCardChoice(index=_TAKE_IDX),
                                CommitCardChoice(index=_DECLINE_IDX)]


def test_taking_moves_a_meeple_from_supply_to_hand():
    s = step(_setup(), CommitCardChoice(index=_TAKE_IDX))
    p = _p0(s)
    assert p.workers_in_supply == 0        # the meeple left the supply pile
    assert p.people_home == 5              # ...and is available to place
    assert p.temp_workers_active == 1
    assert p.people_total == 4             # NEVER a family member


def test_declining_changes_nothing():
    s = step(_setup(), CommitCardChoice(index=_DECLINE_IDX))
    p = _p0(s)
    assert (p.workers_in_supply, p.people_home, p.temp_workers_active) == (1, 4, 0)


def test_resolving_the_offer_does_not_end_the_turn():
    """The offer is answered at the START of the turn — the player still places this
    turn, so the frame must not trigger the worker alternation."""
    for idx in (_TAKE_IDX, _DECLINE_IDX):
        s = step(_setup(), CommitCardChoice(index=idx))
        assert s.current_player == 0
        assert s.pending_stack == ()
        assert all(isinstance(a, PlaceWorker) for a in legal_actions(s))


def test_offer_is_not_repeated_after_being_answered():
    """Liveness: eligibility is re-tested at every WORK decision boundary, so an offer
    that survived its answer would be re-pushed forever."""
    for idx in (_TAKE_IDX, _DECLINE_IDX):
        s = step(_setup(), CommitCardChoice(index=idx))
        assert not _offer_up(s)
        assert CARD_ID in _p0(s).used_this_round
        # ...and it stays gone after the player actually places.
        s = step(s, legal_actions(s)[0])
        assert not _offer_up(s)


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_not_offered_without_the_card():
    assert not _offer_up(_setup(own=False))


def test_not_offered_with_an_unused_farmyard_space():
    assert not _offer_up(_setup(leave_empty=1))


def test_not_offered_with_no_meeple_in_supply():
    assert not _offer_up(_setup(supply=0, total=5))


def test_not_offered_after_the_first_placement():
    """"On your first turn" — a second turn gets no offer. (Here the latch is cleared
    to prove the placement-count conjunct carries the restriction on its own.)"""
    s = step(_setup(), CommitCardChoice(index=_DECLINE_IDX))
    s = step(s, legal_actions(s)[0])                 # P0 places; turn passes to P1
    p = _p0(s)
    s = fast_replace(s, players=(
        fast_replace(p, used_this_round=p.used_this_round - {CARD_ID}),
        s.players[1]))
    s = with_current_player(s, 0)
    assert not _offer_up(_advance_until_decision(s))


# ---------------------------------------------------------------------------
# The growth tradeoff — the reason declining must exist
# ---------------------------------------------------------------------------

def _wish_legal(state) -> bool:
    return any(isinstance(a, PlaceWorker) and a.space == "basic_wish_for_children"
               for a in legal_actions(state))


def test_taking_the_loaner_blocks_growth_to_the_fifth_person():
    """With one meeple left, the loaner and a 5th family member want the SAME token.
    No loaner-specific legality code does this — the existing `workers_in_supply > 0`
    wish gate does."""
    s = _setup()
    assert _wish_legal(step(s, CommitCardChoice(index=_DECLINE_IDX)))
    assert not _wish_legal(step(s, CommitCardChoice(index=_TAKE_IDX)))


def test_taking_the_loaner_leaves_growth_open_when_a_meeple_remains():
    """Only the LAST meeple is contested: at 3 family with 2 in supply, taking the
    loaner still leaves a token to grow with."""
    s = _setup(total=3, supply=2)
    assert _wish_legal(step(s, CommitCardChoice(index=_TAKE_IDX)))


# ---------------------------------------------------------------------------
# The loaner as a worker — ordinal, and the full round
# ---------------------------------------------------------------------------

def test_loaner_placement_is_the_first_person_placed():
    """User ruling 2026-07-24: a loaner advances the ordinal, so the placement made
    with it is "the first person you place" — and the next one is the second."""
    s = step(_setup(), CommitCardChoice(index=_TAKE_IDX))
    assert placements_this_round(_p0(s)) == 0
    s = step(s, legal_actions(s)[0])
    assert placements_this_round(_p0(s)) == 1
    s = with_current_player(_advance_until_decision(s), 0)
    s = step(s, legal_actions(s)[0])
    assert placements_this_round(_p0(s)) == 2


def _play_round(state):
    """Drive both players greedily until the round advances; return the state."""
    start = state.round_number
    while state.round_number == start and state.phase.name != "GAME_OVER":
        actions = legal_actions(state)
        if not actions:
            raise AssertionError(
                f"no legal action at round {state.round_number}, "
                f"phase {state.phase}, stack "
                f"{[type(f).__name__ for f in state.pending_stack]}")
        state = step(state, actions[0])
    return state


def _count_p0_placements(state) -> int:
    """Play out the round, counting the worker placements P0 actually makes."""
    start, placed = state.round_number, 0
    while state.round_number == start and state.phase.name != "GAME_OVER":
        actions = legal_actions(state)
        assert actions, (
            f"no legal action at round {state.round_number}, phase {state.phase}, "
            f"stack {[type(f).__name__ for f in state.pending_stack]}")
        action = actions[0]
        if isinstance(action, PlaceWorker) and state.current_player == 0:
            placed += 1
        state = step(state, action)
    return placed


def test_taking_the_loaner_yields_one_extra_placement():
    """The whole point of the card: 4 family + 1 loaner = 5 placements, against the
    4 a declining player gets."""
    with_loaner = _count_p0_placements(
        step(_setup(), CommitCardChoice(index=_TAKE_IDX)))
    declined = _count_p0_placements(
        step(_setup(), CommitCardChoice(index=_DECLINE_IDX)))
    assert declined == 4
    assert with_loaner == 5


def test_round_end_returns_the_loaner_to_supply():
    """The meeple goes back to SUPPLY (not home), so it is never fed and growth
    re-opens next round. Meeple conservation: people_total + workers_in_supply is
    back to the 5 the player owns."""
    s = step(_setup(), CommitCardChoice(index=_TAKE_IDX))
    assert _p0(s).people_total + _p0(s).workers_in_supply == 4    # one is on loan
    end = _play_round(s)
    p = _p0(end)
    assert p.temp_workers_active == 0
    assert p.workers_in_supply == 1
    assert p.people_total == 4
    assert p.people_total + p.workers_in_supply == 5              # conservation
    assert p.people_home == p.people_total                        # loaner NOT at home


def test_declined_round_conserves_meeples_too():
    end = _play_round(step(_setup(), CommitCardChoice(index=_DECLINE_IDX)))
    p = _p0(end)
    assert (p.temp_workers_active, p.workers_in_supply, p.people_total) == (0, 1, 4)


def test_returning_a_worker_mid_round_still_conserves_meeples():
    """Sheep Inspector (D93) returns a placed person home mid-round. The meeple is
    fungible, so nothing knows or needs to know whether the returned one was the
    loaner — and because a return moves a meeple board -> home without touching
    `workers_in_supply`, the borrowed meeple stays borrowed (growth stays blocked)
    and the round-end restore still balances exactly.

    This is the interaction that broke an earlier design, where the loaner was
    tracked by the space id it stood on: a returned loaner vanished from that record
    and its meeple was silently destroyed at the restore.
    """
    s = _setup(supply=2, total=3)                     # room to place + a spare meeple
    p0 = fast_replace(s.players[0],
                      occupations=frozenset({CARD_ID, _SHEEP_INSPECTOR}))
    s = fast_replace(s, players=(p0, s.players[1]))
    s = with_resources(s, 0, food=6)
    s = with_animals(s, 0, sheep=2)
    s = _advance_until_decision(s)

    s = step(s, CommitCardChoice(index=_TAKE_IDX))
    assert _p0(s).temp_workers_active == 1

    # Play the round out, firing Sheep Inspector's return the first time it is offered.
    fired, start = False, s.round_number
    while s.round_number == start and s.phase.name != "GAME_OVER":
        actions = legal_actions(s)
        assert actions
        pick = None
        if not fired:
            pick = next((a for a in actions
                         if isinstance(a, FireTrigger)
                         and a.card_id == _SHEEP_INSPECTOR), None)
            fired = pick is not None
        s = step(s, pick or actions[0])

    assert fired, "Sheep Inspector never offered its return — test drove nothing"
    p = _p0(s)
    assert p.temp_workers_active == 0
    assert p.people_total + p.workers_in_supply == 5      # no meeple lost or gained
    assert p.people_home == p.people_total


def test_offer_returns_in_a_later_round():
    """The latch is per-round: a fresh round re-offers (the card recurs every round)."""
    s = step(_setup(), CommitCardChoice(index=_DECLINE_IDX))
    end = _play_round(s)
    assert CARD_ID not in _p0(end).used_this_round
