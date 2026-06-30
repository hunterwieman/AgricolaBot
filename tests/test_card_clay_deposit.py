"""Tests for Clay Deposit (minor improvement, C36; Corbarius Expansion).

Card text: "Immediately after each time you use a clay accumulation space, you can
exchange 1 clay for 1 bonus point. If you do, place the clay on the accumulation
space."
Prerequisite: "1 Occupation". Cost: 2 Food. Printed 0 VP.

Shape: an OPTIONAL "exchange 1 clay for 1 bonus point" FireTrigger (register) on
the after-phase of the atomic-hosted Clay Pit accumulation space (which grants its
accumulated clay on Proceed). The buy is surfaced as a FireTrigger the player may
decline (the host's Stop), gated on once-per-use + having >= 1 clay. When fired it
spends 1 clay, banks 1 bonus point in CardStore, and returns the spent clay to the
space's accumulated goods; the point is read at scoring via register_scoring.
"""
import agricola.cards.clay_deposit  # noqa: F401  (registers the card)

from agricola.actions import FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS
from agricola.cards.triggers import OWN_ACTION_HOOK_CARDS, TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources

CARD_ID = "clay_deposit"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _scorer():
    """The registered scoring fn for this card."""
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


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
            fast_replace(p, minor_improvements=frozenset({CARD_ID})) if i == 0
            else cs.players[i] for i in range(2)))
    return cs, 0


def _place_clay_pit_to_after(state):
    """Place P0 at Clay Pit and Proceed past the accumulated-clay pickup so the host
    frame is in its after-phase (where the exchange trigger is surfaced)."""
    state = step(state, PlaceWorker(space="clay_pit"))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    state = step(state, Proceed())                 # pick up accumulated clay, flip to after
    assert state.pending_stack[-1].phase == "after"
    return state


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_clay_deposit_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(food=2))
    assert spec.min_occupations == 1            # prereq "1 Occupation"
    # The optional exchange is an after_action_space FireTrigger.
    trig_ids = {e.card_id for e in TRIGGERS.get("after_action_space", ())}
    assert CARD_ID in trig_ids
    # Clay Pit is atomic → it must be explicitly hosted.
    assert CARD_ID in OWN_ACTION_HOOK_CARDS.get("clay_pit", set())
    # Banked bonus point read at scoring.
    assert CARD_ID in {cid for cid, _ in SCORING_TERMS}


# ---------------------------------------------------------------------------
# The real-flow effect: exchange 1 clay for 1 bonus point, clay returned to space
# ---------------------------------------------------------------------------

def test_exchange_offered_with_clay_and_fires():
    s, cp = _card_state()
    s = with_resources(s, cp, clay=0)
    accumulated = get_space(s.board, "clay_pit").accumulated.clay
    assert accumulated >= 1                          # round-1 clay_pit holds clay to take
    s = _place_clay_pit_to_after(s)
    # Picked up the accumulated clay; the space is now empty of clay.
    assert s.players[cp].resources.clay == accumulated
    assert get_space(s.board, "clay_pit").accumulated.clay == 0
    assert s.players[cp].card_state.get(CARD_ID, 0) == 0

    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) in la
    assert Stop() in la                             # declining is also available

    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[cp].resources.clay == accumulated - 1     # -1 clay spent
    assert s.players[cp].card_state.get(CARD_ID, 0) == 1       # +1 banked bonus point
    # "place the clay on the accumulation space" — the spent clay is returned.
    assert get_space(s.board, "clay_pit").accumulated.clay == 1
    # Once-per-use → not re-offered after firing; only the host Stop remains.
    assert FireTrigger(card_id=CARD_ID) not in legal_actions(s)

    s = step(s, Stop())
    assert s.pending_stack == ()
    # The bonus point is worth +1 VP at scoring.
    assert _scorer()(s, cp) == 1


# ---------------------------------------------------------------------------
# Eligibility boundary: not offered without clay to exchange
# ---------------------------------------------------------------------------

def test_exchange_not_offered_when_no_clay_at_after_phase():
    # Force the after-phase clay to 0 (a state the pickup wouldn't produce here):
    # drain clay AFTER the pickup → exchange NOT offered, but the host Stop still is.
    s, cp = _card_state()
    s = _place_clay_pit_to_after(s)
    p = s.players[cp]
    p = fast_replace(p, resources=fast_replace(p.resources, clay=0))
    s = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    la = legal_actions(s)
    assert FireTrigger(card_id=CARD_ID) not in la    # never offers a dead-end
    assert Stop() in la


# ---------------------------------------------------------------------------
# Optionality — declining = not firing (Stop exits without spending)
# ---------------------------------------------------------------------------

def test_optional_can_decline_via_stop():
    s, cp = _card_state()
    s = with_resources(s, cp, clay=0)
    accumulated = get_space(s.board, "clay_pit").accumulated.clay
    s = _place_clay_pit_to_after(s)
    clay_after_pickup = s.players[cp].resources.clay
    s = step(s, Stop())                             # decline → host exits, turn ends
    assert s.pending_stack == ()
    assert s.players[cp].resources.clay == clay_after_pickup   # no clay spent
    assert s.players[cp].card_state.get(CARD_ID, 0) == 0       # no point banked
    assert _scorer()(s, cp) == 0
    # Clay was not returned to the space (nothing was exchanged).
    assert get_space(s.board, "clay_pit").accumulated.clay == 0


# ---------------------------------------------------------------------------
# Scoping: once per Clay Pit ACTION (a fresh frame re-enables the exchange)
# ---------------------------------------------------------------------------

def test_once_per_action_resets_across_two_clay_pit_uses():
    # Use Clay Pit twice in the same game; each use should re-offer the exchange
    # (triggers_resolved is per-frame, freshly empty each action).
    s, cp = _card_state()
    s = with_resources(s, cp, clay=0)

    # First Clay Pit use → fire the exchange.
    s = _place_clay_pit_to_after(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[cp].card_state.get(CARD_ID, 0) == 1
    s = step(s, Stop())

    # Hand the worker placement back to P0 (skip the opponent's turn for the test).
    s = fast_replace(s, current_player=cp)
    # Reseed the space with clay so a second take is meaningful.
    sp = get_space(s.board, "clay_pit")
    sp = fast_replace(sp, accumulated=sp.accumulated + Resources(clay=2))
    s = fast_replace(s, board=with_space(s.board, "clay_pit", sp))

    # Second Clay Pit use → the exchange is offered again (fresh frame).
    s = _place_clay_pit_to_after(s)
    assert FireTrigger(card_id=CARD_ID) in legal_actions(s)
    s = step(s, FireTrigger(card_id=CARD_ID))
    assert s.players[cp].card_state.get(CARD_ID, 0) == 2       # banked twice total


# ---------------------------------------------------------------------------
# Eligibility boundary — does NOT fire on an unrelated space
# ---------------------------------------------------------------------------

def test_does_not_fire_on_unrelated_space():
    # Owns clay_deposit; uses Forest (not Clay Pit). Forest is atomic and
    # clay_deposit does not hook it, so it stays on the atomic fast path: no host.
    s, cp = _card_state()
    s = with_resources(s, cp, clay=0)
    assert CARD_ID not in OWN_ACTION_HOOK_CARDS.get("forest", set())
    s = step(s, PlaceWorker(space="forest"))
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.players[cp].card_state.get(CARD_ID, 0) == 0       # nothing banked


def test_opponents_clay_deposit_does_not_fire_on_my_clay_pit():
    # Only the ACTING player's owned hook fires (any_player=False default).
    s, cp = _card_state(owned=False)
    opp = 1 - cp
    s = fast_replace(s, players=tuple(
        fast_replace(s.players[opp], minor_improvements=frozenset({CARD_ID})) if i == opp
        else s.players[i] for i in range(2)))
    s = with_resources(s, cp, clay=0)
    s = step(s, PlaceWorker(space="clay_pit"))
    # cp does NOT own clay_deposit → Clay Pit is not hosted for cp's use.
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert s.players[cp].card_state.get(CARD_ID, 0) == 0
    assert s.players[opp].card_state.get(CARD_ID, 0) == 0
