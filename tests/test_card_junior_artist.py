import agricola.cards.junior_artist  # noqa: F401  (registers the card — deliberately not in cards/__init__ yet)
import agricola.cards.lodger  # noqa: F401  (the inert hand occupation played at Lessons)

"""Junior Artist (occupation, B152, [4+]): "Each time after you use the 'Day
Laborer' action space, you can pay 1 food to use an unoccupied 'Traveling
Players' or 'Lessons' action space with the same person."

Rulings under test (user, 2026-07-26 — ruling 81): the jump is an OPTIONAL
trigger in the owner's own Day Laborer after_action_space window; firing moves
the acting worker's board marker and runs the destination's FULL action
(worker_moves.relocate_and_use), the walk returning to the source's
after-window; destination-unoccupied is read at the trigger time; NO placement
number is minted (`placements_this_round` untouched).

`traveling_players` does not exist on the 2-player board, so the Lessons branch
is the live one here (the Traveling Players variant must simply never appear).
Players 4+ — never dealt at 2p; these tests inject the card (Lodger precedent).
The 1-food cost is the Canal Boatman shape (food on hand, direct debit), with
the destination predicate evaluated on the post-payment state — so a jump that
would strand the worker at Lessons unable to pay the occupation cost is never
offered.
"""

from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
    Proceed,
    Stop,
)
from agricola.cards.junior_artist import CARD_ID, _variants
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, PLAY_VARIANT_TRIGGERS
from agricola.constants import GameMode
from agricola.engine import step
from agricola.helpers import placements_this_round
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingSubActionSpace
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import get_space
from tests.factories import (
    with_current_player,
    with_people,
    with_resources,
    with_space,
)


def _own(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _with_hand(state, idx, card_ids):
    p = state.players[idx]
    p = fast_replace(p, hand_occupations=p.hand_occupations | set(card_ids))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _state(*, food=0, own=True, hand=("lodger",)):
    """A CARDS-mode state, P0 to move (and starting player), holding exactly
    `food` food, owning the card by default, with `hand` in hand. Owning the
    card means P0 has 1 played occupation, so the Lessons price for the next
    one is the normal 1 food (`occupation_cost(1)`)."""
    state = fast_replace(setup(seed=0), mode=GameMode.CARDS, starting_player=0)
    state = with_current_player(state, 0)
    state = with_resources(state, 0, food=food)
    if own:
        state = _own(state, 0)
    if hand:
        state = _with_hand(state, 0, hand)
    return state


def _ja_triggers(opts):
    """The Junior Artist FireTriggers among legal actions, as a variant set."""
    return {a.variant for a in opts
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID}


def _to_after_window(state):
    """Place on Day Laborer (hosted — the card hooks it) and Proceed through
    the atomic +2-food effect into the host's after-window."""
    state = step(state, PlaceWorker(space="day_laborer"))
    acts = legal_actions(state)
    assert [type(a).__name__ for a in acts] == ["Proceed"]   # after-only trigger
    return step(state, Proceed())


def _workers(state, space_id):
    return get_space(state.board, space_id).workers


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("day_laborer", frozenset())


# ---------------------------------------------------------------------------
# The Day Laborer -> Lessons jump, end to end
# ---------------------------------------------------------------------------

def test_jump_to_lessons_end_to_end():
    state = _to_after_window(_state(food=0))
    p0 = state.players[0]
    assert p0.resources.food == 2                    # Day Laborer's +2 taken
    assert p0.people_home == 1                       # one worker placed
    assert placements_this_round(p0) == 1

    # After-window: exactly the Lessons jump + Stop. The Traveling Players
    # variant never appears — the space is not on the 2-player board.
    acts = legal_actions(state)
    assert _ja_triggers(acts) == {"lessons"}
    assert {type(a).__name__ for a in acts} == {"FireTrigger", "Stop"}
    assert len(acts) == 2

    # Fire the jump: 1 food paid, the SAME worker moves Day Laborer -> Lessons,
    # no extra person consumed, no placement number minted.
    state = step(state, FireTrigger(card_id=CARD_ID, variant="lessons"))
    p0 = state.players[0]
    assert p0.resources.food == 1                    # 2 - 1 jump payment
    assert _workers(state, "day_laborer") == (0, 0)  # vacated
    assert _workers(state, "lessons") == (1, 0)      # the same person, moved
    assert p0.people_home == 1                       # no second worker used
    assert placements_this_round(p0) == 1            # ordinal unchanged (ruling 81 item 3)

    # The destination's FULL action: the Lessons host demands its one mandatory
    # sub-action...
    top = state.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace)
    assert top.initiated_by_id == "space:lessons"
    acts = legal_actions(state)
    assert [type(a).__name__ for a in acts] == ["ChooseSubAction"]
    assert acts[0].name == "play_occupation"
    state = step(state, acts[0])

    # ... playing the hand occupation at the normal Lessons price (P0 already
    # has 1 played occupation — Junior Artist — so the next costs 1 food).
    acts = legal_actions(state)
    assert len(acts) == 1
    commit = acts[0]
    assert isinstance(commit, CommitPlayOccupation) and commit.card_id == "lodger"
    state = step(state, commit)
    p0 = state.players[0]
    assert p0.resources.food == 0                    # the 1-food Lessons price paid
    assert "lodger" in p0.occupations
    assert "lodger" not in p0.hand_occupations

    # Unwind: the play frame's after-window, then the Lessons host's
    # after-window — where the jump is NOT offered (its host filter is Day
    # Laborer only)...
    assert [type(a).__name__ for a in legal_actions(state)] == ["Stop"]
    state = step(state, Stop())                      # pop PendingPlayOccupation
    assert [type(a).__name__ for a in legal_actions(state)] == ["Stop"]
    state = step(state, Stop())                      # pop the Lessons host

    # ... and the walk is back at the SOURCE's after-window: the Day Laborer
    # host, jump already resolved there, only Stop left.
    top = state.pending_stack[-1]
    assert isinstance(top, PendingActionSpace)
    assert top.space_id == "day_laborer"
    assert top.phase == "after"
    assert CARD_ID in top.triggers_resolved
    assert [type(a).__name__ for a in legal_actions(state)] == ["Stop"]
    state = step(state, Stop())

    # Turn over; the ordinal never moved.
    assert not state.pending_stack
    assert state.current_player == 1
    assert placements_this_round(state.players[0]) == 1
    assert placements_this_round(state.players[1]) == 0

    # The vacated Day Laborer is OPEN to the opponent (occupancy is solely
    # worker presence), and using it works normally (unhosted for P1 — the
    # hook is own-use and P1 owns nothing).
    assert PlaceWorker(space="day_laborer") in legal_actions(state)
    p1_food = state.players[1].resources.food
    state = step(state, PlaceWorker(space="day_laborer"))
    assert not state.pending_stack                   # pure atomic for P1
    assert state.players[1].resources.food == p1_food + 2
    assert _workers(state, "day_laborer") == (0, 1)


# ---------------------------------------------------------------------------
# Declining
# ---------------------------------------------------------------------------

def test_declinable():
    state = _to_after_window(_state(food=0))
    assert _ja_triggers(legal_actions(state)) == {"lessons"}
    state = step(state, Stop())                      # decline: just end the turn
    assert not state.pending_stack
    assert state.current_player == 1
    p0 = state.players[0]
    assert p0.resources.food == 2                    # no jump payment
    assert _workers(state, "day_laborer") == (1, 0)  # the worker stayed put
    assert _workers(state, "lessons") == (0, 0)
    assert "lodger" in p0.hand_occupations           # nothing played


# ---------------------------------------------------------------------------
# Destination gates
# ---------------------------------------------------------------------------

def test_lessons_occupied_variant_absent():
    # "an unoccupied ... space", read at the trigger time (ruling 81 item 2).
    state = _state(food=5)
    state = with_space(state, "lessons", workers=(0, 1))
    state = with_people(state, 1, home=1)            # P1's meeple is out on Lessons
    state = _to_after_window(state)
    assert _variants(state, 0) == []
    assert _ja_triggers(legal_actions(state)) == set()
    assert [type(a).__name__ for a in legal_actions(state)] == ["Stop"]


def test_own_worker_on_lessons_also_blocks():
    # Strictly workers-all-zero: the owner's own earlier worker occupies too.
    state = _state(food=5)
    state = with_space(state, "lessons", workers=(1, 0))
    state = with_people(state, 0, home=1)
    state = _to_after_window(state)
    assert _ja_triggers(legal_actions(state)) == set()


def test_no_playable_occupation_variant_absent():
    # Lessons' own action must be legal: with an empty hand there is nothing to
    # play, so the jump would be a dead-end and is not offered.
    state = _to_after_window(_state(food=5, hand=()))
    assert _variants(state, 0) == []
    assert _ja_triggers(legal_actions(state)) == set()
    assert [type(a).__name__ for a in legal_actions(state)] == ["Stop"]


def test_food_gates():
    # The jump needs its 1 food on hand AND must leave the destination usable:
    # the Lessons predicate is evaluated on the post-payment state. P0 owns one
    # occupation (this card), so the Lessons price is 1 food — the jump is
    # offered only from >= 2 food (1 for the jump + 1 for the play).
    state = _to_after_window(_state(food=0))         # 0 + Day Laborer's 2 = 2 food
    assert _ja_triggers(legal_actions(state)) == {"lessons"}

    # Drained to 0 food mid-window (as another card's payment could): no jump.
    broke = with_resources(state, 0, food=0)
    assert _variants(broke, 0) == []
    assert _ja_triggers(legal_actions(broke)) == set()

    # 1 food: the jump itself is payable, but it would strand the worker at
    # Lessons with 0 food against the 1-food occupation cost — never offered.
    one = with_resources(state, 0, food=1)
    assert _variants(one, 0) == []
    assert _ja_triggers(legal_actions(one)) == set()

    # 2 food: both payments covered — offered again.
    two = with_resources(state, 0, food=2)
    assert _variants(two, 0) == ["lessons"]


# ---------------------------------------------------------------------------
# Ownership
# ---------------------------------------------------------------------------

def test_unowned_or_hand_only_does_not_host():
    # A hand card cannot fire: Day Laborer stays a pure atomic placement.
    state = _state(food=0, own=False, hand=("lodger", CARD_ID))
    state = step(state, PlaceWorker(space="day_laborer"))
    assert not state.pending_stack                   # no host, no window, no jump
    assert state.players[0].resources.food == 2
    assert state.current_player == 1
