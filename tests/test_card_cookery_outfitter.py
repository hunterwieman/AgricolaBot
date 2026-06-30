"""Cookery Outfitter (occupation, A101): during scoring, +1 point per cooking
improvement you own. Cooking improvements that count = Fireplaces (indices 0,1)
and Cooking Hearths (indices 2,3) ONLY; the Clay Oven (5) and Stone Oven (6) do
NOT count (errata: "Ovens do not count towards this card.").
"""
import agricola.cards.cookery_outfitter  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import COOKING_HEARTH_INDICES, FIREPLACE_INDICES
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import CardPool, setup, setup_env
from tests.factories import with_majors

_POOL = CardPool(
    occupations=("cookery_outfitter",) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _own(state, idx, card_id):
    p = fast_replace(state.players[idx], occupations=state.players[idx].occupations | {card_id})
    return fast_replace(state, players=tuple(p if i == idx else state.players[i] for i in range(2)))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_registered_in_both_registries():
    assert "cookery_outfitter" in OCCUPATIONS                          # playable via Lessons
    assert any(cid == "cookery_outfitter" for cid, _ in SCORING_TERMS)  # scores


# ---------------------------------------------------------------------------
# Scoring: counts Fireplaces + Cooking Hearths, never ovens
# ---------------------------------------------------------------------------

def test_scores_one_per_cooking_improvement():
    s = setup(0)
    # Own a Fireplace (idx 0) + a Cooking Hearth (idx 2) = 2 cooking improvements.
    s = with_majors(s, owner_by_idx={0: 0, 2: 0})
    base, _ = score(s, 0)
    s1 = _own(s, 0, "cookery_outfitter")
    t1, bd1 = score(s1, 0)
    assert bd1.card_points == 2
    assert t1 == base + 2


def test_counts_both_fireplaces_and_both_hearths():
    # All four cooking improvements (indices 0,1,2,3) owned -> 4 points.
    s = setup(0)
    s = with_majors(s, owner_by_idx={i: 0 for i in (FIREPLACE_INDICES + COOKING_HEARTH_INDICES)})
    s = _own(s, 0, "cookery_outfitter")
    _t, bd = score(s, 0)
    assert bd.card_points == 4


def test_ovens_do_not_count():
    # Own only the Clay Oven (idx 5) + Stone Oven (idx 6) -> excluded -> 0 points.
    s = setup(0)
    s = with_majors(s, owner_by_idx={5: 0, 6: 0})
    s = _own(s, 0, "cookery_outfitter")
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_no_cooking_improvements_scores_zero():
    s = setup(0)
    s = _own(s, 0, "cookery_outfitter")
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_opponents_cooking_improvements_do_not_count():
    # Player 1 owns the Fireplace + Cooking Hearth; player 0 owns the card -> 0 for player 0.
    s = setup(0)
    s = with_majors(s, owner_by_idx={0: 1, 2: 1})
    s = _own(s, 0, "cookery_outfitter")
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_not_owned_scores_zero():
    s = setup(0)
    s = with_majors(s, owner_by_idx={0: 0, 2: 0})
    _t, bd = score(s, 0)
    assert bd.card_points == 0   # has cooking improvements but not the card


# ---------------------------------------------------------------------------
# Played via Lessons (no-op on play), then scores through a real engine flow
# ---------------------------------------------------------------------------

def test_played_via_lessons_then_scores():
    cs, env = setup_env(5, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=frozenset({"cookery_outfitter"}))
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))
    # Give the player a Fireplace so the card has something to score.
    cs = with_majors(cs, owner_by_idx={0: cp})

    res_before = cs.players[cp].resources
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))   # singleton: push PendingPlayOccupation
    cs = step(cs, CommitPlayOccupation(card_id="cookery_outfitter"))

    assert "cookery_outfitter" in cs.players[cp].occupations     # moved to tableau
    assert "cookery_outfitter" not in cs.players[cp].hand_occupations
    assert cs.players[cp].resources == res_before                # no-op on play (first occupation, free)

    _t, bd = score(cs, cp)
    assert bd.card_points == 1


def test_family_game_unaffected():
    s = setup(0)
    s = with_majors(s, owner_by_idx={0: 0, 2: 0})
    _t, bd = score(s, 0)
    assert bd.card_points == 0   # card not owned; Family game scores no card points
