"""Tests for Paper Maker (occupation B109): an optional `before_play_occupation` trigger
(pay 1 wood -> 1 food per occupation in front of you) that is ALSO an occupation-cost food
source. Covers: self-exclusion via ownership timing; the value-trade firing (offered even
with food on hand); and the affordability machinery — the Lessons/Scholar gate offering a
play payable only via Paper Maker, plus the play-occupation commit gate that withholds the
commit (no empty-frontier dead state) until Paper Maker is fired.
"""
from agricola.actions import (
    ChooseSubAction,
    CommitPlayOccupation,
    FireTrigger,
    PlaceWorker,
)
from agricola.cards.specs import OCCUPATIONS, OCCUPATION_FOOD_SOURCES
from agricola.cards.triggers import TRIGGERS
from agricola.engine import step
from agricola.legality import legal_actions, legal_placements
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env

_POOL = CardPool(
    occupations=("paper_maker", "consultant", "priest") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _state(*, owned=("paper_maker",), hand=("consultant",), food=0, wood=0):
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], occupations=frozenset(owned),
                     hand_occupations=frozenset(hand),
                     resources=Resources(food=food, wood=wood))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _spaces(cs):
    return {a.space for a in legal_placements(cs)}


def _to_play_occupation(cs):
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    return cs


def test_paper_maker_registered():
    assert "paper_maker" in OCCUPATIONS
    assert "paper_maker" in OCCUPATION_FOOD_SOURCES
    assert any(e.card_id == "paper_maker" for e in TRIGGERS.get("before_play_occupation", []))


def test_paper_maker_fires_for_value_with_food_on_hand():
    # Owned + a 2nd occupation to play, plenty of food: Paper Maker is still offered (a pure
    # 1-wood -> N-food value trade) and firing it adds 1 food per occupation (N=1: Paper Maker).
    cs, cp = _state(owned=("paper_maker",), hand=("consultant",), food=5, wood=2)
    cs = _to_play_occupation(cs)
    assert FireTrigger(card_id="paper_maker") in legal_actions(cs)
    cs = step(cs, FireTrigger(card_id="paper_maker"))
    p = cs.players[cp]
    assert p.resources.wood == 1          # 2 - 1
    assert p.resources.food == 6          # 5 + 1 (one occupation in front)


def test_paper_maker_self_excludes_on_own_play():
    # Playing Paper Maker ITSELF (first occupation, free): it is not yet owned, so it is NOT
    # offered as a before_play_occupation trigger — "after this one" handled automatically.
    cs, cp = _state(owned=(), hand=("paper_maker",), food=2, wood=2)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    assert FireTrigger(card_id="paper_maker") not in la
    assert CommitPlayOccupation(card_id="paper_maker") in la


def test_lessons_offered_only_via_paper_maker():
    # 0 food, 0 liquidation fuel, 1 wood, own Paper Maker: the 2nd occupation's 1-food cost is
    # payable only by firing Paper Maker first — Lessons must be offered (the gate consults the
    # food source). Without the wood (Paper Maker can't fire) it must NOT be offered.
    cs, _ = _state(owned=("paper_maker",), hand=("consultant",), food=0, wood=1)
    assert "lessons" in _spaces(cs)
    cs_nowood, _ = _state(owned=("paper_maker",), hand=("consultant",), food=0, wood=0)
    assert "lessons" not in _spaces(cs_nowood)


def test_commit_gate_forces_paper_maker_before_commit():
    # The dead-state guard: 0 food, 1 wood, own Paper Maker, play a 2nd occupation (cost 1
    # food). At the frame the commit is WITHHELD (food short) — only Paper Maker is offered;
    # firing it raises the food, then the commit unlocks and succeeds.
    cs, cp = _state(owned=("paper_maker",), hand=("consultant",), food=0, wood=1)
    cs = _to_play_occupation(cs)
    la = legal_actions(cs)
    assert CommitPlayOccupation(card_id="consultant") not in la   # withheld: food short
    assert FireTrigger(card_id="paper_maker") in la

    cs = step(cs, FireTrigger(card_id="paper_maker"))             # 1 wood -> 1 food
    assert cs.players[cp].resources.food == 1
    assert CommitPlayOccupation(card_id="consultant") in legal_actions(cs)   # now unlocked

    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    p = cs.players[cp]
    assert "consultant" in p.occupations
    assert p.resources.food == 0          # raised 1, paid the 1-food occupation cost
    assert p.resources.wood == 0
    assert p.resources.clay == 3          # consultant's on-play ran


def test_paper_maker_banks_surplus_with_multiple_occupations():
    # Own Paper Maker + Priest (N=2). Play a 3rd occupation (cost 1 food) with 0 food, 1 wood:
    # firing Paper Maker yields 2 food, paying 1 banks 1.
    cs, cp = _state(owned=("paper_maker", "priest"), hand=("consultant",), food=0, wood=1)
    cs = _to_play_occupation(cs)
    cs = step(cs, FireTrigger(card_id="paper_maker"))
    assert cs.players[cp].resources.food == 2          # 0 + 2 (two occupations in front)
    cs = step(cs, CommitPlayOccupation(card_id="consultant"))
    assert cs.players[cp].resources.food == 1          # 2 - 1, banked
    assert "consultant" in cs.players[cp].occupations
