"""Tests for Fellow Grazer (occupation, A99; Artifex): "During scoring, you get
2 bonus points for each pasture you have covering at least 3 farmyard spaces."

Coverage is the pasture's CELL count (len(p.cells) >= 3), 2 VP per qualifying
pasture. Mirrors tests/test_cards_scoring.py (Stable Architect): registry,
the score helper across boundary sizes, owner-only scoring, and a real
play-via-Lessons engine flow.
"""
import agricola.cards.fellow_grazer  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.fellow_grazer import _score
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.pasture import Pasture
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import CardPool, setup, setup_env

_POOL = CardPool(
    occupations=("fellow_grazer",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _own(state, idx, card_id):
    p = fast_replace(state.players[idx], occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


def _set_pastures(state, idx, cells_per_pasture):
    """Install the given pastures (one frozenset of cells each) onto the farmyard."""
    fy = state.players[idx].farmyard
    pastures = tuple(
        Pasture(cells=frozenset(cells), num_stables=0, capacity=2 * len(cells))
        for cells in cells_per_pasture)
    fy = fast_replace(fy, pastures=pastures)
    p = fast_replace(state.players[idx], farmyard=fy)
    return fast_replace(state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_fellow_grazer_registered_in_both_registries():
    assert "fellow_grazer" in OCCUPATIONS                          # playable via Lessons
    assert any(cid == "fellow_grazer" for cid, _ in SCORING_TERMS)  # scores


# ---------------------------------------------------------------------------
# The _score helper — coverage threshold (>= 3 cells) and 2-VP multiplier
# ---------------------------------------------------------------------------

def test_score_threshold_is_three_cells_inclusive():
    s = setup(0)
    # A 2-cell pasture does NOT qualify; a 3-cell one does.
    s2 = _set_pastures(s, 0, [[(0, 0), (1, 0)]])
    assert _score(s2, 0) == 0
    s3 = _set_pastures(s, 0, [[(0, 0), (1, 0), (2, 0)]])
    assert _score(s3, 0) == 2


def test_score_is_two_per_qualifying_pasture():
    s = setup(0)
    # Two qualifying pastures (3 and 4 cells) + one non-qualifying (1 cell).
    s = _set_pastures(s, 0, [
        [(0, 0), (1, 0), (2, 0)],            # 3 cells -> qualifies
        [(0, 1), (1, 1), (2, 1), (0, 2)],    # 4 cells -> qualifies
        [(2, 2)],                            # 1 cell  -> does not qualify
    ])
    assert _score(s, 0) == 4  # 2 qualifying * 2 VP


def test_score_no_pastures_is_zero():
    s = setup(0)
    assert _score(s, 0) == 0


def test_score_stables_do_not_change_cell_count():
    s = setup(0)
    # A 2-cell pasture with stables raising capacity still has only 2 cells -> 0.
    fy = s.players[0].farmyard
    fy = fast_replace(fy, pastures=(
        Pasture(cells=frozenset({(0, 0), (1, 0)}), num_stables=2, capacity=16),))
    p = fast_replace(s.players[0], farmyard=fy)
    s = fast_replace(s, players=(p, s.players[1]))
    assert _score(s, 0) == 0


# ---------------------------------------------------------------------------
# Scoring integration — owner-only
# ---------------------------------------------------------------------------

def test_card_points_added_only_for_owner():
    s = setup(0)
    s = _set_pastures(s, 0, [[(0, 0), (1, 0), (2, 0)]])  # one 3-cell pasture
    # Not owned -> no card points.
    base_total, bd = score(s, 0)
    assert bd.card_points == 0
    # Own Fellow Grazer -> +2 card points, total rises by exactly 2.
    s2 = _own(s, 0, "fellow_grazer")
    t2, bd2 = score(s2, 0)
    assert bd2.card_points == 2
    assert t2 == base_total + 2

    # The opponent (non-owner) gets nothing even with a qualifying pasture.
    s3 = _set_pastures(s2, 1, [[(0, 0), (1, 0), (2, 0)]])
    _t, bd3 = score(s3, 1)
    assert bd3.card_points == 0


# ---------------------------------------------------------------------------
# Played via Lessons (no-op on play), then scores
# ---------------------------------------------------------------------------

def test_fellow_grazer_played_via_lessons_then_scores():
    cs, env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"fellow_grazer"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = _set_pastures(cs, cp, [[(0, 0), (1, 0), (2, 0)]])  # one 3-cell pasture

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # singleton: push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="fellow_grazer"))
    assert "fellow_grazer" in cs.players[cp].occupations
    _t, bd = score(cs, cp)
    assert bd.card_points == 2
