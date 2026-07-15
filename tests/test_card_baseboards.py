"""Tests for Baseboards (minor improvement, A4; Artifex; traveling).

Card text: "You immediately get 1 wood for each room you have. If you have more
rooms than people, you get 1 additional wood." Cost "2 Food / 1 Grain" (an
ALTERNATIVE cost); passing.

Coverage: registration (the "/" alt cost: 2 food in `cost`, 1 grain in
`alt_costs`; passing); on-play +1 wood per room; the strict rooms>people bonus
(default 2 rooms == 2 people gives NO bonus; a 3rd room with 2 people gives +1);
real play flow paying EITHER food OR grain, with circulation to the opponent.
"""
import agricola.cards.baseboards  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
import tests.factories as f
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "baseboards"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _minor_commits(state):
    return [a for a in legal_actions(state)
            if getattr(a, "card_id", None) == CARD_ID]


def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    # "2 Food / 1 Grain" -> pay ONE: 2 food (cost) OR 1 grain (alt).
    assert spec.cost == Cost(resources=Resources(food=2))
    assert spec.alt_costs == (Cost(resources=Resources(grain=1)),)
    assert spec.passing_left is True


def test_on_play_default_two_rooms_two_people_no_bonus():
    # Default farm: 2 rooms, 2 people -> 2 wood, NO bonus (strict comparison).
    s, _env = setup_env(0)
    wood0 = s.players[0].resources.wood
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.wood == wood0 + 2


def test_on_play_more_rooms_than_people_gives_bonus():
    # Add a 3rd ROOM at an empty cell -> 3 rooms, 2 people -> 3 + 1 bonus = 4 wood.
    s, _env = setup_env(0)
    s = f.with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    wood0 = s.players[0].resources.wood
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.wood == wood0 + 4


def test_on_play_equal_rooms_and_people_no_bonus():
    # 3 rooms but 3 people -> equal, so NO bonus: 3 wood.
    s, _env = setup_env(0)
    s = f.with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.ROOM)})
    s = f.with_people(s, 0, total=3)
    wood0 = s.players[0].resources.wood
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out.players[0].resources.wood == wood0 + 3


def _play_state(res):
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}), resources=res)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return cs, cp


def test_both_alternatives_offered_when_affordable():
    cs, _cp = _play_state(Resources(food=2, grain=1))
    payments = sorted((c.payment.food, c.payment.grain) for c in _minor_commits(cs))
    assert payments == [(0, 1), (2, 0)]   # a 1-grain option and a 2-food option


def test_real_flow_pay_grain_gains_wood_and_passes():
    cs, cp = _play_state(Resources(food=0, grain=1))
    opp = 1 - cp
    wood0 = cs.players[cp].resources.wood
    grain_commit = next(c for c in _minor_commits(cs) if c.payment.grain == 1)
    cs = step(cs, grain_commit)
    p = cs.players[cp]
    assert p.resources.grain == 0                # paid the 1 grain
    assert p.resources.wood == wood0 + 2         # default 2 rooms -> 2 wood
    assert CARD_ID not in p.minor_improvements   # traveling
    assert CARD_ID in cs.players[opp].hand_minors  # circulated
