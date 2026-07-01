"""Tests for Fodder Chamber (D35) — a pure end-game scoring minor improvement.

Card text: "During scoring in a game with 1/2/3/4+ players, you get 1 bonus point
for every 7th/5th/4th/3rd animal on your farm." Printed 2 victory points.

This engine is the 2-player game, so the threshold is the *5th-animal* tier: the
bonus is `floor(total_animals / 5)`. The printed 2 VPs are summed separately by
`score()`, so the `register_scoring` term returns ONLY the per-5-animals bonus
(adding the 2 inside it would double-count).
"""
import agricola.cards.fodder_chamber  # noqa: F401  (registers the card)

from agricola.cards.fodder_chamber import CARD_ID, _score, _total_animals
from agricola.cards.specs import MINORS
from agricola.resources import Cost, Resources
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import setup

from tests.factories import with_animals, with_minors


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration_minor():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost(resources=Resources(stone=3, grain=3))
    assert spec.vps == 2
    # Pure scoring minor: no prereq, no passing, no occupation bounds.
    assert spec.prereq is None
    assert spec.passing_left is False
    assert spec.min_occupations == 0
    assert spec.max_occupations is None


def test_registration_scoring():
    assert any(cid == CARD_ID for cid, _ in SCORING_TERMS)


# ---------------------------------------------------------------------------
# The per-5-animals bonus (2-player tier): floor(total_animals / 5).
# ---------------------------------------------------------------------------

def test_total_animals_sums_all_three_species():
    state = setup(seed=0)
    state = with_animals(state, 0, sheep=2, boar=3, cattle=4)
    assert _total_animals(state, 0) == 9


def test_score_floor_division_by_5():
    state = setup(seed=0)
    # Each species contributes to the single farm-total.
    cases = {
        0: 0,    # 0 animals -> 0
        4: 0,    # below first threshold
        5: 1,    # exactly the 5th animal -> 1
        9: 1,    # still one complete group of 5
        10: 2,   # two complete groups
        14: 2,
        15: 3,
    }
    for total, expected in cases.items():
        s = with_animals(state, 0, sheep=total)  # route the whole total through sheep
        assert _score(s, 0) == expected, f"{total} animals -> {expected}"


def test_score_counts_mixed_species():
    state = setup(seed=0)
    # 3 + 4 + 3 = 10 animals -> 2 bonus points.
    state = with_animals(state, 0, sheep=3, boar=4, cattle=3)
    assert _score(state, 0) == 2


# ---------------------------------------------------------------------------
# Eligibility boundary: exactly the 5-animal step.
# ---------------------------------------------------------------------------

def test_threshold_boundary_at_5():
    state = setup(seed=0)
    assert _score(with_animals(state, 0, sheep=4), 0) == 0
    assert _score(with_animals(state, 0, sheep=5), 0) == 1
    assert _score(with_animals(state, 0, sheep=6), 0) == 1


# ---------------------------------------------------------------------------
# Owner-scoping: the term only counts the SCORED player's animals.
# ---------------------------------------------------------------------------

def test_scoped_to_player_idx():
    state = setup(seed=0)
    state = with_animals(state, 0, sheep=10)   # P0: 2 bonus
    state = with_animals(state, 1, sheep=5)    # P1: 1 bonus
    assert _score(state, 0) == 2
    assert _score(state, 1) == 1


# ---------------------------------------------------------------------------
# Integration through score(): printed vps + the per-5-animals bonus, no
# double-counting; the term only fires for the owner.
# ---------------------------------------------------------------------------

def test_score_includes_card_when_owned():
    """Owning the minor: card_points = printed 2 vps + floor(animals/5) bonus."""
    state = setup(seed=0)
    state = with_animals(state, 0, sheep=10)         # 10 animals -> 2 bonus
    state = with_minors(state, 0, frozenset({CARD_ID}))

    _total, br = score(state, 0)
    # card_points = 2 (printed vps) + 2 (scoring term) = 4. No double-count of vps.
    assert br.card_points == 4


def test_no_card_points_when_minor_not_owned():
    """The scoring term is OWNER-gated in `score()` (`_owns(ps, card_id)`), so a
    player who does not own Fodder Chamber gets neither the per-5-animals bonus nor
    the printed vps, even with many animals."""
    state = setup(seed=0)
    state = with_animals(state, 0, sheep=10)         # 10 animals, but no card
    # No with_minors: the minor is not in the tableau, so it is not owned.
    _total, br = score(state, 0)
    assert br.card_points == 0  # term gated off; no printed vps either


def test_term_scoped_to_owner_through_score():
    """P0 owns the minor with 10 animals; P1 has 10 animals but does NOT own it.
    Only P0 receives card_points (2 vps + 2 bonus); P1 gets 0."""
    state = setup(seed=0)
    state = with_animals(state, 0, sheep=10)
    state = with_animals(state, 1, sheep=10)
    state = with_minors(state, 0, frozenset({CARD_ID}))   # only P0 owns it
    _t0, br0 = score(state, 0)
    _t1, br1 = score(state, 1)
    assert br0.card_points == 4   # 2 vps + 2 bonus
    assert br1.card_points == 0   # not owned


def test_no_bonus_below_threshold_through_score():
    state = setup(seed=0)
    state = with_animals(state, 0, sheep=4)          # below 5 -> 0 bonus
    state = with_minors(state, 0, frozenset({CARD_ID}))
    _total, br = score(state, 0)
    # Only the printed 2 vps; the per-5 term contributes 0.
    assert br.card_points == 2
