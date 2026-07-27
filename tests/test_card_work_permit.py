"""Tests for Work Permit (minor improvement, D22).

Card text (verbatim): "Add 1 to the current round for each building resource you have and
place 1 person from your supply on the corresponding round space. In that round, you can
use the person."

Telegram's near-twin, differing in the one respect these tests exist to pin: the meeple
leaves SUPPLY when the card is played (it sits on the round space), not when the loaner is
used. So growth is blocked for the whole stretch between play and that round, the loaner
costs no second meeple when taken, and an unused parked meeple comes back at its round's
returning-home phase.

Per the user's 2026-07-24 ruling, the person "on the corresponding round space" is a TIMING
indicator — it does not occupy or block that action space, exactly as goods placed on a round
space don't — so the effect is equivalent to setting the worker aside for a named future
round. Hence the parked meeple is CardStore state, and no test here expects the round space
to be blocked.
"""
import agricola.cards  # noqa: F401  -- registers Work Permit (and everything else)

from agricola.actions import CommitCardChoice, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.cards.work_permit import CARD_ID, DECLINE, TAKE, _OPTIONS
from agricola.cards.turn_offers import TURN_START_OFFERS
from agricola.constants import Phase
from agricola.engine import _advance_until_decision, step
from agricola.legality import legal_actions
from agricola.pending import PendingCardChoice
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import (
    with_current_player,
    with_people,
    with_resources,
    with_round,
)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)

_TAKE_IDX = _OPTIONS.index(TAKE)
_DECLINE_IDX = _OPTIONS.index(DECLINE)


def _p0(state):
    return state.players[0]


def _offer_up(state) -> bool:
    return bool(state.pending_stack) and isinstance(
        state.pending_stack[-1], PendingCardChoice)


def _base(*, seed=11):
    s, _env = setup_env(seed, card_pool=_POOL)
    s = with_current_player(s, 0)
    p0 = fast_replace(s.players[0], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    p1 = fast_replace(s.players[1], hand_occupations=frozenset(),
                      hand_minors=frozenset())
    return fast_replace(s, players=(p0, p1))


def _parked(state, *, target, home=0, supply=1, total=3):
    """P0 owns Work Permit with a meeple already parked for `target`."""
    p = state.players[0]
    p = fast_replace(p,
                     minor_improvements=p.minor_improvements | {CARD_ID},
                     card_state=p.card_state.set(CARD_ID, target))
    state = fast_replace(state, players=(p, state.players[1]))
    state = with_people(state, 0, total=total, home=home, supply=supply)
    return with_people(state, 1, total=2, home=0)     # opponent finished


def _at_target_round(*, target=4, **kw):
    s = with_round(_base(), target)
    return _advance_until_decision(_parked(s, target=target, **kw))


# ---------------------------------------------------------------------------
# Registration + the static facts
# ---------------------------------------------------------------------------

def test_registered_with_printed_cost():
    assert CARD_ID in MINORS
    assert MINORS[CARD_ID].cost.resources == Resources(food=1)
    assert MINORS[CARD_ID].vps == 0
    assert CARD_ID in TURN_START_OFFERS


def test_prereq_needs_a_building_resource_and_a_meeple():
    spec = MINORS[CARD_ID]
    s = with_resources(_base(), 0, wood=0, clay=0, reed=0, stone=0)
    assert not spec.prereq(s, 0)                      # no building resource
    s = with_resources(_base(), 0, clay=1)
    assert spec.prereq(s, 0)
    assert not spec.prereq(with_people(s, 0, total=5, home=5, supply=0), 0)   # no meeple


def test_food_and_grain_are_not_building_resources():
    spec = MINORS[CARD_ID]
    s = with_resources(_base(), 0, wood=0, clay=0, reed=0, stone=0,
                       food=5, grain=5, veg=5)
    assert not spec.prereq(s, 0)


# ---------------------------------------------------------------------------
# On play — the meeple leaves supply NOW
# ---------------------------------------------------------------------------

def test_on_play_schedules_and_parks_a_meeple():
    s = with_round(_base(), 3)
    s = with_resources(s, 0, wood=2, clay=1, reed=1, stone=1)   # 5 building resources
    s = with_people(s, 0, total=3, home=3, supply=2)
    s = MINORS[CARD_ID].on_play(s, 0)
    p = _p0(s)
    assert p.card_state.get(CARD_ID) == 8            # round 3 + 5 resources
    assert p.workers_in_supply == 1                  # ...and a meeple left the pile NOW
    assert p.resources.wood == 2                     # the resources are NOT consumed
    assert p.temp_workers_active == 0                # parked, not yet working


def test_parking_blocks_growth_from_play_time():
    """The whole point of the card's cost: the meeple is gone from supply for the whole
    stretch between playing it and its round, not just for the round it works."""
    s = with_round(_base(), 2)
    s = with_resources(s, 0, clay=1)
    s = with_people(s, 0, total=4, home=4, supply=1)   # the LAST meeple
    s = MINORS[CARD_ID].on_play(s, 0)
    assert _p0(s).workers_in_supply == 0               # growth to 5 now impossible


# ---------------------------------------------------------------------------
# The loaner, in its round
# ---------------------------------------------------------------------------

def test_offer_surfaces_in_the_target_round_once_workers_are_spent():
    s = _at_target_round(target=4, home=0)
    assert _offer_up(s)
    assert legal_actions(s) == [CommitCardChoice(index=_TAKE_IDX),
                                CommitCardChoice(index=_DECLINE_IDX)]


def test_not_offered_while_household_workers_remain():
    s = _at_target_round(target=4, home=2)
    assert not _offer_up(s)


def test_not_offered_in_other_rounds():
    for round_number in (3, 5):
        s = with_round(_base(), round_number)
        assert not _offer_up(_advance_until_decision(_parked(s, target=4, home=0)))


def test_taking_does_not_debit_supply_again():
    """The meeple was taken at play time; taking the loaner must not charge a second."""
    s = _at_target_round(target=4, home=0, supply=0)   # supply already emptied by parking
    s = step(s, CommitCardChoice(index=_TAKE_IDX))
    p = _p0(s)
    assert p.workers_in_supply == 0                   # unchanged, not negative
    assert (p.people_home, p.temp_workers_active) == (1, 1)
    assert p.card_state.get(CARD_ID) is None          # left the round space


def test_used_loaner_returns_to_supply_at_round_end():
    s = step(_at_target_round(target=4, home=0, supply=0),
             CommitCardChoice(index=_TAKE_IDX))
    s = step(s, legal_actions(s)[0])                  # place the loaner
    while s.round_number == 4 and s.phase is Phase.WORK:
        s = step(s, legal_actions(s)[0])
    p = _p0(s)
    assert (p.temp_workers_active, p.workers_in_supply) == (0, 1)
    assert p.people_total + p.workers_in_supply == 4  # conservation (3 family + 1 loaned)


def test_unused_parked_meeple_returns_to_supply_at_round_end():
    """Declining must not strand the meeple on the round space forever."""
    s = step(_at_target_round(target=4, home=0, supply=0),
             CommitCardChoice(index=_DECLINE_IDX))
    while s.round_number == 4 and s.phase is Phase.WORK:
        s = step(s, legal_actions(s)[0])
    p = _p0(s)
    assert p.workers_in_supply == 1                   # came back
    assert p.card_state.get(CARD_ID) is None          # record cleared
    assert p.temp_workers_active == 0


def test_taking_grants_a_placement_turn():
    s = step(_at_target_round(target=4, home=0), CommitCardChoice(index=_TAKE_IDX))
    assert s.current_player == 0
    assert s.phase is Phase.WORK and s.round_number == 4
    assert all(isinstance(a, PlaceWorker) for a in legal_actions(s))


def test_offer_is_not_repeated_after_being_answered():
    for idx in (_TAKE_IDX, _DECLINE_IDX):
        s = step(_at_target_round(target=4, home=0), CommitCardChoice(index=idx))
        assert not _offer_up(s)
        assert CARD_ID in _p0(s).used_this_round
