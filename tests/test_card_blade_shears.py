"""Blade Shears (minor, C7): on play gain max(3, sheep) food; keep the sheep.

Prereq: at least 1 enclosed pasture (have-check). Cost 1 wood. Not passing, no VPs.

Real-flow play is driven through PendingPlayMinor + sole_play_minor (the
established minor-play test pattern), mirroring tests/test_cards_minors.py.
"""
import agricola.cards.blade_shears  # noqa: F401

from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pasture import Pasture
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import GameState
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD = "blade_shears"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD,) + tuple(f"m{i}" for i in range(20)),
)


def _add_pasture(state: GameState, idx: int, cells=((0, 0),)) -> GameState:
    """Give player `idx` one enclosed pasture (satisfies the prereq)."""
    fy = state.players[idx].farmyard
    pasture = Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
    fy = fast_replace(fy, pastures=(pasture,))
    p = fast_replace(state.players[idx], farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _card_state(seed=5, *, cp_minors=frozenset(), cp_res=None,
                sheep=0, with_pasture=True):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = cs.players[cp]
    changes = {"hand_minors": cp_minors}
    if cp_res is not None:
        changes["resources"] = cp_res
    if sheep:
        changes["animals"] = p.animals + Animals(sheep=sheep)
    p = fast_replace(p, **changes)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    if with_pasture:
        cs = _add_pasture(cs, cp)
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_blade_shears_registered():
    assert CARD in MINORS
    spec = MINORS[CARD]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.passing_left is False
    assert spec.vps == 0
    assert spec.prereq is not None


# ---------------------------------------------------------------------------
# Prerequisite: at least 1 pasture
# ---------------------------------------------------------------------------

def test_prereq_requires_a_pasture():
    spec = MINORS[CARD]
    cs, cp = _card_state(with_pasture=False)
    assert not prereq_met(spec, cs, cp)        # no pasture -> not met
    cs, cp = _card_state(with_pasture=True)
    assert prereq_met(spec, cs, cp)            # one pasture -> met


def test_unplayable_without_pasture_even_if_affordable():
    cs, cp = _card_state(cp_minors=frozenset({CARD}), cp_res=Resources(wood=2),
                         with_pasture=False)
    assert playable_minors(cs, cp) == []       # prereq fails despite affording cost
    cs, cp = _card_state(cp_minors=frozenset({CARD}), cp_res=Resources(wood=2),
                         with_pasture=True)
    assert playable_minors(cs, cp) == [CARD]


def test_unaffordable_without_wood():
    cs, cp = _card_state(cp_minors=frozenset({CARD}), cp_res=Resources(wood=0),
                         with_pasture=True)
    assert playable_minors(cs, cp) == []       # has pasture but cannot pay 1 wood


# ---------------------------------------------------------------------------
# On-play effect: max(3, sheep) food, sheep kept
# ---------------------------------------------------------------------------

def test_grants_three_food_with_few_sheep():
    # 1 sheep -> max(3, 1) = 3 food; pays 1 wood; keeps the sheep.
    cs, cp = _card_state(cp_minors=frozenset({CARD}),
                         cp_res=Resources(wood=1), sheep=1)
    base_food = cs.players[cp].resources.food
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, CARD))
    p = cs.players[cp]
    assert p.resources.food == base_food + 3
    assert p.resources.wood == 0               # paid the 1-wood cost
    assert p.animals.sheep == 1                # sheep kept


def test_grants_one_food_per_sheep_above_three():
    # 5 sheep -> max(3, 5) = 5 food; sheep kept.
    cs, cp = _card_state(cp_minors=frozenset({CARD}),
                         cp_res=Resources(wood=1), sheep=5)
    base_food = cs.players[cp].resources.food
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, CARD))
    p = cs.players[cp]
    assert p.resources.food == base_food + 5
    assert p.animals.sheep == 5                # sheep kept (never spent)


def test_grants_three_food_with_no_sheep():
    # 0 sheep -> floor of 3 food.
    cs, cp = _card_state(cp_minors=frozenset({CARD}),
                         cp_res=Resources(wood=1), sheep=0)
    base_food = cs.players[cp].resources.food
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, CARD))
    p = cs.players[cp]
    assert p.resources.food == base_food + 3
    assert p.animals.sheep == 0


# ---------------------------------------------------------------------------
# Kept (non-passing), scoped to the player
# ---------------------------------------------------------------------------

def test_kept_in_tableau_and_does_not_touch_opponent():
    cs, cp = _card_state(cp_minors=frozenset({CARD}),
                         cp_res=Resources(wood=1), sheep=2)
    opp = 1 - cp
    opp_before = cs.players[opp]
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, CARD))
    p = cs.players[cp]
    assert CARD in p.minor_improvements        # kept (non-passing)
    assert CARD not in p.hand_minors           # left hand
    assert CARD not in cs.players[opp].hand_minors
    # Opponent untouched (no food gain, no card).
    assert cs.players[opp].resources == opp_before.resources
    assert cs.players[opp].animals == opp_before.animals
