"""Tests for Throwing Axe (minor A52, Artifex).

Card text: "Each time you use a wood accumulation space while there is at least
1 wild boar on the 'Pig Market' accumulation space, you also get 2 food."
Cost 1 Wood; prereq Play in Round 7 or Later; no VP; not passing.

The +2 food is a `before_action_space` automatic effect on the `forest` space (the
only wood accumulation space). `forest` is atomic, so the card hosts it. The effect
is gated on >=1 boar sitting on the Pig Market accumulation space
(get_space(board, "pig_market").accumulated_amount), not the player's owned boar.
"""
import agricola.cards.throwing_axe  # noqa: F401  (registers the card; not in cards/__init__.py)

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    should_host_space,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space

CARD_ID = "throwing_axe"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, round_number=7):
    s, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(s, round_number=round_number, current_player=0)


def _own(state, idx, minors=(CARD_ID,)):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | set(minors))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_pig_market_boar(state, n):
    sp = get_space(state.board, "pig_market")
    return fast_replace(state, board=with_space(state.board, "pig_market",
                                                fast_replace(sp, accumulated_amount=n)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_minor():
    spec = MINORS[CARD_ID]
    assert spec.cost.resources == Resources(wood=1)
    assert spec.vps == 0
    assert spec.passing_left is False


def test_registered_as_before_hook_on_forest():
    # Hosts the forest space (atomic), and the auto effect is on before_action_space.
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["forest"]
    events = {event for event, entries in AUTO_EFFECTS.items()
              if any(e.card_id == CARD_ID for e in entries)}
    assert events == {"before_action_space"}


# ---------------------------------------------------------------------------
# Round-7 prerequisite (play-time gate)
# ---------------------------------------------------------------------------

def test_prereq_requires_round_7_or_later():
    spec = MINORS[CARD_ID]
    s6 = _card_state(round_number=6)
    s7 = _card_state(round_number=7)
    s9 = _card_state(round_number=9)
    assert not prereq_met(spec, s6, 0)
    assert prereq_met(spec, s7, 0)
    assert prereq_met(spec, s9, 0)


# ---------------------------------------------------------------------------
# The effect via a real forest placement
# ---------------------------------------------------------------------------

def test_grants_two_food_on_forest_with_boar_on_pig_market():
    s = _own(_card_state(), 0)
    s = _set_pig_market_boar(s, 1)
    accumulated = get_space(s.board, "forest").accumulated.wood
    before_food = s.players[0].resources.food
    before_wood = s.players[0].resources.wood

    # Drive the hosted lifecycle: place → before-phase (auto fires) → Proceed → Stop.
    s = step(s, PlaceWorker(space="forest"))
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert s.pending_stack[-1].phase == "before"
    # The +2 food is a choiceless auto applied at hosting → before-phase is a
    # singleton Proceed (no FireTrigger surfaced).
    assert legal_actions(s) == [Proceed()]
    s = step(s, Proceed())
    s = step(s, Stop())
    assert not s.pending_stack

    assert s.players[0].resources.food == before_food + 2          # Throwing Axe
    assert s.players[0].resources.wood == before_wood + accumulated  # normal forest take


def test_no_food_when_no_boar_on_pig_market():
    s = _own(_card_state(), 0)
    s = _set_pig_market_boar(s, 0)            # no boar waiting
    before_food = s.players[0].resources.food

    s = step(s, PlaceWorker(space="forest"))  # still hosted (the card hooks forest)
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    s = step(s, Proceed())
    s = step(s, Stop())

    assert s.players[0].resources.food == before_food  # eligibility failed → no +2


def test_does_not_fire_on_non_wood_accumulation_space():
    # Clay Pit / Reed Bank etc. are accumulation spaces but NOT wood spaces.
    s = _own(_card_state(), 0)
    s = _set_pig_market_boar(s, 3)            # plenty of boar, but wrong space
    before_food = s.players[0].resources.food

    out = step(s, PlaceWorker(space="clay_pit"))
    # throwing_axe does not hook clay_pit → atomic fast path, no host, no food.
    assert not any(isinstance(f, PendingActionSpace) for f in out.pending_stack)
    assert out.players[0].resources.food == before_food


def test_should_host_forest_only_when_owned():
    s = _card_state()
    assert not should_host_space(s, "forest", 0)         # not owned yet
    s = _own(s, 0)
    assert should_host_space(s, "forest", 0)             # owned → hosts forest
    assert not should_host_space(s, "clay_pit", 0)       # but not other wood-less spaces


def test_uses_pig_market_space_boar_not_owned_boar():
    # Owning many boar but with an EMPTY pig market must NOT fire.
    s = _own(_card_state(), 0)
    s = _set_pig_market_boar(s, 0)
    p = fast_replace(s.players[0], animals=s.players[0].animals + _Boar(5))
    s = fast_replace(s, players=(p, s.players[1]))
    before_food = s.players[0].resources.food

    s = step(s, PlaceWorker(space="forest"))
    s = step(s, Proceed())
    s = step(s, Stop())
    assert s.players[0].resources.food == before_food  # owned boar irrelevant


def _Boar(n):
    from agricola.resources import Animals
    return Animals(boar=n)
