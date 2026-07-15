"""Tests for Mayor Candidate (occupation, E124; Ephipparius).

Card text: "You immediately get 2 wood and 2 stone. During scoring, you get 1
negative point for each wood and each stone in your supply. You can no longer
discard wood or stone."

Coverage: registration (OCCUPATIONS + a SCORING_TERMS entry); the on-play +2
wood/+2 stone directly and via a real play-through-Lessons flow; the NEGATIVE
scoring term `-(wood + stone)` in the owner's supply, gated by ownership and
scoped to the owner's own supply.
"""
import agricola.cards.mayor_candidate  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import CardPool, setup, setup_env
import tests.factories as f

CARD_ID = "mayor_candidate"

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _own_occ(state, idx, card_id=CARD_ID):
    p = fast_replace(state.players[idx],
                     occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert any(cid == CARD_ID for cid, _fn in SCORING_TERMS)


def test_on_play_grants_two_wood_two_stone():
    s = setup(0)
    wood0 = s.players[0].resources.wood
    stone0 = s.players[0].resources.stone
    out = OCCUPATIONS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.wood == wood0 + 2
    assert out.players[0].resources.stone == stone0 + 2
    # opponent untouched
    assert out.players[1].resources == s.players[1].resources


def test_real_flow_played_via_lessons():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    wood0 = cs.players[cp].resources.wood
    stone0 = cs.players[cp].resources.stone

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=CARD_ID))

    p = cs.players[cp]
    assert CARD_ID in p.occupations
    assert p.resources.wood == wood0 + 2
    assert p.resources.stone == stone0 + 2


def test_scoring_negative_per_wood_and_stone():
    s = setup(0)
    s = f.with_resources(s, 0, wood=3, stone=2)   # 3 wood + 2 stone = 5 in supply
    s = _own_occ(s, 0)
    _t, bd = score(s, 0)
    assert bd.card_points == -5   # -(3 + 2)


def test_scoring_zero_when_no_wood_or_stone():
    s = setup(0)
    s = f.with_resources(s, 0, wood=0, stone=0, food=5)
    s = _own_occ(s, 0)
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_not_owned_no_penalty():
    s = setup(0)
    s = f.with_resources(s, 0, wood=9, stone=9)
    # Not owned -> the negative term does not apply.
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_scoping_reads_own_supply_only():
    s = setup(0)
    s = f.with_resources(s, 0, wood=1, stone=0)   # owner: 1 in supply
    s = f.with_resources(s, 1, wood=9, stone=9)   # opponent loaded
    s = _own_occ(s, 0)
    _t, bd = score(s, 0)
    assert bd.card_points == -1   # only the owner's own 1 wood counts
