"""Tests for Braggart (occupation, A133; Base Revised).

Card text: "During the scoring, you get 2/3/4/5/7/9 bonus points for having at least
5/6/7/8/9/10 improvements in front of you."

A pure end-game scoring term: the bonus is a step function of the improvement count
(owned minors + owned majors; occupations do NOT count). Tests cover registration,
the no-op on-play, every tier band (incl. the >= top-band saturation), that majors
and minors both count, and that occupations do not.
"""
import agricola.cards.braggart  # noqa: F401  (registers the card)

from agricola.cards.braggart import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.scoring import SCORING_TERMS
from agricola.setup import setup
from agricola.state import GameState

from tests.factories import with_majors, with_minors


def _score_fn():
    return next(fn for cid, fn in SCORING_TERMS if cid == CARD_ID)


def _minors(state: GameState, idx: int, k: int) -> GameState:
    return with_minors(state, idx, frozenset(f"m{i}" for i in range(k)))


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


def test_on_play_is_noop():
    s = setup(0)
    assert OCCUPATIONS[CARD_ID].on_play(s, 0) == s


# --- Scoring bands ----------------------------------------------------------

def test_tier_bands_by_minor_count():
    score = _score_fn()
    # (improvements, expected bonus) across every band boundary.
    for n, expected in [(0, 0), (4, 0), (5, 2), (6, 3), (7, 4),
                        (8, 5), (9, 7), (10, 9), (11, 9), (14, 9)]:
        s = _minors(setup(0), 0, n)
        assert score(s, 0) == expected, (n, expected)


def test_majors_and_minors_both_count():
    score = _score_fn()
    # 3 minors + 2 majors = 5 improvements -> the first band (2 points).
    s = _minors(setup(0), 0, 3)
    s = with_majors(s, owner_by_idx={0: 0, 1: 0})   # majors idx 0 and 1 to player 0
    assert score(s, 0) == 2


def test_occupations_do_not_count():
    score = _score_fn()
    # 4 minors (below the 5 threshold) plus many occupations must NOT reach a band.
    s = _minors(setup(0), 0, 4)
    from agricola.replace import fast_replace
    p = fast_replace(s.players[0],
                     occupations=frozenset(f"occ{i}" for i in range(6)) | {CARD_ID})
    s = fast_replace(s, players=(p, s.players[1]))
    assert score(s, 0) == 0     # occupations are not improvements


def test_owner_scoped():
    score = _score_fn()
    s = _minors(setup(0), 1, 6)     # player 1 has 6 minors, player 0 has none
    assert score(s, 0) == 0
    assert score(s, 1) == 3
