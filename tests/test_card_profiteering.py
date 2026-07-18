"""Tests for Profiteering (minor improvement, E82; Ephipparius Expansion).

Card text: "When you play this card, you immediately get 1 food. Each time after you
use the "Day Laborer" action space, you can exchange 1 building resource for another
building resource."

Two effects:
  * on-play +1 food (ruling 66, 2026-07-17: the ordinary on-play instant), and
  * an OPTIONAL `after_action_space` trigger on `day_laborer` (own use only) that
    exchanges 1 building resource for a different one, modeled as a play-variant
    trigger surfaced as one `FireTrigger(variant="give->get")` per legal pair. Day
    Laborer is true-atomic, so the card also registers an action-space hook.
"""
from __future__ import annotations

import agricola.cards.profiteering  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, FireTrigger, PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import (
    OWN_ACTION_HOOK_CARDS,
    PLAY_VARIANT_TRIGGERS,
    TRIGGERS,
)
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.state import GameState, get_space, with_space
from tests.factories import with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("profiteering",) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _set_resources(state, idx, **kw):
    p = fast_replace(state.players[idx], resources=Resources(**kw))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _at_day_laborer_after(idx=0, **resources):
    """Own Profiteering + the given resources, place on Day Laborer, then Proceed to
    reach the host's AFTER-phase (where the exchange trigger lives). Returns the state
    just after the +2 food landed."""
    s, _env = setup_env(0)
    s = fast_replace(s, current_player=idx)
    s = _own_minor(s, idx, "profiteering")
    if resources:
        s = _set_resources(s, idx, **resources)
    s = step(s, PlaceWorker(space="day_laborer"))
    # Before-phase offers only Proceed (the exchange fires AFTER); Proceed applies the
    # Day Laborer +2 food and flips the host to its after-phase.
    assert legal_actions(s) == [Proceed()]
    s = step(s, Proceed())
    return s, idx


def _fire_variants(state):
    return {a.variant for a in legal_actions(state) if isinstance(a, FireTrigger)}


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_profiteering_registered():
    assert "profiteering" in MINORS
    spec = MINORS["profiteering"]
    assert spec.cost == Cost()             # no cost
    assert spec.alt_costs == ()
    assert spec.vps == 0
    assert spec.passing_left is False
    assert spec.max_occupations is None and spec.min_occupations == 0
    # No prerequisite: any state satisfies it.
    assert prereq_met(spec, setup(0), 0)
    # Play-variant trigger on after_action_space + the atomic-space hook.
    assert "profiteering" in PLAY_VARIANT_TRIGGERS
    aas = {e.card_id for e in TRIGGERS.get("after_action_space", [])}
    assert "profiteering" in aas
    assert "profiteering" not in {e.card_id for e in TRIGGERS.get("before_action_space", [])}
    assert "profiteering" in OWN_ACTION_HOOK_CARDS.get("day_laborer", set())


# ---------------------------------------------------------------------------
# On-play +1 food (via a real play route)
# ---------------------------------------------------------------------------

def test_profiteering_on_play_grants_one_food_via_engine():
    # Drive the real play-minor flow through the Major Improvement space in CARDS
    # mode (PlaceWorker -> improvement -> play_minor -> CommitPlayMinor). No cost, so
    # nothing is spent; the only resource change is the on-play +1 food.
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, food=0)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"profiteering"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    food_before = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "profiteering"))

    assert "profiteering" in cs.players[cp].minor_improvements
    assert cs.players[cp].resources.food == food_before + 1


# ---------------------------------------------------------------------------
# The Day Laborer exchange — real flow
# ---------------------------------------------------------------------------

def test_profiteering_day_laborer_food_then_exchange_offered():
    # Holding 1 wood: the +2 food lands, then wood->{clay,reed,stone} are offered.
    s, ap = _at_day_laborer_after(0, wood=1)
    assert s.players[ap].resources.food == 2          # Day Laborer's 2 food arrived
    assert isinstance(s.pending_stack[-1], PendingActionSpace)
    assert _fire_variants(s) == {"wood->clay", "wood->reed", "wood->stone"}
    assert Stop() in legal_actions(s)                 # optional → decline is Stop


def test_profiteering_exchange_applies_correctly():
    s, ap = _at_day_laborer_after(0, wood=1)
    s = step(s, FireTrigger(card_id="profiteering", variant="wood->stone"))
    # -1 wood, +1 stone; food untouched by the exchange.
    assert s.players[ap].resources.wood == 0
    assert s.players[ap].resources.stone == 1
    assert s.players[ap].resources.food == 2
    # Once-per-use: the exchange is no longer offered; only Stop remains.
    la = legal_actions(s)
    assert not any(isinstance(a, FireTrigger) for a in la)
    assert la == [Stop()]
    # Stop pops the host and ends the turn.
    s = step(s, Stop())
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)


def test_profiteering_variants_match_holdings():
    # Hold wood + clay only: gives come from {wood, clay}, gets from the other three
    # building types each; never a give-type not held, never give == get.
    s, ap = _at_day_laborer_after(0, wood=1, clay=1)
    variants = _fire_variants(s)
    assert variants == {
        "wood->clay", "wood->reed", "wood->stone",
        "clay->wood", "clay->reed", "clay->stone",
    }
    for v in variants:
        give, get = v.split("->")
        assert give in ("wood", "clay")          # only held give-types
        assert give != get                       # never give == get


def test_profiteering_no_variants_when_no_building_resource():
    # Only non-building resources (food, grain) → no exchange offered, host is bare Stop.
    s, ap = _at_day_laborer_after(0, grain=5)
    # The +2 food landed; grain is not a building resource, so nothing to trade.
    assert s.players[ap].resources.food == 2
    assert not any(isinstance(a, FireTrigger) for a in legal_actions(s))
    assert legal_actions(s) == [Stop()]


def test_profiteering_decline_via_stop_changes_nothing_but_food():
    s, ap = _at_day_laborer_after(0, wood=1, clay=1)
    wood0 = s.players[ap].resources.wood
    clay0 = s.players[ap].resources.clay
    s = step(s, Stop())   # decline the exchange
    assert s.players[ap].resources.wood == wood0     # no exchange happened
    assert s.players[ap].resources.clay == clay0
    assert s.players[ap].resources.food == 2         # only the Day Laborer food


# ---------------------------------------------------------------------------
# Opponent's Day Laborer use offers nothing (own use only)
# ---------------------------------------------------------------------------

def test_profiteering_opponent_day_laborer_offers_nothing():
    # P0 owns Profiteering; P1 uses Day Laborer. P1 doesn't own the hook, so the space
    # stays atomic for P1 — no host frame, no exchange, and P0's card never fires.
    s, _env = setup_env(0)
    s = fast_replace(s, current_player=1)
    s = _own_minor(s, 0, "profiteering")          # only P0 owns it
    s = _set_resources(s, 1, wood=5, clay=5)
    food1_before = s.players[1].resources.food
    s = step(s, PlaceWorker(space="day_laborer"))
    # No Profiteering host frame anywhere, and no FireTrigger available.
    assert not any(isinstance(f, PendingActionSpace) for f in s.pending_stack)
    assert not any(isinstance(a, FireTrigger) for a in legal_actions(s))
    # P1 just got the plain +2 food; building resources untouched.
    assert s.players[1].resources.food == food1_before + 2
    assert s.players[1].resources.wood == 5 and s.players[1].resources.clay == 5
