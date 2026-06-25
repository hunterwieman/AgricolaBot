"""Printed-VP scoring for kept minors, plus two more Category 3 automatic-income
cards on atomic spaces that carry VPs: Loam Pit (Day Laborer, +3 clay) and Canoe
(Fishing, +1 food +1 reed). Confirms the Family game still scores 0 card points.
"""
from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.agents.base import RandomAgent, play_game
from agricola.cards.specs import MINORS, prereq_met
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.scoring import score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import get_space

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _own_minor(state, idx, card_id):
    p = fast_replace(state.players[idx],
                     minor_improvements=state.players[idx].minor_improvements | {card_id})
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _card_state():
    s, _env = setup_env(5, card_pool=_POOL)
    return fast_replace(s, current_player=0)


def _play_hosted(state, space_id):
    state = step(state, PlaceWorker(space=space_id))
    state = step(state, Proceed())
    state = step(state, Stop())
    return state


# ---------------------------------------------------------------------------
# Printed-VP scoring
# ---------------------------------------------------------------------------

def test_kept_minor_scores_printed_vps():
    s = setup(0)
    base, _ = score(s, 0)
    s1 = _own_minor(s, 0, "loam_pit")          # vps 1, no SCORING_TERM
    t1, bd1 = score(s1, 0)
    assert bd1.card_points == 1
    assert t1 == base + 1


def test_family_game_card_points_zero_with_vps_change():
    s, env = setup_env(9)
    final, _ = play_game(s, (RandomAgent(seed=1), RandomAgent(seed=2)), dealer=env.resolve)
    for i in (0, 1):
        _t, bd = score(final, i)
        assert bd.card_points == 0


# ---------------------------------------------------------------------------
# Loam Pit + Canoe — Category 3 automatic income on atomic spaces
# ---------------------------------------------------------------------------

def test_loam_pit_adds_clay_on_day_laborer():
    s = _own_minor(_card_state(), 0, "loam_pit")
    clay0 = s.players[0].resources.clay
    food0 = s.players[0].resources.food
    s = _play_hosted(s, "day_laborer")
    assert s.players[0].resources.clay == clay0 + 3      # Loam Pit
    assert s.players[0].resources.food == food0 + 2      # Day Laborer primary


def test_canoe_adds_food_and_reed_on_fishing():
    s = _own_minor(_card_state(), 0, "canoe")
    accumulated = get_space(s.board, "fishing").accumulated_amount
    food0 = s.players[0].resources.food
    reed0 = s.players[0].resources.reed
    s = _play_hosted(s, "fishing")
    assert s.players[0].resources.reed == reed0 + 1      # Canoe
    assert s.players[0].resources.food == food0 + accumulated + 1


def test_loam_pit_and_canoe_prereqs():
    s = setup(0)
    # Loam Pit needs 3 occupations; Canoe needs 1.
    def _with_occs(n):
        p = fast_replace(s.players[0], occupations=frozenset(f"occ{i}" for i in range(n)))
        return fast_replace(s, players=(p, s.players[1]))
    assert not prereq_met(MINORS["loam_pit"], _with_occs(2), 0)
    assert prereq_met(MINORS["loam_pit"], _with_occs(3), 0)
    assert not prereq_met(MINORS["canoe"], _with_occs(0), 0)
    assert prereq_met(MINORS["canoe"], _with_occs(1), 0)
