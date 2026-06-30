import agricola.cards.gardeners_knife  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources, with_sown_fields
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("gardeners_knife",) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"),
                      revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _play(state, cp):
    """Drive the real play-minor flow via the Major Improvement space."""
    state = step(state, PlaceWorker(space="major_improvement"))
    state = step(state, ChooseSubAction(name="improvement"))
    state = step(state, ChooseSubAction(name="play_minor"))
    return step(state, sole_play_minor(state, "gardeners_knife"))


def _setup(seed, cp_resources=None):
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, wood=1, **(cp_resources or {}))  # afford the 1-wood cost
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"gardeners_knife"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def test_registered():
    assert "gardeners_knife" in MINORS
    spec = MINORS["gardeners_knife"]
    assert spec.cost == Cost(resources=Resources(wood=1))
    assert spec.passing_left is False
    assert spec.vps == 0


def test_food_per_grain_field_and_grain_per_veg_field():
    cs, cp = _setup(5)
    # 2 grain fields, 3 veg fields sown.
    cs = with_sown_fields(cs, cp, grain_fields=[(0, 0), (1, 0)],
                          veg_fields=[(0, 1), (1, 1), (2, 1)])
    food0 = cs.players[cp].resources.food
    grain0 = cs.players[cp].resources.grain
    cs = _play(cs, cp)
    # +2 food (grain fields), +3 grain (veg fields). 1 wood paid.
    assert cs.players[cp].resources.food == food0 + 2
    assert cs.players[cp].resources.grain == grain0 + 3
    assert cs.players[cp].resources.wood == 0
    # Kept (not passing): lands in the owner's minor_improvements.
    assert "gardeners_knife" in cs.players[cp].minor_improvements
    assert "gardeners_knife" not in cs.players[1 - cp].hand_minors


def test_unsown_fields_count_as_neither():
    cs, cp = _setup(5)
    # Plowed but UNSOWN fields (grain==0 and veg==0) — count as neither.
    cs = with_sown_fields(cs, cp, grain_fields=[], veg_fields=[])
    from tests.factories import with_fields
    cs = with_fields(cs, cp, [(0, 0), (1, 0), (2, 0)])
    food0 = cs.players[cp].resources.food
    grain0 = cs.players[cp].resources.grain
    cs = _play(cs, cp)
    assert cs.players[cp].resources.food == food0      # no grain fields
    assert cs.players[cp].resources.grain == grain0    # no veg fields


def test_no_fields_grants_nothing():
    cs, cp = _setup(5)
    food0 = cs.players[cp].resources.food
    grain0 = cs.players[cp].resources.grain
    cs = _play(cs, cp)
    assert cs.players[cp].resources.food == food0
    assert cs.players[cp].resources.grain == grain0


def test_food_and_grain_not_transposed():
    cs, cp = _setup(5)
    # Only grain fields -> only +food, no +grain.
    cs = with_sown_fields(cs, cp, grain_fields=[(0, 0), (1, 0), (2, 0)], veg_fields=[])
    food0 = cs.players[cp].resources.food
    grain0 = cs.players[cp].resources.grain
    cs = _play(cs, cp)
    assert cs.players[cp].resources.food == food0 + 3   # 3 grain fields -> +3 food
    assert cs.players[cp].resources.grain == grain0     # no veg fields -> +0 grain


def test_only_veg_fields_grant_grain_only():
    cs, cp = _setup(5)
    cs = with_sown_fields(cs, cp, grain_fields=[], veg_fields=[(0, 0), (1, 0)])
    food0 = cs.players[cp].resources.food
    grain0 = cs.players[cp].resources.grain
    cs = _play(cs, cp)
    assert cs.players[cp].resources.food == food0       # no grain fields -> +0 food
    assert cs.players[cp].resources.grain == grain0 + 2  # 2 veg fields -> +2 grain
