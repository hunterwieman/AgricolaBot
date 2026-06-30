"""Tests for Excavator (occupation, C126; Consul Dirigens Expansion).

Card text: "Each time after you use the 'Day Laborer' action space, you get 1
additional wood and clay, and you can buy 1 stone for 1 food."
Clarification: "These resources may not be used to pay for the effect of the
Cottager B087."

Shape: a MANDATORY automatic +1 wood +1 clay (register_auto) AND an OPTIONAL
"buy 1 stone for 1 food" FireTrigger (register), both on the after-phase of the
atomic-hosted Day Laborer space (which grants +2 food on Proceed). The auto fires
choicelessly at the after-phase flip; the buy is surfaced as a FireTrigger that the
player may decline (the host's Stop), gated on once-per-use + having ≥ 1 food.
"""
import agricola.cards.excavator  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import (
    AUTO_EFFECTS,
    OWN_ACTION_HOOK_CARDS,
    TRIGGERS,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from tests.factories import with_resources

CARD_ID = "excavator"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _card_state(seed=5, *, owned=True):
    """Round-1 WORK card state with P0 as current player, optionally owning the card."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = fast_replace(cs, current_player=0)
    if owned:
        p = cs.players[0]
        cs = fast_replace(cs, players=tuple(
            fast_replace(p, occupations=frozenset({CARD_ID})) if i == 0 else cs.players[i]
            for i in range(2)))
    return cs, 0


def _place_day_laborer_to_after(state):
    """Place P0 at Day Laborer and Proceed past the +2-food pickup so the host frame
    is in its after-phase (where the auto has fired and the buy trigger is surfaced)."""
    state = step(state, PlaceWorker(space="day_laborer"))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())                 # +2 food, flip to after; auto fires
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_excavator_registered():
    assert CARD_ID in OCCUPATIONS
    # Mandatory +1 wood/clay is an automatic after-effect.
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("after_action_space", ())}
    assert CARD_ID in auto_ids
    # The optional stone-buy is an after_action_space FireTrigger.
    trig_ids = {e.card_id for e in TRIGGERS.get("after_action_space", ())}
    assert CARD_ID in trig_ids
    # Day Laborer is atomic → it must be explicitly hosted.
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("day_laborer", set())


# ---------------------------------------------------------------------------
# Mandatory +1 wood +1 clay (auto, never surfaced)
# ---------------------------------------------------------------------------

def test_auto_grants_one_wood_one_clay():
    s, cp = _card_state()
    s = with_resources(s, cp, wood=0, clay=0, food=0)
    before_food = s.players[cp].resources.food
    s = step(s, PlaceWorker(space="day_laborer"))
    assert s.pending_stack[-1].phase == "before"
    # The +1 wood/clay are NOT granted before the space resolves.
    assert s.players[cp].resources.wood == 0
    assert s.players[cp].resources.clay == 0
    s = step(s, Proceed())                          # +2 food pickup, flip, auto fires
    assert s.pending_stack[-1].phase == "after"
    assert s.players[cp].resources.wood == 1        # +1 wood
    assert s.players[cp].resources.clay == 1        # +1 clay
    assert s.players[cp].resources.food == before_food + 2  # Day Laborer's +2 food only


def test_auto_fires_and_buy_offered_after_pickup():
    # Day Laborer grants +2 food, so even starting at 0 food the player can afford the
    # buy after the pickup; the auto wood/clay fires regardless.
    s, cp = _card_state()
    s = with_resources(s, cp, wood=0, clay=0, food=0)
    s = _place_day_laborer_to_after(s)
    assert s.players[cp].resources.wood == 1
    assert s.players[cp].resources.clay == 1
    assert s.players[cp].resources.food == 2        # +2 pickup
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    assert Stop() in legal_actions(s)


def test_buy_not_offered_when_no_food_at_after_phase():
    # The food>=1 eligibility boundary: force the after-phase supply to 0 food (a
    # state the +2 pickup wouldn't produce on its own) → the buy is NOT offered, but
    # the host Stop still is. Exercises that the buy never offers a dead-end. Drain
    # only food, preserving the auto-granted wood/clay.
    s, cp = _card_state()
    s = _place_day_laborer_to_after(s)
    assert s.players[cp].resources.wood == 1 and s.players[cp].resources.clay == 1
    p = s.players[cp]
    p = fast_replace(p, resources=fast_replace(p.resources, food=0))
    s = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    assert Stop() in legal_actions(s)
    # The mandatory wood/clay (fired at the flip) is untouched by the food drain.
    assert s.players[cp].resources.wood == 1
    assert s.players[cp].resources.clay == 1


# ---------------------------------------------------------------------------
# Optional buy 1 stone for 1 food — the real-flow effect
# ---------------------------------------------------------------------------

def test_buy_offered_with_food_and_fires():
    s, cp = _card_state()
    s = with_resources(s, cp, wood=0, clay=0, stone=0, food=3)
    s = _place_day_laborer_to_after(s)
    # Auto already applied; Day Laborer gave +2 food (3 + 2 = 5).
    assert s.players[cp].resources.food == 5
    assert s.players[cp].resources.stone == 0
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Stop() in la                             # declining is also available
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[cp].resources.food == 4        # -1 food
    assert s.players[cp].resources.stone == 1       # +1 stone
    # After firing, the buy is once-per-use → not re-offered; only the host Stop.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)
    s = step(s, Stop())
    assert s.pending_stack == ()


# ---------------------------------------------------------------------------
# Optionality — declining = not firing (Stop exits without spending)
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_stop():
    s, cp = _card_state()
    s = with_resources(s, cp, stone=0, food=3)
    s = _place_day_laborer_to_after(s)
    food_after_pickup = s.players[cp].resources.food
    s = step(s, Stop())                             # decline → host exits, turn ends
    assert s.pending_stack == ()
    assert s.players[cp].resources.food == food_after_pickup  # no food spent
    assert s.players[cp].resources.stone == 0       # no stone bought
    # The mandatory wood/clay still happened.
    assert s.players[cp].resources.wood == 1
    assert s.players[cp].resources.clay == 1


# ---------------------------------------------------------------------------
# Eligibility boundary — does NOT fire on an unrelated space
# ---------------------------------------------------------------------------

def test_does_not_fire_on_unrelated_space():
    # Owns excavator; uses Forest (not Day Laborer). Forest is atomic and excavator
    # does not hook it, so it stays on the atomic fast path: no host, no +1 wood/clay.
    s, cp = _card_state()
    s = with_resources(s, cp, wood=0, clay=0, food=3)
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("forest", set())
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    # Forest grants +3 wood (its own pickup) but NOT the excavator +1 clay.
    assert s.players[cp].resources.clay == 0


def test_opponents_excavator_does_not_fire_on_my_day_laborer():
    # Only the ACTING player's owned hook fires (any_player=False default).
    s, cp = _card_state(owned=False)
    opp = 1 - cp
    s = fast_replace(s, players=tuple(
        fast_replace(s.players[opp], occupations=frozenset({CARD_ID})) if i == opp
        else s.players[i] for i in range(2)))
    s = with_resources(s, cp, wood=0, clay=0, food=0)
    before_opp_wood = s.players[opp].resources.wood
    s = step(s, PlaceWorker(space="day_laborer"))
    # cp does NOT own excavator → Day Laborer is not hosted for cp's use.
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.players[cp].resources.wood == 0        # acting player: no +1 wood
    assert s.players[cp].resources.clay == 0
    assert s.players[opp].resources.wood == before_opp_wood  # opponent: no +1 either
