"""Tests for Artisan District (minor improvement, D30; Dulcinaria Expansion).

Card text (verbatim): "During scoring, you get 2/5/8 bonus points for having
3/4/5 major improvements from the bottom row of the supply board."
Cost: 1 Stone. Prerequisite: 3 Occupations. Printed VPs: 1.

The bottom row of the supply board is the five work-station crafts — Clay Oven
(5), Stone Oven (6), Joinery (7), Pottery (8), Basketmaker's Workshop (9). The
top row (Fireplaces 0,1 / Cooking Hearths 2,3 / Well 4) does NOT count.

Covers: registration (1-stone cost, +1 vps, min_occupations=3 prereq, scoring
term, not a trigger card); the prereq eligibility boundary (3+ occupations
fires; <3 blocks); the step-function bonus (0/1/2 bottom-row → 0; 3 → 2; 4 → 5;
5 → 8; top-row majors and opponent-owned bottom-row majors don't count); the
scoring ownership gate (only the owner gets the term); and a real play-minor
engine flow (pays 1 stone, kept in tableau, +1 printed vps + scoring bonus).
"""
import agricola.cards.artisan_district  # noqa: F401  (registers the card)

import dataclasses

import pytest

from agricola.cards.artisan_district import _bonus, _bottom_row_count
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import CARDS
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import CardPool, setup_env
from tests.factories import with_majors, with_minors, with_pending_stack, with_resources
from tests.test_utils import sole_play_minor

# Bottom-row major-improvement indices (the work-station crafts).
_BOTTOM = (5, 6, 7, 8, 9)
# Top-row indices (Fireplaces / Cooking Hearths / Well) — must NOT count.
_TOP = (0, 1, 2, 3, 4)

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("artisan_district",) + tuple(f"m{i}" for i in range(20)),
)


def _state(*, n_occupations=3, in_hand=True, stone=1, seed=5):
    """Game state with `artisan_district` in the current player's hand, the
    player holding `n_occupations` occupations and `stone` stone."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    hand = frozenset({"artisan_district"}) if in_hand else frozenset()
    occs = frozenset(f"occ{i}" for i in range(n_occupations))
    p = fast_replace(cs.players[cp], hand_minors=hand, occupations=occs)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    cs = with_resources(cs, cp, stone=stone)
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


def _own_majors(cs, cp, idxs):
    """Give player `cp` ownership of the given major-improvement indices."""
    return with_majors(cs, owner_by_idx={m: cp for m in idxs})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_artisan_district_registered():
    assert "artisan_district" in MINORS
    spec = MINORS["artisan_district"]
    assert spec.vps == 1
    assert spec.passing_left is False
    # 1-stone printed cost, no animals.
    assert spec.cost == Cost(resources=Resources(stone=1))
    assert spec.cost.animals == Animals()
    # "3 Occupations" is a prereq, modeled via min_occupations (not a cost).
    assert spec.min_occupations == 3
    assert spec.prereq is None
    # End-game scoring term, not a trigger card.
    assert "artisan_district" not in CARDS
    assert any(cid == "artisan_district" for cid, _ in SCORING_TERMS)


# ---------------------------------------------------------------------------
# Prerequisite eligibility boundary (3 occupations)
# ---------------------------------------------------------------------------

def test_prereq_met_with_three_occupations():
    cs, cp = _state(n_occupations=3)
    assert prereq_met(MINORS["artisan_district"], cs, cp) is True
    assert "artisan_district" in playable_minors(cs, cp)


def test_prereq_met_with_more_than_three_occupations():
    cs, cp = _state(n_occupations=5)
    assert prereq_met(MINORS["artisan_district"], cs, cp) is True


def test_prereq_blocked_with_two_occupations():
    cs, cp = _state(n_occupations=2)
    assert prereq_met(MINORS["artisan_district"], cs, cp) is False
    assert "artisan_district" not in playable_minors(cs, cp)


def test_prereq_blocked_with_zero_occupations():
    cs, cp = _state(n_occupations=0)
    assert prereq_met(MINORS["artisan_district"], cs, cp) is False


def test_unaffordable_without_stone():
    # Prereq met but no stone → not offered (cost not affordable).
    cs, cp = _state(n_occupations=3, stone=0)
    assert prereq_met(MINORS["artisan_district"], cs, cp) is True
    assert "artisan_district" not in playable_minors(cs, cp)


# ---------------------------------------------------------------------------
# The scoring bonus: step function over bottom-row major count
# ---------------------------------------------------------------------------

def test_bottom_row_count_counts_only_indices_5_to_9():
    cs, cp = _state()
    cs = _own_majors(cs, cp, _BOTTOM)
    assert _bottom_row_count(cs, cp) == 5


def test_top_row_majors_do_not_count():
    # Owning every TOP-row major (Fireplaces, Cooking Hearths, Well) → 0.
    cs, cp = _state()
    cs = _own_majors(cs, cp, _TOP)
    assert _bottom_row_count(cs, cp) == 0
    assert _bonus(cs, cp) == 0


def test_bonus_zero_below_three():
    cs, cp = _state()
    # 0 bottom-row owned.
    assert _bonus(cs, cp) == 0
    # 1 bottom-row owned.
    cs1 = _own_majors(cs, cp, (5,))
    assert _bottom_row_count(cs1, cp) == 1
    assert _bonus(cs1, cp) == 0
    # 2 bottom-row owned.
    cs2 = _own_majors(cs, cp, (5, 6))
    assert _bottom_row_count(cs2, cp) == 2
    assert _bonus(cs2, cp) == 0


def test_bonus_two_for_three():
    cs, cp = _state()
    cs = _own_majors(cs, cp, (5, 6, 7))
    assert _bottom_row_count(cs, cp) == 3
    assert _bonus(cs, cp) == 2


def test_bonus_five_for_four():
    cs, cp = _state()
    cs = _own_majors(cs, cp, (5, 6, 7, 8))
    assert _bottom_row_count(cs, cp) == 4
    assert _bonus(cs, cp) == 5


def test_bonus_eight_for_five():
    cs, cp = _state()
    cs = _own_majors(cs, cp, _BOTTOM)
    assert _bottom_row_count(cs, cp) == 5
    assert _bonus(cs, cp) == 8


def test_opponent_owned_bottom_row_does_not_count():
    # Opponent owns three bottom-row majors; the owner gets nothing for them.
    cs, cp = _state()
    cs = with_majors(cs, owner_by_idx={5: 1 - cp, 6: 1 - cp, 7: 1 - cp})
    assert _bottom_row_count(cs, cp) == 0
    assert _bonus(cs, cp) == 0
    # And the opponent (perspective) does see them.
    assert _bottom_row_count(cs, 1 - cp) == 3
    assert _bonus(cs, 1 - cp) == 2


# ---------------------------------------------------------------------------
# Scoring integration: ownership gate + printed vps
# ---------------------------------------------------------------------------

def test_scoring_term_only_applies_to_owner():
    # The owner has the card kept AND owns four bottom-row majors → +5 bonus +1
    # printed vps. The opponent, despite owning the same majors here, holds no
    # copy of the card, so the term doesn't apply to them.
    cs, cp = _state()
    cs = with_minors(cs, cp, frozenset({"artisan_district"}))
    cs = _own_majors(cs, cp, (5, 6, 7, 8))
    _total_owner, bd_owner = score(cs, cp)
    _total_opp, bd_opp = score(cs, 1 - cp)
    # Owner: +5 bonus AND +1 printed vps = 6 card_points.
    assert bd_owner.card_points == 6
    # Opponent owns no copy → 0 card points.
    assert bd_opp.card_points == 0


def test_scoring_zero_bonus_below_three_still_gives_printed_vp():
    cs, cp = _state()
    cs = with_minors(cs, cp, frozenset({"artisan_district"}))
    cs = _own_majors(cs, cp, (5, 6))  # only 2 bottom-row → 0 bonus
    _total, bd = score(cs, cp)
    # 0 bonus + 1 printed vps.
    assert bd.card_points == 1


# ---------------------------------------------------------------------------
# On-play via a real engine play-minor flow
# ---------------------------------------------------------------------------

def test_play_artisan_district_pays_stone_and_kept():
    cs, cp = _state(n_occupations=3, stone=1)
    cs = _push_minor(cs, cp)
    # Prereq met (3 occupations) + affordable (1 stone) → the play is offered.
    assert legal_actions(cs) == [sole_play_minor(cs, "artisan_district")]
    cs = step(cs, sole_play_minor(cs, "artisan_district"))
    p = cs.players[cp]
    assert p.resources.stone == 0                            # paid 1 stone
    assert "artisan_district" in p.minor_improvements        # non-passing → kept
    assert "artisan_district" not in p.hand_minors           # left my hand
    assert "artisan_district" not in cs.players[1 - cp].hand_minors  # not circulated


def test_play_blocked_with_two_occupations():
    cs, cp = _state(n_occupations=2, stone=1)
    cs = _push_minor(cs, cp)
    from agricola.actions import CommitPlayMinor
    plays = [
        a for a in legal_actions(cs)
        if isinstance(a, CommitPlayMinor) and a.card_id == "artisan_district"
    ]
    assert plays == []


def test_printed_vps_and_bonus_scored_after_play():
    cs, cp = _state(n_occupations=3, stone=1)
    cs = _own_majors(cs, cp, (5, 6, 7, 8, 9))  # all 5 bottom-row → +8 bonus
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "artisan_district"))
    _total, bd = score(cs, cp)
    # +8 bonus (register_scoring) + +1 printed vps = 9.
    assert bd.card_points == 9


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
