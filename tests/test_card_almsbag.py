"""Tests for Almsbag (minor improvement, E65; Ephipparius; kept).

Card text: "When you play this card, you immediately get 1 grain for every 2
completed rounds." No cost; prereq "No Occupations" (max_occupations=0); kept.

Coverage: registration (no cost, max_occupations=0, not passing); the
completed-rounds grain formula `(round_number - 1) // 2` at several rounds; the
"No Occupations" prerequisite boundary (0 occ ok, >=1 blocked); real play flow
via the improvement space (kept in tableau, grain credited).
"""
import agricola.cards.almsbag  # noqa: F401  (registers the card)

import pytest

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import Phase
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space
import tests.factories as f
from tests.test_utils import sole_play_minor

CARD_ID = "almsbag"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()
    assert spec.max_occupations == 0
    assert spec.passing_left is False


@pytest.mark.parametrize("round_number,expected_grain", [
    (1, 0),    # 0 completed rounds -> 0
    (2, 0),    # 1 completed -> 0
    (3, 1),    # 2 completed -> 1
    (5, 2),    # 4 completed -> 2
    (14, 6),   # 13 completed -> 6
])
def test_completed_rounds_grain(round_number, expected_grain):
    s = fast_replace(setup(0), round_number=round_number)
    grain0 = s.players[0].resources.grain
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.grain == grain0 + expected_grain


def test_prereq_no_occupations():
    s = setup(0)
    assert prereq_met(MINORS[CARD_ID], s, 0)       # 0 occupations -> ok
    s1 = fast_replace(s, players=tuple(
        fast_replace(s.players[i], occupations=frozenset({"anyocc"})) if i == 0
        else s.players[i] for i in range(2)))
    assert not prereq_met(MINORS[CARD_ID], s1, 0)  # 1 occupation -> blocked


def test_real_flow_kept_and_grain_credited():
    cs, _env = setup_env(5, card_pool=_POOL)
    # Play in round 5 -> 4 completed rounds -> 2 grain.
    cs = fast_replace(cs, round_number=5)
    sp = fast_replace(get_space(cs.board, "major_improvement"), revealed=True, workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "major_improvement", sp))
    cp = cs.current_player
    p = fast_replace(cs.players[cp],
                     hand_occupations=frozenset(),   # no occupations -> prereq met
                     hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    grain0 = cs.players[cp].resources.grain

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    p = cs.players[cp]
    assert p.resources.grain == grain0 + 2         # 4 completed // 2 = 2
    assert CARD_ID in p.minor_improvements          # KEPT (not traveling)
    assert CARD_ID not in p.hand_minors
