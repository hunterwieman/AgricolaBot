"""Tests for Trident (minor improvement, D7; Consul Dirigens Expansion).

Card text: "If you play this card in round 3/6/9/12, you immediately get 3/4/5/6
food." Cost: 1 Wood. Prereq: "Play in Round 3, 6, 9, or 12". VPs: 0. Not passing.

A pure on-play one-shot minor. The "3/6/9/12 -> 3/4/5/6 food" slash list is a
positional schedule (food = round // 3 + 2), NOT an OR/play-variant; the amount is
keyed to the round in which the card is played. The round restriction is the card's
prerequisite (a when-check on `state.round_number`), not a cost — mirrors
test_card_digging_spade.py's round-prereq pattern and test_card_trellises.py's
on-play grant flow.
"""
from __future__ import annotations

import agricola.cards.trident  # noqa: F401  (registers the card; not in __init__)

from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import TRIGGERS
from agricola.engine import step
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "trident"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.vps == 0
    assert spec.passing_left is True          # D7 is a traveling minor
    assert spec.on_play is not None
    assert spec.prereq is not None
    # Pure on-play minor — no trigger/hook machinery.
    for entries in TRIGGERS.values():
        assert CARD_ID not in {e.card_id for e in entries}


# ---------------------------------------------------------------------------
# Prerequisite: only rounds 3, 6, 9, 12
# ---------------------------------------------------------------------------

def test_prereq_blocked_off_schedule_rounds():
    s = setup(0)
    spec = MINORS[CARD_ID]
    for r in (1, 2, 4, 5, 7, 8, 10, 11, 13, 14):
        s = fast_replace(s, round_number=r)
        assert not prereq_met(spec, s, 0)


def test_prereq_met_on_schedule_rounds():
    s = setup(0)
    spec = MINORS[CARD_ID]
    for r in (3, 6, 9, 12):
        s = fast_replace(s, round_number=r)
        assert prereq_met(spec, s, 0)


# ---------------------------------------------------------------------------
# on_play — food keyed to the play round (3->3, 6->4, 9->5, 12->6)
# ---------------------------------------------------------------------------

def test_on_play_food_schedule():
    spec = MINORS[CARD_ID]
    for r, expected in ((3, 3), (6, 4), (9, 5), (12, 6)):
        s = fast_replace(setup(0), round_number=r)
        before = s.players[0].resources.food
        out = spec.on_play(s, 0)
        assert out.players[0].resources.food == before + expected, f"round {r}"


def test_on_play_credits_only_acting_player():
    s = fast_replace(setup(0), round_number=6)
    before_opp = s.players[1].resources.food
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[1].resources.food == before_opp   # opponent untouched


def test_on_play_adds_to_existing_food():
    # The grant is additive, not a set.
    s = fast_replace(setup(0), round_number=9)
    p = fast_replace(s.players[0], resources=Resources(food=2))
    s = fast_replace(s, players=(p, s.players[1]))
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.food == 2 + 5


def test_on_play_for_player_1():
    s = fast_replace(setup(0), round_number=12)
    before0 = s.players[0].resources.food
    before1 = s.players[1].resources.food
    out = MINORS[CARD_ID].on_play(s, 1)
    assert out.players[1].resources.food == before1 + 6   # 12 -> 6 food for P1
    assert out.players[0].resources.food == before0       # P0 untouched


# ---------------------------------------------------------------------------
# End-to-end: play the minor at a real PendingPlayMinor
# ---------------------------------------------------------------------------

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def test_play_minor_flow():
    cs, _env = setup_env(0, card_pool=_POOL)
    cs = fast_replace(cs, round_number=6)
    cp = cs.current_player
    # Give the player the card in hand and the wood to pay.
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     resources=Resources(wood=1))
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))

    before_food = cs.players[cp].resources.food
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    pl = cs.players[cp]
    # Traveling: passes to the opponent's hand, not kept in the tableau.
    assert CARD_ID not in pl.minor_improvements
    assert CARD_ID in cs.players[1 - cp].hand_minors
    assert pl.resources.wood == 0                 # cost paid
    assert pl.resources.food == before_food + 4   # round 6 -> +4 food
