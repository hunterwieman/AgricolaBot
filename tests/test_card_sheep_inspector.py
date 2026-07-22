import agricola.cards.sheep_inspector  # noqa: F401  (registers the card)

"""Sheep Inspector (occupation, deck D #93, [1+]): "Once per work phase, after
you complete a person action, you can pay 1 sheep and 2 food to return another
person you placed home."

Rulings under test (all 2026-07-21): "after you complete a person action" = the
after_action_space window of the owner's own action (ruling 74); newborns are
NEVER a return target; "once per work phase" = the used_this_round latch;
return semantics mirror Tea Time (people_home +1, the owner's worker marker
decrements, the vacated space is OPEN — occupancy is solely worker presence).
"""

from agricola.actions import FireTrigger, PlaceWorker, Proceed, RevealCard, Stop
from agricola.cards.sheep_inspector import CARD_ID, _variants
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import GameMode, Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import get_space
from tests.factories import (
    with_animals,
    with_current_player,
    with_resources,
    with_space,
)

_URGENT = "urgent_wish_for_children"


def _own(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _state(*, sheep=1, food=2, own=True, current_player=0):
    """A CARDS-mode state, `current_player` to move (and starting player, so
    round boundaries hand the move back deterministically), that player holding
    exactly `sheep` sheep and `food` food and (by default) owning the card."""
    state = fast_replace(setup(seed=0), mode=GameMode.CARDS, starting_player=0)
    state = with_current_player(state, current_player)
    state = with_resources(state, current_player, food=food)
    state = with_animals(state, current_player, sheep=sheep)
    if own:
        state = _own(state, current_player)
    return state


def _si_triggers(opts):
    """The Sheep Inspector FireTriggers among legal actions, as a variant set."""
    return {a.variant for a in opts
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID}


def _use_space(state, space_id):
    """Drive one hosted own-space use up to its after window: place + Proceed."""
    state = step(state, PlaceWorker(space=space_id))
    assert [type(a).__name__ for a in legal_actions(state)] == ["Proceed"]
    return step(state, Proceed())


def _to_second_after_window(state):
    """P0: Forest (no target -> Stop through the after window); P1: Clay Pit
    (atomic); P0: Grain Seeds -> its after window, where Forest holds P0's
    other placed person. Returns that after-window state."""
    state = _use_space(state, "forest")
    assert _si_triggers(legal_actions(state)) == set()   # no other placed person
    state = step(state, Stop())
    state = step(state, PlaceWorker(space="clay_pit"))   # P1, atomic (no hook)
    return _use_space(state, "grain_seeds")


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    from agricola.cards.triggers import (
        OWN_ACTION_HOOK_CARDS,
        PLAY_VARIANT_TRIGGERS,
        TRIGGERS,
    )
    from agricola.constants import SPACE_IDS
    assert CARD_ID in OCCUPATIONS
    # optional (never mandatory) trigger on the AFTER window of an action space
    assert any(e.card_id == CARD_ID and not e.mandatory
               for e in TRIGGERS.get("after_action_space", []))
    assert not any(e.card_id == CARD_ID
                   for e in TRIGGERS.get("before_action_space", []))
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    # hooked over EVERY canonical space id, own-use
    for space_id in SPACE_IDS:
        assert CARD_ID in OWN_ACTION_HOOK_CARDS.get(space_id, set())


# ---------------------------------------------------------------------------
# The real flow: pay 1 sheep + 2 food, the person comes home, the space opens
# ---------------------------------------------------------------------------

def test_real_flow_return_grain_seeds_person():
    # Grain Seeds first (a permanent supply space — placeable whenever open, so
    # the reopened-space check below runs through the real legality path; a
    # vacated ACCUMULATION space is also open but stays out of legal placements
    # while its stock is empty), then Forest as the second, firing action.
    s = _state(sheep=1, food=2)
    s = _use_space(s, "grain_seeds")
    assert _si_triggers(legal_actions(s)) == set()   # no other placed person
    s = step(s, Stop())
    s = step(s, PlaceWorker(space="clay_pit"))       # P1, atomic (no hook)
    s = _use_space(s, "forest")
    # Exactly one target: the Grain Seeds person ("another person you placed").
    assert _si_triggers(legal_actions(s)) == {"grain_seeds"}
    s = step(s, FireTrigger(card_id=CARD_ID, variant="grain_seeds"))
    p = s.players[0]
    assert p.animals.sheep == 0            # 1 sheep paid (from the farm)
    assert p.resources.food == 0           # 2 food paid
    assert p.people_home == 1              # the person is home again
    assert p.people_total == 2             # nobody gained or lost
    assert get_space(s.board, "grain_seeds").workers == (0, 0)   # marker gone
    # Once per use on the same host: not re-offered; Stop ends the turn.
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]
    s = step(s, Stop())
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)

    # The vacated space is OPEN (occupancy is solely worker presence): after
    # the opponent moves, the RETURNED person may be placed on it again.
    s = step(s, PlaceWorker(space="fishing"))              # P1, atomic
    assert s.current_player == 0
    assert PlaceWorker(space="grain_seeds") in legal_actions(s)
    s = _use_space(s, "grain_seeds")                       # place it again
    assert get_space(s.board, "grain_seeds").workers == (1, 0)


# ---------------------------------------------------------------------------
# Once per work phase: latched for the round, fresh again next round
# ---------------------------------------------------------------------------

def test_once_per_work_phase_and_fresh_next_round():
    s = _state(sheep=2, food=6)
    s = _to_second_after_window(s)
    assert _si_triggers(legal_actions(s)) == {"forest"}
    s = step(s, FireTrigger(card_id=CARD_ID, variant="forest"))
    assert CARD_ID in s.players[0].used_this_round
    s = step(s, Stop())

    # P1's second person; then P0 places the returned person. A target exists
    # (the Grain Seeds person), sheep (1) and food (4) suffice — only the
    # once-per-work-phase latch blocks the second offer.
    s = step(s, PlaceWorker(space="fishing"))              # P1, atomic
    s = _use_space(s, "day_laborer")                       # P0's returned person
    assert s.players[0].animals.sheep == 1
    assert s.players[0].resources.food >= 2
    assert get_space(s.board, "grain_seeds").workers[0] == 1   # target exists
    assert _si_triggers(legal_actions(s)) == set()             # latched
    s = step(s, Stop())

    # All people placed -> the round ends; the reveal is nature's step.
    reveals = [a for a in legal_actions(s) if isinstance(a, RevealCard)]
    assert reveals, "expected the round-2 reveal pause"
    s = step(s, reveals[0])
    assert s.phase is Phase.WORK and s.round_number == 2
    assert CARD_ID not in s.players[0].used_this_round     # latch cleared

    # Fresh work phase: the same shape is offered again.
    s = _to_second_after_window(s)
    assert _si_triggers(legal_actions(s)) == {"forest"}


# ---------------------------------------------------------------------------
# Newborn exclusion: grow at a wish space; the parent is a target, the newborn
# never is
# ---------------------------------------------------------------------------

def test_newborn_never_a_target_parent_is():
    s = _state(sheep=1, food=2)
    s = with_space(s, _URGENT, revealed=True)
    # P0 grows at Urgent Wish: parent + newborn both sit on the space.
    s = _use_space(s, _URGENT)
    assert get_space(s.board, _URGENT).workers == (2, 0)
    assert s.players[0].newborns == 1 and s.players[0].people_total == 3
    assert _si_triggers(legal_actions(s)) == set()   # own host space excluded
    s = step(s, Stop())
    s = step(s, PlaceWorker(space="clay_pit"))       # P1, atomic
    s = _use_space(s, "grain_seeds")                 # P0's second person

    # ONE returnable person on the wish space (the placed parent) — the
    # newborn meeple contributes nothing.
    assert _si_triggers(legal_actions(s)) == {_URGENT}
    s = step(s, FireTrigger(card_id=CARD_ID, variant=_URGENT))
    p = s.players[0]
    assert p.animals.sheep == 0 and p.resources.food == 0
    assert p.people_home == 1                        # the PARENT came home
    assert p.newborns == 1 and p.people_total == 3   # the newborn did not
    assert get_space(s.board, _URGENT).workers == (1, 0)   # newborn stays put

    # White-box: with only the lone newborn left on the wish space, the
    # derivation counts NO returnable person there (and the just-used Grain
    # Seeds person is excluded as the host's own) — no target remains.
    assert _variants(s, 0) == []

    # The newborn's meeple keeps the wish space occupied for placement.
    s = step(s, Stop())
    assert s.current_player == 1
    assert PlaceWorker(space=_URGENT) not in legal_actions(s)


# ---------------------------------------------------------------------------
# "Another person": the just-used space is never a target
# ---------------------------------------------------------------------------

def test_just_used_space_never_a_target():
    s = _state(sheep=1, food=2)
    # First placement: the only own person on the board is on the host space
    # itself -> the trigger is not offered at all.
    s = _use_space(s, "forest")
    assert _si_triggers(legal_actions(s)) == set()
    s = step(s, Stop())
    s = step(s, PlaceWorker(space="clay_pit"))       # P1, atomic
    # Second placement: only the OTHER person's space is offered — never the
    # just-used Grain Seeds, though the owner has a person there too.
    s = _use_space(s, "grain_seeds")
    assert _si_triggers(legal_actions(s)) == {"forest"}


# ---------------------------------------------------------------------------
# Eligibility boundaries: no sheep / short food / no other placed person
# ---------------------------------------------------------------------------

def test_not_offered_without_a_sheep():
    s = _state(sheep=0, food=5)
    s = _to_second_after_window(s)
    assert _si_triggers(legal_actions(s)) == set()


def test_not_offered_with_one_food():
    s = _state(sheep=2, food=1)
    s = _to_second_after_window(s)
    assert _si_triggers(legal_actions(s)) == set()


def test_not_offered_with_no_other_placed_person():
    # Covered structurally inside the flow helpers; assert it standalone: the
    # first placement's after window (resources ample) offers nothing.
    s = _state(sheep=3, food=9)
    s = _use_space(s, "forest")
    assert _si_triggers(legal_actions(s)) == set()
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]


# ---------------------------------------------------------------------------
# Decline path: Stop costs nothing
# ---------------------------------------------------------------------------

def test_decline_via_stop_costs_nothing():
    s = _state(sheep=1, food=2)
    s = _to_second_after_window(s)
    assert _si_triggers(legal_actions(s)) == {"forest"}
    s = step(s, Stop())                              # decline
    p = s.players[0]
    assert p.animals.sheep == 1
    assert p.resources.food == 2
    assert p.people_home == 0                        # nobody returned
    assert CARD_ID not in p.used_this_round          # a decline is not a use
    assert get_space(s.board, "forest").workers == (1, 0)
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# Own use only; a hand card is inert
# ---------------------------------------------------------------------------

def test_opponent_use_not_hosted():
    from agricola.cards.triggers import should_host_space
    s = _state(own=False, current_player=1)
    s = _own(s, 0)                                   # the OWNER is P0; P1 acts
    assert should_host_space(s, "grain_seeds", 0) is True
    assert should_host_space(s, "grain_seeds", 1) is False
    s = step(s, PlaceWorker(space="grain_seeds"))    # atomic: no host, no trigger
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


def test_hand_card_does_not_host():
    from agricola.cards.triggers import should_host_space
    s = _state(own=False)
    p = s.players[0]
    s = fast_replace(s, players=(fast_replace(
        p, hand_occupations=frozenset({CARD_ID})), s.players[1]))
    assert should_host_space(s, "grain_seeds", 0) is False
    s = step(s, PlaceWorker(space="grain_seeds"))    # atomic
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# Card-space return: the worker parked on Canal Boatman (ruling 74)
# ---------------------------------------------------------------------------

def test_returns_canal_boatman_parked_worker():
    """USER RULING (2026-07-21, ruling 74, CARD_DEFERRED_PLANS.md): Sheep
    Inspector CAN return the worker parked on Canal Boatman. Surfaced as the
    "card:canal_boatman" variant; returning = on-card marker -1,
    people_home +1 (the Tea Time semantics via return_card_space_worker)."""
    import agricola.cards.canal_boatman  # noqa: F401  (registers the card)
    from agricola.cards.canal_boatman import CARD_ID as CB
    from agricola.cards.card_spaces import card_space_worker_count

    s = _state(sheep=1, food=3)          # 1 food for the park + 2 for the return
    s = _own(s, 0, card_id=CB)           # P0 also owns Canal Boatman
    acc = get_space(s.board, "fishing").accumulated_amount
    s = _use_space(s, "fishing")         # both cards hook Fishing -> hosted
    # Before the park there is no return target (the only own person on a
    # space is on the just-used host itself) -> Sheep Inspector is silent.
    assert _si_triggers(legal_actions(s)) == set()
    # Park a person on Canal Boatman (pay 1 food, take 3 stone).
    s = step(s, FireTrigger(card_id=CB, variant="3_stone"))
    assert card_space_worker_count(s.players[0], CB) == 1
    assert s.players[0].people_home == 0
    # The parked worker is now the one legal return target, in card form.
    assert _si_triggers(legal_actions(s)) == {"card:canal_boatman"}
    s = step(s, FireTrigger(card_id=CARD_ID, variant="card:canal_boatman"))
    p = s.players[0]
    assert p.animals.sheep == 0                       # 1 sheep paid
    assert p.resources.food == acc                    # 3 + take - 1 (park) - 2
    assert card_space_worker_count(p, CB) == 0        # marker off the card
    assert p.people_home == 1                         # the parked person is home
    assert p.people_total == 2                        # nobody gained or lost
    assert CARD_ID in p.used_this_round               # once per work phase
    # Both triggers spent for this host visit: Stop ends the turn.
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]
