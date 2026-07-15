"""Tests for Fir Cutter (occupation E116, Ephipparius).

Card text: "When you play this card, you immediately get 1 food. Each time
after you use an animal accumulation space with your 1st/2nd/3rd/4th/5th
person, you get 1/1/2/2/3 wood."

On play: +1 food. Recurring: an `after_action_space` automatic effect gated to
the three animal accumulation spaces (sheep_market / pig_market / cattle_market
— all non-atomic + self-hosting, so NO action-space hook). The wood amount is
keyed to which of the owner's people this placement was, this round: the Nth
person placed pays [1,1,2,2,3][N-1] wood. The ordinal is Catcher's idiom,
`(people_total − newborns) − people_home`, read at the after window (the
placement has already decremented `people_home`). Under the deferred after-flip
(ruling 60) the wood lands only after the market's full effect — including its
accommodation frontier — has resolved.
"""
import agricola.cards.fir_cutter  # noqa: F401  (registers the card before cards/__init__)

from agricola.actions import PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    ANY_PLAYER_HOOK_CARDS,
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    apply_auto_effects,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace, PendingSheepMarket, push
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD_ID = "fir_cutter"

MARKETS = ("sheep_market", "pig_market", "cattle_market")

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _own(state, idx):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {CARD_ID})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _with_people(state, idx, *, total, home, newborns=0):
    p = fast_replace(state.players[idx], people_total=total, people_home=home,
                     newborns=newborns)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reveal_market(state, space_id, amount=1):
    """Turn a stage market face-up (sheep=stage 1, pig=stage 3, cattle=stage 4)
    and stock it with `amount` animals, as the existing market tests do."""
    sp = get_space(state.board, space_id)
    return fast_replace(state, board=with_space(
        state.board, space_id,
        fast_replace(sp, revealed=True, accumulated_amount=amount)))


def _run_turn(s):
    steps = 0
    while s.pending_stack and steps < 30:
        s = step(s, legal_actions(s)[0])
        steps += 1
    return s


def _place_and_finish(state, space_id):
    state = step(state, PlaceWorker(space=space_id))
    return _run_turn(state)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_occupation():
    assert CARD_ID in OCCUPATIONS


def test_registered_as_after_action_space_auto_only():
    events = {event for event, entries in AUTO_EFFECTS.items()
              if any(e.card_id == CARD_ID for e in entries)}
    assert events == {"after_action_space"}
    entry = next(e for e in AUTO_EFFECTS["after_action_space"]
                 if e.card_id == CARD_ID)
    assert not entry.any_player                    # "you use" — owner's use only


def test_no_action_space_hook_registered():
    # The three markets are non-atomic + self-hosting: no hook may be registered
    # (and none for any other space either).
    for sid in MARKETS:
        assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get(sid, set())
        assert CARD_ID not in ANY_PLAYER_HOOK_CARDS.get(sid, set())
    s = _own(_card_state(), 0)
    assert not should_host_space(s, "sheep_market", 0)


# ---------------------------------------------------------------------------
# On play: +1 food
# ---------------------------------------------------------------------------

def test_on_play_grants_1_food():
    s = _own(_card_state(), 0)
    before = s.players[0].resources
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources == before + Resources(food=1)
    assert out.players[1].resources == s.players[1].resources


# ---------------------------------------------------------------------------
# The wood ladder — Nth person placed this round -> 1/1/2/2/3 wood
# ---------------------------------------------------------------------------

def test_first_person_pays_1_wood_after_sheep_market():
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=2, home=2)        # nobody placed yet -> 1st person
    s = _reveal_market(s, "sheep_market", 1)
    wood0 = s.players[0].resources.wood

    # AFTER-window pin: at the host push (before-phase) no wood has landed yet —
    # the grant fires only once the market's full effect (accommodation) resolves.
    s = step(s, PlaceWorker(space="sheep_market"))
    assert isinstance(s.pending_stack[-1], PendingSheepMarket)
    assert s.pending_stack[-1].phase == "before"
    assert s.players[0].resources.wood == wood0

    s = _run_turn(s)
    assert s.players[0].resources.wood == wood0 + 1


def test_second_person_pays_1_wood_after_pig_market():
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=2, home=1)        # 1 already placed -> 2nd person
    s = _reveal_market(s, "pig_market", 1)
    wood0 = s.players[0].resources.wood
    s = _place_and_finish(s, "pig_market")
    assert s.players[0].resources.wood == wood0 + 1


def test_third_person_pays_2_wood_after_cattle_market():
    # Family grown to 3; two workers already placed this round -> 3rd person.
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=3, home=1)
    s = _reveal_market(s, "cattle_market", 1)
    wood0 = s.players[0].resources.wood
    s = _place_and_finish(s, "cattle_market")
    assert s.players[0].resources.wood == wood0 + 2


def test_fourth_person_pays_2_wood():
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=5, home=2)        # 3 already placed -> 4th person
    s = _reveal_market(s, "sheep_market", 1)
    wood0 = s.players[0].resources.wood
    s = _place_and_finish(s, "sheep_market")
    assert s.players[0].resources.wood == wood0 + 2


def test_fifth_person_pays_3_wood():
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=5, home=1)        # 4 already placed -> 5th person
    s = _reveal_market(s, "sheep_market", 1)
    wood0 = s.players[0].resources.wood
    s = _place_and_finish(s, "sheep_market")
    assert s.players[0].resources.wood == wood0 + 3


def test_empty_market_still_pays():
    # The trigger is USING the space, not gaining animals: an empty (0-animal)
    # market use still pays the ordinal's wood.
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=2, home=2)
    s = _reveal_market(s, "sheep_market", 0)
    wood0 = s.players[0].resources.wood
    s = _place_and_finish(s, "sheep_market")
    assert s.players[0].resources.wood == wood0 + 1


# ---------------------------------------------------------------------------
# Same-round newborn must NOT inflate the person ordinal (the `- newborns` term:
# a Wish-for-Children birth bumps people_total but not people_home).
# ---------------------------------------------------------------------------

def test_same_round_newborn_does_not_inflate_ordinal():
    # 1 real worker placed this round + a same-round newborn (people_total bumped
    # to 3, newborns=1, people_home NOT bumped). Placing the 2nd real WORKER is
    # the 2nd-person ordinal -> 1 wood. Without `- newborns` the ordinal would
    # read 3 and wrongly pay 2.
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=3, home=1, newborns=1)
    s = _reveal_market(s, "sheep_market", 1)
    wood0 = s.players[0].resources.wood
    s = _place_and_finish(s, "sheep_market")
    assert s.players[0].resources.wood == wood0 + 1


# ---------------------------------------------------------------------------
# Space gating + ownership
# ---------------------------------------------------------------------------

def test_no_wood_after_forest():
    # Forest is a wood accumulation space, not an animal one: the take is exactly
    # the accumulated wood, no Fir Cutter bonus (and no host frame — fir_cutter
    # registers no hook, so an owned-only board keeps forest on the atomic path).
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=2, home=2)
    sp = get_space(s.board, "forest")
    s = fast_replace(s, board=with_space(
        s.board, "forest", fast_replace(sp, accumulated=Resources(wood=3))))
    wood0 = s.players[0].resources.wood
    out = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    out = _run_turn(out)
    assert out.players[0].resources.wood == wood0 + 3   # the space's own 3, nothing more


def test_opponent_market_use_pays_nothing():
    # P1 owns Fir Cutter; P0 (active) uses the Sheep Market — nobody gains wood.
    s = _card_state()
    s = _own(s, 1)
    s = _with_people(s, 0, total=2, home=2)
    s = _reveal_market(s, "sheep_market", 1)
    w0, w1 = s.players[0].resources.wood, s.players[1].resources.wood
    s = _place_and_finish(s, "sheep_market")
    assert s.players[0].resources.wood == w0
    assert s.players[1].resources.wood == w1


def test_hand_only_is_inert():
    # The card sitting in the owner's HAND (not played) must not fire.
    s = _card_state()
    p = fast_replace(s.players[0],
                     hand_occupations=s.players[0].hand_occupations | {CARD_ID})
    s = fast_replace(s, players=(p, s.players[1]))
    s = _with_people(s, 0, total=2, home=2)
    s = _reveal_market(s, "sheep_market", 1)
    wood0 = s.players[0].resources.wood
    s = _place_and_finish(s, "sheep_market")
    assert s.players[0].resources.wood == wood0


# ---------------------------------------------------------------------------
# Eligibility scoped to the animal markets (driven via apply_auto_effects)
# ---------------------------------------------------------------------------

def test_eligibility_rejects_non_market_host_frame():
    # A market-class frame whose space_id is NOT an animal market must not fire.
    s = _own(_card_state(), 0)
    s = _with_people(s, 0, total=2, home=1)
    s = push(s, PendingSheepMarket(
        player_idx=0, initiated_by_id="space:grain_seeds", gained=0, phase="after"))
    wood0 = s.players[0].resources.wood
    out = apply_auto_effects(s, "after_action_space", 0)
    assert out.players[0].resources.wood == wood0


def test_eligibility_accepts_each_market_frame():
    for sid in MARKETS:
        s = _own(_card_state(), 0)
        s = _with_people(s, 0, total=2, home=1)     # 1st person placed
        s = push(s, PendingSheepMarket(
            player_idx=0, initiated_by_id=f"space:{sid}", gained=0, phase="after"))
        wood0 = s.players[0].resources.wood
        out = apply_auto_effects(s, "after_action_space", 0)
        assert out.players[0].resources.wood == wood0 + 1, sid
