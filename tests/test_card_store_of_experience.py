"""Tests for Store of Experience (minor improvement, B5; Bubulcus; traveling).

Card text: "If you have 0-4/5/6/7 occupations left in hand, you immediately get 1
stone/reed/clay/wood." No cost; no prereq; passing.

Coverage: registration (passing, no cost); the full band table 0-4->stone,
5->reed, 6->clay, 7->wood (checked at each threshold incl. the 0/4 edges of the
low band); real play flow + circulation; own-hand-only scoping (the opponent's
hand size is irrelevant).
"""
import agricola.cards.store_of_experience  # noqa: F401  (registers the card)

import pytest

from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup_env
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "store_of_experience"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _set_hand_occ(state, idx, n):
    """Give player `idx` exactly `n` occupation cards in hand."""
    p = fast_replace(state.players[idx],
                     hand_occupations=frozenset(f"occ{i}" for i in range(n)))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()
    assert spec.passing_left is True


@pytest.mark.parametrize("n,field", [
    (0, "stone"), (1, "stone"), (4, "stone"),   # 0-4 band -> stone
    (5, "reed"),
    (6, "clay"),
    (7, "wood"),
])
def test_band_table(n, field):
    s, _env = setup_env(0)
    s = _set_hand_occ(s, 0, n)
    base = getattr(s.players[0].resources, field)
    out = MINORS[CARD_ID].on_play(s, 0)
    r = out.players[0].resources
    # Exactly one unit of the mapped resource is granted; the others are unchanged.
    assert getattr(r, field) == base + 1
    total_gained = (r.wood - s.players[0].resources.wood
                    + r.clay - s.players[0].resources.clay
                    + r.reed - s.players[0].resources.reed
                    + r.stone - s.players[0].resources.stone)
    assert total_gained == 1


def test_real_flow_five_occ_gives_reed_and_passes():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    opp = 1 - cp
    p = fast_replace(cs.players[cp],
                     hand_minors=frozenset({CARD_ID}),
                     hand_occupations=frozenset(f"occ{i}" for i in range(5)))
    opp_p = fast_replace(cs.players[opp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp_p for i in range(2)))
    reed0 = cs.players[cp].resources.reed
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))

    cs = step(cs, sole_play_minor(cs, CARD_ID))
    p = cs.players[cp]
    assert p.resources.reed == reed0 + 1          # 5 occ -> +1 reed
    assert CARD_ID not in p.minor_improvements     # traveling
    assert CARD_ID in cs.players[opp].hand_minors  # circulated


def test_scoping_ignores_opponent_hand():
    s, _env = setup_env(0)
    s = _set_hand_occ(s, 0, 7)   # owner: 7 -> wood
    s = _set_hand_occ(s, 1, 0)   # opponent's hand size must not matter
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.wood == s.players[0].resources.wood + 1
