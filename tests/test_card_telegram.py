"""Tests for Telegram (minor improvement, A22).

Card text (verbatim): "Add 1 to the current round for each fence in your supply and mark
the corresponding round space. In that round only, you can place a person from your
supply."
Clarification: "The person is returned to your supply in the 'returning home' phase."

Two clauses, tested separately: the SCHEDULING clause (target round = current + fences in
supply, recorded in CardStore — the printed "mark the round space" is a physical reminder,
not game state) and the LOANER clause (in that round only, a supply meeple may work).

Unlike Motivator — whose offer is pinned by its text to the player's first turn — Telegram's
loaner is available anywhere in its round, so the offer is surfaced at the LAST usable
moment: once every household worker is placed. That requires the engine to grant a turn to a
player who has no workers but an outstanding offer (`engine._can_act`), which is the
behaviour several tests here pin.
"""
import agricola.cards  # noqa: F401  -- registers Telegram (and everything else)

from agricola.actions import CommitCardChoice, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.cards.telegram import CARD_ID, DECLINE, TAKE, _OPTIONS
from agricola.cards.turn_offers import TURN_START_OFFERS, has_outstanding_offer
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


def _owning(state, *, target, home=0, supply=1, total=3, fences=15):
    """P0 owns Telegram scheduled for `target`, with `home` household workers left."""
    p = state.players[0]
    p = fast_replace(p,
                     minor_improvements=p.minor_improvements | {CARD_ID},
                     card_state=p.card_state.set(CARD_ID, target),
                     fences_in_supply=fences)
    state = fast_replace(state, players=(p, state.players[1]))
    state = with_people(state, 0, total=total, home=home, supply=supply)
    return with_people(state, 1, total=2, home=0)   # opponent finished


def _at_target_round(*, target=4, **kw):
    s = with_round(_base(), target)
    return _advance_until_decision(_owning(s, target=target, **kw))


# ---------------------------------------------------------------------------
# Registration + the static facts
# ---------------------------------------------------------------------------

def test_registered_with_printed_cost_and_vp():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(food=2)
    assert spec.vps == 1
    assert CARD_ID in TURN_START_OFFERS


def test_prereq_needs_a_fence_in_supply():
    """"At Least 1 Fence in Supply" is a have-check, not a cost — the fences are not
    spent."""
    spec = MINORS[CARD_ID]
    s = _base()
    p = fast_replace(s.players[0], fences_in_supply=0)
    assert not spec.prereq(fast_replace(s, players=(p, s.players[1])), 0)
    p = fast_replace(s.players[0], fences_in_supply=1)
    assert spec.prereq(fast_replace(s, players=(p, s.players[1])), 0)


# ---------------------------------------------------------------------------
# Clause 1 — the scheduling
# ---------------------------------------------------------------------------

def test_on_play_schedules_current_round_plus_fences_in_supply():
    s = with_round(_base(), 3)
    p = fast_replace(s.players[0], fences_in_supply=5)
    s = fast_replace(s, players=(p, s.players[1]))
    s = MINORS[CARD_ID].on_play(s, 0)
    assert _p0(s).card_state.get(CARD_ID) == 8       # round 3 + 5 fences
    assert _p0(s).fences_in_supply == 5              # the fences are NOT consumed


def test_a_target_past_the_last_round_simply_never_arrives():
    s = with_round(_base(), 2)
    p = fast_replace(s.players[0], fences_in_supply=15)
    s = fast_replace(s, players=(p, s.players[1]))
    s = MINORS[CARD_ID].on_play(s, 0)
    assert _p0(s).card_state.get(CARD_ID) == 17      # > 14: the loaner never comes
    assert not has_outstanding_offer(s, 0)


# ---------------------------------------------------------------------------
# Clause 2 — the loaner, offered at the last usable moment
# ---------------------------------------------------------------------------

def test_offer_surfaces_in_the_target_round_once_workers_are_spent():
    s = _at_target_round(target=4, home=0)
    assert _offer_up(s)
    assert legal_actions(s) == [CommitCardChoice(index=_TAKE_IDX),
                                CommitCardChoice(index=_DECLINE_IDX)]


def test_not_offered_while_household_workers_remain():
    """The deferral prune: taking a loaner never yields a placement sooner, so an early
    offer would be a dominated choice."""
    s = _at_target_round(target=4, home=2)
    assert not _offer_up(s)
    assert all(isinstance(a, PlaceWorker) for a in legal_actions(s))


def test_not_offered_in_other_rounds():
    for round_number in (3, 5):
        s = with_round(_base(), round_number)
        s = _advance_until_decision(_owning(s, target=4, home=0))
        assert not _offer_up(s)


def test_not_offered_without_a_meeple_in_supply():
    """A player who grew to 5 has no meeple to loan, so the effect is simply unusable."""
    s = _at_target_round(target=4, home=0, supply=0, total=5)
    assert not _offer_up(s)


def test_not_offered_without_owning_the_card():
    s = with_round(_base(), 4)
    s = with_people(s, 0, total=3, home=0, supply=1)
    s = with_people(s, 1, total=2, home=0)
    assert not _offer_up(_advance_until_decision(s))


# ---------------------------------------------------------------------------
# The extra turn — the work phase must wait for an outstanding offer
# ---------------------------------------------------------------------------

def test_work_phase_does_not_end_while_the_offer_is_outstanding():
    """Everyone is out of household workers, yet the round must not end: this player may
    still place a loaner."""
    s = _at_target_round(target=4, home=0)
    assert s.phase is Phase.WORK
    assert s.round_number == 4
    assert _offer_up(s)


def test_declining_lets_the_round_end():
    s = step(_at_target_round(target=4, home=0), CommitCardChoice(index=_DECLINE_IDX))
    assert s.round_number != 4 or s.phase is not Phase.WORK
    assert _p0(s).temp_workers_active == 0


def test_taking_grants_a_placement_turn():
    s = step(_at_target_round(target=4, home=0), CommitCardChoice(index=_TAKE_IDX))
    p = _p0(s)
    assert (p.workers_in_supply, p.people_home, p.temp_workers_active) == (0, 1, 1)
    assert p.people_total == 3                     # never a family member
    assert s.current_player == 0                   # the turn is theirs
    assert s.phase is Phase.WORK and s.round_number == 4
    assert all(isinstance(a, PlaceWorker) for a in legal_actions(s))


def test_the_loaner_actually_places_and_then_the_round_ends():
    s = step(_at_target_round(target=4, home=0), CommitCardChoice(index=_TAKE_IDX))
    placements = legal_actions(s)
    s = step(s, placements[0])
    while s.round_number == 4 and s.phase is Phase.WORK:
        s = step(s, legal_actions(s)[0])
    p = _p0(s)
    assert p.temp_workers_active == 0              # returned at the reset
    assert p.workers_in_supply == 1                # ...to SUPPLY, not home
    assert p.people_total + p.workers_in_supply == 4   # conservation (3 family owned + 1)


def test_offer_is_not_repeated_after_being_answered():
    """Liveness: an outstanding offer holds the work phase open, so an offer surviving
    its own decline would loop forever."""
    for idx in (_TAKE_IDX, _DECLINE_IDX):
        s = step(_at_target_round(target=4, home=0), CommitCardChoice(index=idx))
        assert not _offer_up(s)
        assert CARD_ID in _p0(s).used_this_round


# ---------------------------------------------------------------------------
# The growth tradeoff
# ---------------------------------------------------------------------------

def test_taking_the_loaner_blocks_growth_while_it_is_out():
    """The loaner occupies the physical meeple a 5th family member would need — enforced
    by the existing wish gate reading `workers_in_supply`, with no card-specific code."""
    s = step(_at_target_round(target=4, home=0, total=4, supply=1),
             CommitCardChoice(index=_TAKE_IDX))
    assert _p0(s).workers_in_supply == 0
    s2 = step(_at_target_round(target=4, home=0, total=4, supply=1),
              CommitCardChoice(index=_DECLINE_IDX))
    assert _p0(s2).workers_in_supply == 1
