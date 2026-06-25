"""Tests for the card scoring-term registry (CARD_IMPLEMENTATION_PLAN.md
Category 1) and the first scoring occupation, Stable Architect (+1 VP per
unfenced stable). Confirms the Family game is unaffected (card_points == 0).
"""
from agricola.actions import CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.stable_architect import count_unfenced_stables
from agricola.constants import CellType
from agricola.engine import step
from agricola.pasture import Pasture
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell
from tests.factories import with_grid

_POOL = CardPool(
    occupations=("stable_architect",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _own(state, idx, card_id):
    p = fast_replace(state.players[idx], occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_stable_architect_registered_in_both_registries():
    assert "stable_architect" in OCCUPATIONS                      # playable via Lessons
    assert any(cid == "stable_architect" for cid, _ in SCORING_TERMS)  # scores


# ---------------------------------------------------------------------------
# The unfenced-stable count
# ---------------------------------------------------------------------------

def test_count_unfenced_stables_counts_only_unenclosed():
    s = setup(0)
    # Two stables on empty cells, no fences -> both unfenced.
    s = with_grid(s, 0, {(0, 2): Cell(cell_type=CellType.STABLE),
                         (0, 3): Cell(cell_type=CellType.STABLE)})
    assert count_unfenced_stables(s.players[0].farmyard) == 2

    # Enclose one of them in a pasture -> only the other counts.
    fy = s.players[0].farmyard
    fy = fast_replace(fy, pastures=(Pasture(cells=frozenset({(0, 2)}), num_stables=1, capacity=4),))
    p = fast_replace(s.players[0], farmyard=fy)
    s = fast_replace(s, players=(p, s.players[1]))
    assert count_unfenced_stables(s.players[0].farmyard) == 1


# ---------------------------------------------------------------------------
# Scoring integration
# ---------------------------------------------------------------------------

def test_card_points_added_only_for_owner():
    s = setup(0)
    s = with_grid(s, 0, {(0, 2): Cell(cell_type=CellType.STABLE),
                         (0, 3): Cell(cell_type=CellType.STABLE)})
    # Not owned yet -> no card points.
    _t, bd = score(s, 0)
    assert bd.card_points == 0

    # Own Stable Architect -> +2 card points (2 unfenced stables), and the total
    # increases by exactly that.
    base_total, _ = score(s, 0)
    s2 = _own(s, 0, "stable_architect")
    t2, bd2 = score(s2, 0)
    assert bd2.card_points == 2
    assert t2 == base_total + 2


def test_family_game_has_zero_card_points():
    final, _ = _play_family_to_scoring()
    for i in (0, 1):
        _t, bd = score(final, i)
        assert bd.card_points == 0


def _play_family_to_scoring():
    from agricola.agents.base import RandomAgent, play_game
    s, env = setup_env(3)
    return play_game(s, (RandomAgent(seed=1), RandomAgent(seed=2)), dealer=env.resolve)


# ---------------------------------------------------------------------------
# Played via Lessons (no-op on play), then scores
# ---------------------------------------------------------------------------

def test_stable_architect_played_via_lessons_then_scores():
    cs, env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"stable_architect"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_grid(cs, cp, {(0, 2): Cell(cell_type=CellType.STABLE)})

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, CommitPlayOccupation(card_id="stable_architect"))
    assert "stable_architect" in cs.players[cp].occupations
    _t, bd = score(cs, cp)
    assert bd.card_points == 1
