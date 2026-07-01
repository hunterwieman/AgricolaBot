"""Tests for Tasting (minor B63): "Each time you use a 'Lessons' action space, before paying
the occupation cost, you can exchange 1 grain for 4 food."

Modeled as a LESSONS-SCOPED `before_action_space` trigger (an optional 1 grain -> 4 food
value trade) that is ALSO an occupation-cost food source. The card fires at the before-phase
of the Lessons action-space HOST (`PendingSubActionSpace`, `space_id == "lessons"`), before
the mandatory `ChooseSubAction("play_occupation")` that pays the occupation cost.

Covers: registration on `before_action_space`; the value trade firing via a real Lessons use
(offered even with food on hand); the grain>=1 eligibility boundary; not-owned; once-per-use
via the host's `triggers_resolved`; the affordability machinery (the Lessons placement gate
offering a play payable only via Tasting); and — the scope-correctness guard — that Tasting is
NOT offered when an occupation is played via a NON-Lessons route (Teacher's Desk off the Major
Improvement space), where the old `before_play_occupation` registration wrongly over-fired.

A minor (unlike Paper Maker, which is an occupation) — verifying `_owns` / the food-source gate
cover minor improvements.
"""
import agricola.cards.tasting        # noqa: F401  (registers the card)
import agricola.cards.teachers_desk   # noqa: F401  (a NON-Lessons occupation-play route)

from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
)
from agricola.cards.specs import MINORS, OCCUPATION_FOOD_SOURCES
from agricola.cards.triggers import TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions, legal_placements
from agricola.pending import PendingPlayOccupation, PendingSubActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env

_POOL = CardPool(
    occupations=("consultant", "priest") + tuple(f"o{i}" for i in range(20)),
    minors=("tasting", "teachers_desk") + tuple(f"m{i}" for i in range(20)),
)


def _state(*, owned_minors=("tasting",), hand_occ=("consultant",),
           occupations=(), food=0, grain=0, wood=0):
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(
        cs.players[cp],
        minor_improvements=frozenset(owned_minors),
        occupations=frozenset(occupations),
        hand_occupations=frozenset(hand_occ),
        resources=Resources(food=food, grain=grain, wood=wood),
    )
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _spaces(cs):
    return {a.space for a in legal_placements(cs)}


def _use_lessons(cs):
    """Place a worker at Lessons; the Lessons HOST frame is now in its before-phase, where
    Tasting is surfaced (before the mandatory ChooseSubAction that pays the occupation cost)."""
    cs = step(cs, PlaceWorker(space="lessons"))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingSubActionSpace)
    assert top.space_id == "lessons"
    assert top.phase == "before"
    return cs


def test_tasting_registered():
    assert "tasting" in MINORS
    assert MINORS["tasting"].vps == 1
    assert MINORS["tasting"].cost.resources == Resources(wood=2)
    assert "tasting" in OCCUPATION_FOOD_SOURCES
    # Now on before_action_space (Lessons-scoped), NOT the generic before_play_occupation.
    assert any(e.card_id == "tasting" for e in TRIGGERS.get("before_action_space", []))
    assert not any(e.card_id == "tasting" for e in TRIGGERS.get("before_play_occupation", []))


def test_tasting_offered_at_lessons_before_the_cost():
    # Owned + an occupation to play, plenty of food + a grain: Tasting is offered at the
    # Lessons host's before-phase (a pure 1-grain -> 4-food value trade), before the
    # occupation cost is paid, and firing it swaps.
    cs, cp = _state(food=5, grain=1)
    cs = _use_lessons(cs)
    assert FireTrigger(card_id="tasting") in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id="tasting"))
    p = cs.players[cp]
    assert p.resources.grain == 0          # 1 - 1
    assert p.resources.food == 9           # 5 + 4


def test_tasting_not_offered_without_grain():
    # grain == 0: the trade has nothing to exchange, so the trigger is not eligible.
    cs, cp = _state(food=5, grain=0)
    cs = _use_lessons(cs)
    assert FireTrigger(card_id="tasting") not in legal_actions(cs)


def test_tasting_not_offered_without_the_card():
    # Not owning Tasting: the Lessons host fires no Tasting trigger.
    cs, cp = _state(owned_minors=(), food=5, grain=1)
    cs = _use_lessons(cs)
    assert FireTrigger(card_id="tasting") not in legal_actions(cs)


def test_tasting_optional_decline():
    # The trigger is declinable: the host's mandatory ChooseSubAction is available alongside
    # the (un-fired) trigger — proceeding without firing keeps the grain.
    cs, cp = _state(food=0, grain=1)
    cs = _use_lessons(cs)
    la = legal_actions(cs)
    assert FireTrigger(card_id="tasting") in la
    assert ChooseSubAction(name="play_occupation") in la      # host's mandatory sub-action
    cs = step(cs, ChooseSubAction(name="play_occupation"))    # declined Tasting
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    p = cs.players[cp]
    assert p.resources.grain == 1          # untouched
    assert "consultant" in p.occupations


def test_tasting_once_per_use():
    # The host's triggers_resolved latches the card so it cannot fire twice in one Lessons use.
    cs, cp = _state(food=0, grain=2)
    cs = _use_lessons(cs)
    cs = step(cs, FireTrigger(card_id="tasting"))
    assert FireTrigger(card_id="tasting") not in legal_actions(cs)
    assert cs.players[cp].resources.food == 4
    assert cs.players[cp].resources.grain == 1


def test_lessons_offered_when_grain_can_pay():
    # 0 food, no other liquidation fuel, own Tasting, ALREADY 1 occupation played (so the next
    # costs 1 food). With 1 grain the cost is payable (grain liquidates to food — and Tasting's
    # food source agrees), so Lessons is offered; with 0 grain there is no fuel and no Tasting
    # input, so it is not.
    cs, _ = _state(occupations=("consultant",), hand_occ=("priest",),
                   food=0, grain=1, wood=0)
    assert "lessons" in _spaces(cs)
    cs_nograin, _ = _state(occupations=("consultant",), hand_occ=("priest",),
                           food=0, grain=0, wood=0)
    assert "lessons" not in _spaces(cs_nograin)


def test_tasting_not_offered_on_non_lessons_route():
    # SCOPE GUARD (the fixed bug): an occupation played via a NON-Lessons route must NOT offer
    # Tasting. Own Tasting AND Teacher's Desk (which plays an occupation off the Major
    # Improvement space). Fire Teacher's Desk to reach a PendingPlayOccupation with a grain in
    # hand — the exact spot the old `before_play_occupation` registration over-fired Tasting.
    cs, cp = _state(owned_minors=("tasting", "teachers_desk"),
                    hand_occ=("consultant",), food=5, grain=2)
    # Building goods so the Major Improvement space (and thus Teacher's Desk) is reachable.
    p = fast_replace(cs.players[cp], resources=fast_replace(
        cs.players[cp].resources, wood=20, clay=20, reed=20, stone=20))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    cs = step(cs, PlaceWorker(space="major_improvement"))
    assert FireTrigger(card_id="teachers_desk") in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id="teachers_desk"))
    top = cs.pending_stack[-1]
    assert isinstance(top, PendingPlayOccupation)             # a NON-Lessons occupation play
    assert top.phase == "before"
    # The old bug fired Tasting on EVERY play-occupation before-phase; scoped correctly, it
    # does not fire here (this is not the Lessons host).
    assert FireTrigger(card_id="tasting") not in legal_actions(cs)
    assert CommitPlayOccupation(card_id="consultant") in legal_actions(cs)
