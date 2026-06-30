"""Tests for Bottles (minor improvement, B36).

Card text: "For each person you have, you must pay an additional 1 clay and 1 food
to play this card." Printed VPs: 4. No prerequisite.
Clarification: A newborn is a person (people_total includes newborns).

Coverage:
  - registration (MINORS, cost_fn present, vps=4)
  - cost_fn returns people_total × (1 clay + 1 food)
  - playable_minors gates on affordability at the actual people_total-scaled cost
  - newborns count toward the cost (people_total)
  - on play: card enters minor_improvements, cost is debited, vps score at end-game
  - no prerequisite (playable from round 1 if affordable)
"""
from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.bottles import CARD_ID, _cost
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.legality import playable_minors
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.scoring import score
from agricola.setup import CardPool, setup_env
from agricola.state import get_space, with_space
from tests.factories import with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("bottles",) + tuple(f"m{i}" for i in range(20)),
)


def _reveal_improvement_space(state):
    sp = fast_replace(get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


def _with_hand(state, idx, card_id):
    p = fast_replace(state.players[idx], hand_minors=frozenset({card_id}))
    return fast_replace(state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.vps == 4
    assert spec.cost_fn is not None


def test_no_prerequisite():
    cs, _env = setup_env(5, card_pool=_POOL)
    assert prereq_met(MINORS[CARD_ID], cs, 0)


# ---------------------------------------------------------------------------
# cost_fn: scales with people_total
# ---------------------------------------------------------------------------

def test_cost_fn_two_people():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    assert cs.players[cp].people_total == 2
    cost = _cost(cs, cp)
    assert cost.resources.clay == 2
    assert cost.resources.food == 2


def test_cost_fn_three_people():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], people_total=3, people_home=3)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cost = _cost(cs, cp)
    assert cost.resources.clay == 3
    assert cost.resources.food == 3


def test_cost_fn_newborn_counts():
    # A newborn increments people_total (the clarification: "A newborn is a person").
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    # Simulate having a newborn: people_total=3 while people_home may differ.
    p = fast_replace(cs.players[cp], people_total=3)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cost = _cost(cs, cp)
    assert cost.resources.clay == 3
    assert cost.resources.food == 3


# ---------------------------------------------------------------------------
# playable_minors gates on scaled cost
# ---------------------------------------------------------------------------

def test_not_playable_when_underfunded():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    # people_total=2 → need 2 clay + 2 food; give only 1 clay
    cs = with_resources(cs, cp, clay=1, food=10)
    cs = _with_hand(cs, cp, CARD_ID)
    assert CARD_ID not in playable_minors(cs, cp)


def test_playable_when_exactly_funded():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    # people_total=2 → need exactly 2 clay + 2 food
    cs = with_resources(cs, cp, clay=2, food=2)
    cs = _with_hand(cs, cp, CARD_ID)
    assert CARD_ID in playable_minors(cs, cp)


# ---------------------------------------------------------------------------
# On play: cost debited, card in tableau, 4 VPs at scoring
# ---------------------------------------------------------------------------

def test_on_play_debits_cost_and_enters_tableau():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    n = cs.players[cp].people_total   # 2 at start
    cs = with_resources(cs, cp, clay=n + 3, food=n + 3)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({CARD_ID}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))

    clay_before = cs.players[cp].resources.clay
    food_before = cs.players[cp].resources.food

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, CARD_ID))

    p_after = cs.players[cp]
    assert CARD_ID in p_after.minor_improvements
    assert p_after.resources.clay == clay_before - n
    assert p_after.resources.food == food_before - n


def test_scoring_four_vps():
    cs, _env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    base_total, _ = score(cs, cp)
    p = fast_replace(cs.players[cp],
                     minor_improvements=cs.players[cp].minor_improvements | {CARD_ID})
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    new_total, bd = score(cs, cp)
    assert bd.card_points == 4
    assert new_total == base_total + 4
