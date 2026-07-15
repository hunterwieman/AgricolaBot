"""Tests for Roof Examiner (occupation, D145; Dulcinaria Expansion).

Card text: "When you play this card, if you have 1/2/3/4 major improvements, you
immediately get 2/3/4/5 reed."

An on-play step-function grant keyed to the number of owned major improvements.
Tests drive the real Lessons -> play-occupation flow for the core case, and cover
every tier band directly (including the >= top-band saturation and the zero-major
no-op).
"""
import agricola.cards.roof_examiner  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.roof_examiner import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env

from tests.factories import with_current_player, with_majors, with_space

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)

# Major-improvement indices 0..9; give player 0 the first k of them.
_MAJOR_IDXS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]


def _give_k_majors(state, idx, k):
    return with_majors(state, owner_by_idx={m: idx for m in _MAJOR_IDXS[:k]})


def _play_occupation(cs, idx, card_id):
    cs = with_current_player(cs, idx)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=card_id))
    return cs


def _give_hand_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, hand_occupations=frozenset({card_id}))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS


# --- On-play tier bands (direct) --------------------------------------------

def test_tier_bands_direct():
    on_play = OCCUPATIONS[CARD_ID].on_play
    for n_majors, expected_reed in [(0, 0), (1, 2), (2, 3), (3, 4),
                                    (4, 5), (5, 5), (7, 5)]:
        s = _give_k_majors(setup(0), 0, n_majors)
        r0 = s.players[0].resources.reed
        after = on_play(s, 0)
        assert after.players[0].resources.reed == r0 + expected_reed, n_majors


# --- Real engine flow -------------------------------------------------------

def test_on_play_via_engine_flow():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _give_hand_occ(cs, 0, CARD_ID)
    cs = _give_k_majors(cs, 0, 3)          # 3 majors -> 4 reed
    r0 = cs.players[0].resources.reed
    cs = _play_occupation(cs, 0, CARD_ID)
    assert cs.players[0].resources.reed == r0 + 4
    assert CARD_ID in cs.players[0].occupations


def test_no_majors_no_reed_via_engine_flow():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _give_hand_occ(cs, 0, CARD_ID)    # no majors owned
    r0 = cs.players[0].resources.reed
    cs = _play_occupation(cs, 0, CARD_ID)
    assert cs.players[0].resources.reed == r0


def test_opponent_majors_do_not_count():
    """Only the OWNER's majors count; the opponent's are irrelevant."""
    on_play = OCCUPATIONS[CARD_ID].on_play
    s = _give_k_majors(setup(0), 1, 4)     # player 1 owns 4 majors
    r0 = s.players[0].resources.reed
    after = on_play(s, 0)
    assert after.players[0].resources.reed == r0    # player 0 owns none -> no reed
