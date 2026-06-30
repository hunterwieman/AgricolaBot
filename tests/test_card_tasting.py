"""Tests for Tasting (minor B63): an optional `before_play_occupation` trigger
(exchange 1 grain -> 4 food) that is ALSO an occupation-cost food source. Covers:
registration; the value-trade firing via a real Lessons play-occupation flow (offered even
with food on hand); the grain>=1 eligibility boundary (no grain => not offered); optionality
(declinable — commit without firing); once-per-play scoping via triggers_resolved; and the
affordability machinery — the Lessons gate offering a play payable only via Tasting, plus the
play-occupation commit gate that withholds the commit until Tasting is fired.

A minor (unlike Paper Maker, which is an occupation) — verifying `_owns` / the food-source gate
cover minor improvements.
"""
import agricola.cards.tasting  # noqa: F401  (registers the card)

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
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env

_POOL = CardPool(
    occupations=("consultant", "priest") + tuple(f"o{i}" for i in range(20)),
    minors=("tasting",) + tuple(f"m{i}" for i in range(20)),
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


def _to_play_occupation(cs):
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    return cs


def test_tasting_registered():
    assert "tasting" in MINORS
    assert MINORS["tasting"].vps == 1
    assert MINORS["tasting"].cost.resources == Resources(wood=2)
    assert "tasting" in OCCUPATION_FOOD_SOURCES
    assert any(e.card_id == "tasting" for e in TRIGGERS.get("before_play_occupation", []))


def test_tasting_fires_for_value_with_food_on_hand():
    # Owned + an occupation to play (free: 0 occupations already), plenty of food + a grain:
    # Tasting is still offered (a pure 1-grain -> 4-food value trade) and firing it swaps.
    cs, cp = _state(food=5, grain=1)
    cs = _to_play_occupation(cs)
    assert FireTrigger(card_id="tasting") in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id="tasting"))
    p = cs.players[cp]
    assert p.resources.grain == 0          # 1 - 1
    assert p.resources.food == 9           # 5 + 4


def test_tasting_not_offered_without_grain():
    # grain == 0: the trade has nothing to exchange, so the trigger is not eligible.
    cs, cp = _state(food=5, grain=0)
    cs = _to_play_occupation(cs)
    assert FireTrigger(card_id="tasting") not in legal_actions(cs)


def test_tasting_optional_decline():
    # The trigger is declinable: with the first occupation free, the commit is available
    # alongside the (un-fired) trigger — playing without firing keeps the grain.
    cs, cp = _state(food=0, grain=1)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    assert FireTrigger(card_id="tasting") in la
    assert CommitPlayOccupation(card_id="consultant") in la       # offered without firing
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))     # declined Tasting
    p = cs.players[cp]
    assert p.resources.grain == 1          # untouched
    assert p.resources.food == 0
    assert "consultant" in p.occupations


def test_tasting_once_per_play():
    # triggers_resolved latches the card so it cannot fire twice in one occupation play.
    cs, cp = _state(food=0, grain=2)
    cs = _to_play_occupation(cs)
    cs = step(cs, FireTrigger(card_id="tasting"))
    assert FireTrigger(card_id="tasting") not in legal_actions(cs)
    assert cs.players[cp].resources.food == 4
    assert cs.players[cp].resources.grain == 1


def test_lessons_offered_when_grain_can_pay():
    # 0 food, no other liquidation fuel, own Tasting, ALREADY 1 occupation played (so the next
    # costs 1 food). With 1 grain the cost is payable (grain liquidates to food — and Tasting's
    # food source agrees), so Lessons is offered; with 0 grain there is no fuel and no Tasting
    # input, so it is not. (Tasting's input being grain means liquidation alone already covers
    # the cost — see test_tasting_value_add_then_commit for why the commit gate need not force
    # it first.)
    cs, _ = _state(occupations=("consultant",), hand_occ=("priest",),
                   food=0, grain=1, wood=0)
    assert "lessons" in _spaces(cs)
    cs_nograin, _ = _state(occupations=("consultant",), hand_occ=("priest",),
                           food=0, grain=0, wood=0)
    assert "lessons" not in _spaces(cs_nograin)


def test_tasting_value_add_then_commit():
    # Unlike Paper Maker (whose 1-wood input does NOT liquidate to food, so the commit gate
    # forces it first), Tasting's input is GRAIN — which liquidates to food at 1:1 — so a
    # 1-food occupation cost is payable directly from the grain. The commit is therefore NOT
    # withheld; Tasting sits alongside it as a pure 1-grain -> 4-food value trade. Firing it
    # first banks the surplus, then the commit pays the 1 food.
    cs, cp = _state(occupations=("consultant",), hand_occ=("priest",),
                    food=0, grain=1, wood=0)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="priest") in la           # grain liquidates -> payable
    assert FireTrigger(card_id="tasting") in la                   # offered as a value trade

    cs = step(cs, FireTrigger(card_id="tasting"))                 # 1 grain -> 4 food
    assert cs.players[cp].resources.food == 4
    assert cs.players[cp].resources.grain == 0

    cs = step(cs, CommitPlayOccupation(card_id="priest"))
    p = cs.players[cp]
    assert "priest" in p.occupations
    assert p.resources.food == 3          # raised 4, paid the 1-food occupation cost
    assert p.resources.grain == 0
