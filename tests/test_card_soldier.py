"""Tests for Soldier (occupation, C133): a pure end-game scoring term awarding
1 bonus point per stone-wood PAIR in the supply = min(wood, stone). No on-play
effect (no-op, played via Lessons). Mirrors test_cards_scoring.py (Stable
Architect, the sibling scoring occupation).
"""
import agricola.cards.soldier  # noqa: F401

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.soldier import _score
from agricola.cards.specs import OCCUPATIONS
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import CardPool, setup, setup_env
from tests.factories import with_resources

_POOL = CardPool(
    occupations=("soldier",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _own(state, idx, card_id):
    p = fast_replace(state.players[idx], occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_soldier_registered_in_both_registries():
    assert "soldier" in OCCUPATIONS                          # playable via Lessons
    assert any(cid == "soldier" for cid, _ in SCORING_TERMS)  # scores


def test_soldier_on_play_is_noop():
    s = setup(0)
    s = with_resources(s, 0, wood=4, stone=4)
    out = OCCUPATIONS["soldier"].on_play(s, 0)
    assert out is s                                          # identity: pure no-op


# ---------------------------------------------------------------------------
# The pair-count math: min(wood, stone), NOT wood + stone
# ---------------------------------------------------------------------------

def test_score_counts_pairs_not_sum():
    s = setup(0)
    s = with_resources(s, 0, wood=4, stone=4)
    assert _score(s, 0) == 4                                 # 4 pairs, not 8

    s = with_resources(s, 0, wood=5, stone=2)
    assert _score(s, 0) == 2                                 # limited by the scarcer (stone)

    s = with_resources(s, 0, wood=1, stone=7)
    assert _score(s, 0) == 1                                 # limited by the scarcer (wood)


def test_score_zero_when_one_resource_absent():
    s = setup(0)
    s = with_resources(s, 0, wood=6, stone=0)
    assert _score(s, 0) == 0                                 # no pairs without stone

    s = with_resources(s, 0, wood=0, stone=6)
    assert _score(s, 0) == 0                                 # no pairs without wood


# ---------------------------------------------------------------------------
# Scoring integration + ownership gating
# ---------------------------------------------------------------------------

def test_card_points_added_only_for_owner():
    s = setup(0)
    s = with_resources(s, 0, wood=3, stone=5)
    # Not owned yet -> no card points from Soldier.
    base_total, bd = score(s, 0)
    assert bd.card_points == 0

    # Own Soldier -> +3 card points (min(3, 5) = 3 pairs); total rises by exactly that.
    s2 = _own(s, 0, "soldier")
    t2, bd2 = score(s2, 0)
    assert bd2.card_points == 3
    assert t2 == base_total + 3


def test_owner_only_scores_own_supply():
    # Owning the card scores P0's supply, independent of P1's resources.
    s = setup(0)
    s = with_resources(s, 0, wood=2, stone=2)
    s = with_resources(s, 1, wood=9, stone=9)
    s = _own(s, 0, "soldier")
    _t0, bd0 = score(s, 0)
    _t1, bd1 = score(s, 1)
    assert bd0.card_points == 2                              # P0's 2 pairs
    assert bd1.card_points == 0                              # P1 doesn't own it


# ---------------------------------------------------------------------------
# Played via Lessons (no-op on play), then scores
# ---------------------------------------------------------------------------

def test_soldier_played_via_lessons_then_scores():
    cs, env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"soldier"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    cs = with_resources(cs, cp, wood=3, stone=4)

    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # singleton: push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="soldier"))
    assert "soldier" in cs.players[cp].occupations
    # Resources are unchanged by playing (first occupation is free, on-play is no-op).
    assert cs.players[cp].resources.wood == 3
    assert cs.players[cp].resources.stone == 4
    _t, bd = score(cs, cp)
    assert bd.card_points == 3                                # min(3, 4) = 3 pairs
