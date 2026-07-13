"""Storage Barn (minor A6) — on-play building-resource grant keyed on owned majors.

Card: "If you have the Well, Joinery, Pottery, and/or Basketmaker's Workshop,
you immediately get 1 stone, 1 wood, 1 clay, and/or 1 reed, respectively."
"""
import agricola.cards.storage_barn  # noqa: F401  (registers the minor; not in cards/__init__ yet)

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.specs import MINORS
from agricola.resources import Cost
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_majors
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("storage_barn",) + tuple(f"m{i}" for i in range(20)),
)

# Major indices -> resource (from the card / constants ordering).
_WELL = 4
_JOINERY = 7
_POTTERY = 8
_BASKETMAKER = 9


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _setup(seed=5, *, owners=None):
    """Fresh card-mode game with the improvement space free and `storage_barn`
    in the current player's hand. `owners` maps major-idx -> player-idx."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    if owners:
        cs = with_majors(cs, owner_by_idx=owners)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"storage_barn"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    return cs, cp


def _play(cs):
    """Drive the real major_improvement -> play_minor flow to play storage_barn."""
    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))     # singleton: push the wrapper
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "storage_barn"))
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered_as_free_kept_minor():
    spec = MINORS["storage_barn"]
    assert spec.card_id == "storage_barn"
    assert spec.cost == Cost()                                 # no cost
    assert spec.cost_fn is None
    assert spec.prereq is None
    assert spec.vps == 0
    assert spec.passing_left is True                           # A6 is a traveling minor


# ---------------------------------------------------------------------------
# Effect via a real engine flow
# ---------------------------------------------------------------------------

def test_grants_for_each_owned_major():
    cs, cp = _setup(owners=None)  # set owners after we know cp
    # Give the current player all four qualifying majors.
    cs = with_majors(cs, owner_by_idx={
        _WELL: cp, _JOINERY: cp, _POTTERY: cp, _BASKETMAKER: cp})
    before = cs.players[cp].resources

    cs = _play(cs)

    after = cs.players[cp].resources
    assert after.stone == before.stone + 1   # Well
    assert after.wood == before.wood + 1     # Joinery
    assert after.clay == before.clay + 1     # Pottery
    assert after.reed == before.reed + 1     # Basketmaker's Workshop
    # Traveling: passes to the opponent's hand, not kept in the tableau.
    assert "storage_barn" not in cs.players[cp].minor_improvements
    assert "storage_barn" in cs.players[1 - cp].hand_minors


def test_grants_only_for_the_subset_owned():
    cs, cp = _setup()
    cs = with_majors(cs, owner_by_idx={_JOINERY: cp, _BASKETMAKER: cp})
    before = cs.players[cp].resources

    cs = _play(cs)

    after = cs.players[cp].resources
    assert after.wood == before.wood + 1     # Joinery -> wood
    assert after.reed == before.reed + 1     # Basketmaker's -> reed
    assert after.stone == before.stone       # no Well
    assert after.clay == before.clay         # no Pottery


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_no_majors_owned_grants_nothing():
    cs, cp = _setup()  # nobody owns any major
    before = cs.players[cp].resources

    cs = _play(cs)

    after = cs.players[cp].resources
    assert after.stone == before.stone
    assert after.wood == before.wood
    assert after.clay == before.clay
    assert after.reed == before.reed
    # Played (then passed) even when it granted nothing.
    assert "storage_barn" not in cs.players[cp].minor_improvements
    assert "storage_barn" in cs.players[1 - cp].hand_minors


def test_opponent_owned_majors_do_not_grant():
    cs, cp = _setup()
    opp = 1 - cp
    # All four qualifying majors owned by the OPPONENT.
    cs = with_majors(cs, owner_by_idx={
        _WELL: opp, _JOINERY: opp, _POTTERY: opp, _BASKETMAKER: opp})
    before = cs.players[cp].resources

    cs = _play(cs)

    after = cs.players[cp].resources
    assert after.stone == before.stone
    assert after.wood == before.wood
    assert after.clay == before.clay
    assert after.reed == before.reed


def test_non_qualifying_majors_do_not_grant():
    cs, cp = _setup()
    # Fireplace (0), Cooking Hearth (2), Clay Oven (5), Stone Oven (6) — none qualify.
    cs = with_majors(cs, owner_by_idx={0: cp, 2: cp, 5: cp, 6: cp})
    before = cs.players[cp].resources

    cs = _play(cs)

    after = cs.players[cp].resources
    assert after.stone == before.stone
    assert after.wood == before.wood
    assert after.clay == before.clay
    assert after.reed == before.reed
