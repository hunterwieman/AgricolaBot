"""More Category 1 (end-game scoring) and Category 2 (on-play one-shot) cards that
need no new infra beyond Milestone 1's scoring registry + on_play dispatch:

  - Manger (minor): bonus points by pasture coverage.
  - Wool Blankets (minor): bonus points by house material; prereq 5 sheep.
  - Clay Embankment (minor, passing): +1 clay per 2 clay held.
  - Young Animal Market (minor, passing): cost 1 sheep, gain 1 cattle (Animals cost).
"""
from agricola.actions import PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.constants import HouseMaterial
from agricola.engine import step
from agricola.pasture import Pasture
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_animals, with_house, with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("clay_embankment", "young_animal_market") + tuple(f"m{i}" for i in range(20)),
)


def _own_minor(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _set_pastures(state, idx, cells_per_pasture):
    fy = state.players[idx].farmyard
    pastures = tuple(
        Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
        for cells in cells_per_pasture)
    fy = fast_replace(fy, pastures=pastures)
    p = fast_replace(state.players[idx], farmyard=fy)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Manger — pasture coverage scoring
# ---------------------------------------------------------------------------

def test_manger_scores_by_pasture_coverage():
    s = setup(0)
    # 6 covered cells -> tier 1 (>=6).
    s = _set_pastures(s, 0, [[(0, 0), (1, 0), (2, 0)], [(0, 1), (1, 1), (2, 1)]])
    base, _ = score(s, 0)
    s1 = _own_minor(s, 0, "manger")
    t1, bd1 = score(s1, 0)
    assert bd1.card_points == 1
    assert t1 == base + 1


def test_manger_below_threshold_scores_zero():
    s = setup(0)
    s = _set_pastures(s, 0, [[(0, 0), (1, 0)]])     # 2 cells, < 6
    s = _own_minor(s, 0, "manger")
    _t, bd = score(s, 0)
    assert bd.card_points == 0


# ---------------------------------------------------------------------------
# Wool Blankets — house-material scoring + prerequisite
# ---------------------------------------------------------------------------

def test_wool_blankets_scores_by_house_material():
    s = setup(0)
    s = with_house(s, 0, HouseMaterial.WOOD)
    s = _own_minor(s, 0, "wool_blankets")
    _t, bd = score(s, 0)
    assert bd.card_points == 3                       # wooden house

    s2 = with_house(s, 0, HouseMaterial.CLAY)
    _t2, bd2 = score(s2, 0)
    assert bd2.card_points == 2


def test_wool_blankets_prereq_needs_five_sheep():
    s = setup(0)
    assert not prereq_met(MINORS["wool_blankets"], with_animals(s, 0, sheep=4), 0)
    assert prereq_met(MINORS["wool_blankets"], with_animals(s, 0, sheep=5), 0)


# ---------------------------------------------------------------------------
# Clay Embankment — +1 clay per 2 clay, passing
# ---------------------------------------------------------------------------

def test_clay_embankment_gain_and_pass():
    cs, env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, clay=5, food=1)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"clay_embankment"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    cs = step(cs, PlaceWorker(space="major_improvement"))   # play-minor entry point
    # singleton improvement choose pushes PendingMajorMinorImprovement, then
    # choose the play-minor branch and commit the card
    from agricola.actions import ChooseSubAction
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "clay_embankment"))
    # 5 clay -> +2 clay (5//2) = 7; food paid (1 -> 0); passed, not kept.
    assert cs.players[cp].resources.clay == 7
    assert "clay_embankment" not in cs.players[cp].minor_improvements
    assert "clay_embankment" in cs.players[1 - cp].hand_minors


# ---------------------------------------------------------------------------
# Young Animal Market — animal cost (1 sheep) -> 1 cattle, passing
# ---------------------------------------------------------------------------

def test_young_animal_market_swaps_sheep_for_cattle():
    cs, env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_animals(cs, cp, sheep=2, cattle=0)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"young_animal_market"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    from agricola.actions import ChooseSubAction
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))   # singleton: push PendingMajorMinorImprovement
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "young_animal_market"))
    assert cs.players[cp].animals.sheep == 1         # 2 - 1 (cost)
    assert cs.players[cp].animals.cattle == 1        # +1 (on_play)
    assert "young_animal_market" in cs.players[1 - cp].hand_minors
