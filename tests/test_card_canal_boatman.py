import agricola.cards.canal_boatman  # noqa: F401  (registers the card)

"""Canal Boatman (occupation, deck D #103, [1+]): "Each time you use "Fishing"
or "Reed Bank", you can pay 1 food to immediately place another person on this
card. If you do, you get your choice of 3 stone or 1 grain plus 1 vegetable."
Clarification: "The choices are (3 stone) or (grain+vegetable)."

Rulings under test (ruling 74, 2026-07-21, CARD_DEFERRED_PLANS.md): the card
is an after_action_space trigger (a user-authorized deviation from the
before-default); MULTIPLE workers may be parked in one round (each qualifying
use is a fresh trigger — no once-per-round latch); the parked person is a real
placement for the round (unavailable for later turns, home again at the
returning-home reset, which also sweeps the on-card marker).
"""

from agricola.actions import FireTrigger, PlaceWorker, Proceed, RevealCard, Stop
from agricola.cards.canal_boatman import CARD_ID
from agricola.cards.card_spaces import card_space_worker_count
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import GameMode, Phase
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.setup import setup
from agricola.state import get_space
from tests.factories import with_current_player, with_people, with_resources


def _own(state, idx, card_id=CARD_ID):
    p = state.players[idx]
    p = fast_replace(p, occupations=p.occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))


def _state(*, food=1, own=True, current_player=0):
    """A CARDS-mode state, `current_player` to move (and starting player, so
    round boundaries hand the move back deterministically), that player holding
    exactly `food` food and (by default) owning the card."""
    state = fast_replace(setup(seed=0), mode=GameMode.CARDS, starting_player=0)
    state = with_current_player(state, current_player)
    state = with_resources(state, current_player, food=food)
    if own:
        state = _own(state, current_player)
    return state


def _cb_triggers(opts):
    """The Canal Boatman FireTriggers among legal actions, as a variant set."""
    return {a.variant for a in opts
            if isinstance(a, FireTrigger) and a.card_id == CARD_ID}


def _use_space(state, space_id):
    """Drive one hosted own-space use up to its after window: place + Proceed."""
    state = step(state, PlaceWorker(space=space_id))
    assert [type(a).__name__ for a in legal_actions(state)] == ["Proceed"]
    return step(state, Proceed())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    from agricola.cards.card_spaces import CARD_ACTION_SPACES
    from agricola.cards.triggers import (
        OWN_ACTION_HOOK_CARDS,
        PLAY_VARIANT_TRIGGERS,
        TRIGGERS,
    )
    from agricola.constants import SPACE_IDS
    assert CARD_ID in OCCUPATIONS
    # Optional (never mandatory) trigger on the AFTER window of an action
    # space (ruling 74's user-authorized deviation), never the before window.
    assert any(e.card_id == CARD_ID and not e.mandatory
               for e in TRIGGERS.get("after_action_space", []))
    assert not any(e.card_id == CARD_ID
                   for e in TRIGGERS.get("before_action_space", []))
    assert CARD_ID in PLAY_VARIANT_TRIGGERS
    # Hooked on exactly the two printed spaces, own-use.
    for space_id in SPACE_IDS:
        hooked = CARD_ID in OWN_ACTION_HOOK_CARDS.get(space_id, set())
        assert hooked == (space_id in {"fishing", "reed_bank"})
    # Canal Boatman is NOT an action space: nobody places on it via
    # legal_placements — the marker is pure occupancy bookkeeping.
    assert CARD_ID not in CARD_ACTION_SPACES


# ---------------------------------------------------------------------------
# The real flow: Fishing -> after window -> pay 1 food, park, take 3 stone
# ---------------------------------------------------------------------------

def test_real_flow_fishing_3_stone():
    s = _state(food=1)
    acc = get_space(s.board, "fishing").accumulated_amount
    assert acc >= 1                                  # round-1 stock (the take)
    s = _use_space(s, "fishing")
    # The after window offers BOTH reward variants (the clarification's two
    # choices) alongside Stop.
    assert _cb_triggers(legal_actions(s)) == {"3_stone", "grain_veg"}
    # The acting person's own take already landed at Proceed.
    assert s.players[0].resources.food == 1 + acc
    s = step(s, FireTrigger(card_id=CARD_ID, variant="3_stone"))
    p = s.players[0]
    assert p.resources.food == acc                   # paid 1; take unaffected
    assert p.resources.stone == 3                    # the chosen reward
    assert p.resources.grain == 0 and p.resources.veg == 0
    assert p.people_home == 0                        # the parked person
    assert p.people_total == 2                       # nobody gained or lost
    assert card_space_worker_count(p, CARD_ID) == 1  # on-card worker marker
    # Once per host visit (triggers_resolved): not re-offered; Stop ends it.
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]
    s = step(s, Stop())
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.current_player == 1


def test_grain_veg_variant():
    s = _state(food=1)
    acc = get_space(s.board, "fishing").accumulated_amount
    s = _use_space(s, "fishing")
    s = step(s, FireTrigger(card_id=CARD_ID, variant="grain_veg"))
    p = s.players[0]
    assert p.resources.food == acc                   # paid 1; take unaffected
    assert p.resources.grain == 1 and p.resources.veg == 1
    assert p.resources.stone == 0
    assert card_space_worker_count(p, CARD_ID) == 1


# ---------------------------------------------------------------------------
# Second qualifying use in the SAME round parks a SECOND person (ruling 74:
# each use is a fresh trigger — no once-per-round latch)
# ---------------------------------------------------------------------------

def test_second_use_same_round_parks_second_person():
    s = _state(food=2)
    s = with_people(s, 0, total=4, home=4)
    # Reed Bank is a building-resource accumulation space: its stock lives in
    # `accumulated: Resources` (fishing's food rides `accumulated_amount`).
    acc_reed = get_space(s.board, "reed_bank").accumulated.reed
    # First qualifying use: Fishing -> park.
    s = _use_space(s, "fishing")
    s = step(s, FireTrigger(card_id=CARD_ID, variant="3_stone"))
    assert card_space_worker_count(s.players[0], CARD_ID) == 1
    s = step(s, Stop())
    s = step(s, PlaceWorker(space="clay_pit"))       # P1, atomic (no hook)
    # Second qualifying use, same round: Reed Bank -> a FRESH trigger.
    s = _use_space(s, "reed_bank")
    assert _cb_triggers(legal_actions(s)) == {"3_stone", "grain_veg"}
    s = step(s, FireTrigger(card_id=CARD_ID, variant="grain_veg"))
    p = s.players[0]
    assert card_space_worker_count(p, CARD_ID) == 2  # two parked workers
    assert p.people_home == 0                        # 4 - 2 placed - 2 parked
    assert p.resources.stone == 3 and p.resources.grain == 1 and p.resources.veg == 1
    assert p.resources.reed == acc_reed              # the Reed Bank take landed


# ---------------------------------------------------------------------------
# Eligibility boundaries: no food / nobody home / other spaces / opponent use
# ---------------------------------------------------------------------------

def test_not_offered_without_food():
    # Reed Bank's take grants no food, so 0 food is still 0 at the after
    # window (Fishing can't test this boundary — its own take pays food).
    s = _state(food=0)
    s = _use_space(s, "reed_bank")
    assert _cb_triggers(legal_actions(s)) == set()
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]


def test_not_offered_with_nobody_home():
    # A 1-person player: the acting person is on Fishing, nobody is home to
    # park — no trigger despite ample food.
    s = _state(food=5)
    s = with_people(s, 0, total=1, home=1)
    s = _use_space(s, "fishing")
    assert s.players[0].people_home == 0
    assert _cb_triggers(legal_actions(s)) == set()
    assert [type(a).__name__ for a in legal_actions(s)] == ["Stop"]


def test_other_spaces_not_hosted():
    # Forest is not hooked by this card: the placement stays on the atomic
    # fast path — no host frame, no window, no trigger.
    s = _state(food=5)
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.current_player == 1


def test_opponent_use_not_hosted():
    from agricola.cards.triggers import should_host_space
    s = _state(own=False, current_player=1)
    s = _own(s, 0)                                   # the OWNER is P0; P1 acts
    assert should_host_space(s, "fishing", 0) is True
    assert should_host_space(s, "fishing", 1) is False
    s = step(s, PlaceWorker(space="fishing"))        # atomic: no host
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# Decline path: Stop costs nothing
# ---------------------------------------------------------------------------

def test_decline_via_stop_costs_nothing():
    s = _state(food=1)
    acc = get_space(s.board, "fishing").accumulated_amount
    s = _use_space(s, "fishing")
    assert _cb_triggers(legal_actions(s)) == {"3_stone", "grain_veg"}
    s = step(s, Stop())                              # decline
    p = s.players[0]
    assert p.resources.food == 1 + acc               # the take, nothing paid
    assert p.resources.stone == 0
    assert p.people_home == 1                        # nobody parked
    assert card_space_worker_count(p, CARD_ID) == 0
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


# ---------------------------------------------------------------------------
# The parked person is a real placement: it shortens the owner's round
# ---------------------------------------------------------------------------

def test_parked_person_shortens_round():
    # P0 (2 people): one placement + one park uses everyone in a single turn,
    # so P1 takes the round's remaining two turns back-to-back.
    s = _state(food=1)
    s = _use_space(s, "fishing")
    s = step(s, FireTrigger(card_id=CARD_ID, variant="3_stone"))
    s = step(s, Stop())                              # P0's ONLY turn
    assert s.current_player == 1
    s = step(s, PlaceWorker(space="clay_pit"))       # P1 turn 1
    assert s.current_player == 1                     # P0 skipped: nobody home
    s = step(s, PlaceWorker(space="forest"))         # P1 turn 2 — all placed
    # The round is over: the walk pauses at the round-2 reveal (nature).
    reveals = [a for a in legal_actions(s) if isinstance(a, RevealCard)]
    assert reveals, "expected the round-2 reveal pause"


# ---------------------------------------------------------------------------
# Returning home: the marker is swept, everyone is home, next round is normal
# ---------------------------------------------------------------------------

def test_returning_home_reset_clears_marker():
    s = _state(food=1)
    s = _use_space(s, "fishing")
    s = step(s, FireTrigger(card_id=CARD_ID, variant="3_stone"))
    s = step(s, Stop())
    assert card_space_worker_count(s.players[0], CARD_ID) == 1
    s = step(s, PlaceWorker(space="clay_pit"))       # P1 turn 1
    s = step(s, PlaceWorker(space="forest"))         # P1 turn 2 — all placed
    reveals = [a for a in legal_actions(s) if isinstance(a, RevealCard)]
    assert reveals
    s = step(s, reveals[0])
    assert s.phase is Phase.WORK and s.round_number == 2
    p = s.players[0]
    assert card_space_worker_count(p, CARD_ID) == 0  # marker swept
    assert p.people_home == p.people_total == 2      # everyone home
    # Next round is normal: Fishing refilled, the same flow re-offers.
    s = _use_space(s, "fishing")
    assert _cb_triggers(legal_actions(s)) == {"3_stone", "grain_veg"}
