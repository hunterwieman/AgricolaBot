"""Tests for Pottery Yard (minor improvement, B31; Bubulcus Expansion).

Card text (verbatim): "During the scoring, if there are at least 2 orthogonally
adjacent unused spaces in your farm, you get 2 bonus points. (You still get the
negative points for those unused spaces.)"
Prerequisite: Pottery (or an Upgrade Thereof). Printed VPs: 1. No cost.

Covers: registration (no cost, +1 vps, prereq predicate, scoring term);
the prereq eligibility boundary (owns Pottery fires; doesn't own / opponent owns
blocks); the +2 adjacency bonus (two orthogonally adjacent unused cells → +2;
no adjacent pair → 0; the ownership gate so the term applies only to the owner;
enclosed cells don't count as unused); and a real play-minor engine flow
(no cost, kept in tableau, +1 printed vps).
"""
import agricola.cards.pottery_yard  # noqa: F401  (registers the card)

import dataclasses

import pytest

from agricola.cards.pottery_yard import _bonus, _owns_pottery
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import CARDS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.scoring import SCORING_TERMS, score
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import with_grid, with_majors, with_minors, with_pending_stack
from tests.test_utils import sole_play_minor

_POTTERY_IDX = 8

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("pottery_yard",) + tuple(f"m{i}" for i in range(20)),
)


def _state(*, owns_pottery=True, in_hand=True, seed=5):
    """Game state with `pottery_yard` in the current player's hand and (by
    default) that player owning Pottery."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    hand = frozenset({"pottery_yard"}) if in_hand else frozenset()
    p = fast_replace(cs.players[cp], hand_minors=hand)
    opp = fast_replace(cs.players[1 - cp], hand_minors=frozenset())
    cs = fast_replace(cs, players=tuple(p if i == cp else opp for i in range(2)))
    if owns_pottery:
        cs = with_majors(cs, owner_by_idx={_POTTERY_IDX: cp})
    return cs, cp


def _push_minor(cs, cp):
    return with_pending_stack(
        cs, (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),)
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_pottery_yard_registered():
    assert "pottery_yard" in MINORS
    spec = MINORS["pottery_yard"]
    assert spec.vps == 1
    assert spec.passing_left is False
    # No printed cost.
    assert spec.cost.resources == Resources() and spec.cost.animals == Animals()
    assert spec.cost == Cost()
    assert spec.prereq is not None
    # End-game scoring term, not a trigger card.
    assert "pottery_yard" not in CARDS
    assert any(cid == "pottery_yard" for cid, _ in SCORING_TERMS)


# ---------------------------------------------------------------------------
# Prerequisite eligibility boundary
# ---------------------------------------------------------------------------

def test_prereq_met_when_owns_pottery():
    cs, cp = _state(owns_pottery=True)
    assert _owns_pottery(cs, cp) is True
    assert prereq_met(MINORS["pottery_yard"], cs, cp) is True
    assert "pottery_yard" in playable_minors(cs, cp)


def test_prereq_blocked_without_pottery():
    cs, cp = _state(owns_pottery=False)
    assert _owns_pottery(cs, cp) is False
    assert prereq_met(MINORS["pottery_yard"], cs, cp) is False
    assert "pottery_yard" not in playable_minors(cs, cp)


def test_prereq_blocked_when_opponent_owns_pottery():
    cs, cp = _state(owns_pottery=False)
    cs = with_majors(cs, owner_by_idx={_POTTERY_IDX: 1 - cp})
    assert _owns_pottery(cs, cp) is False
    assert prereq_met(MINORS["pottery_yard"], cs, cp) is False


# ---------------------------------------------------------------------------
# Scoring bonus: the +2 adjacency term
# ---------------------------------------------------------------------------

def test_bonus_is_two_on_a_fresh_farm():
    # A fresh farm: rooms at (1,0),(2,0); every other cell is EMPTY and
    # unenclosed → many orthogonally adjacent unused pairs.
    cs, cp = _state()
    assert _bonus(cs, cp) == 2


def _fill_all_empty_with_fields(cs, cp):
    """Turn every EMPTY cell into a FIELD so NO unused (empty) spaces remain."""
    grid = cs.players[cp].farmyard.grid
    overrides = {
        (r, c): Cell(cell_type=CellType.FIELD)
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY
    }
    return with_grid(cs, cp, overrides)


def test_bonus_zero_when_no_unused_spaces():
    cs, cp = _state()
    cs = _fill_all_empty_with_fields(cs, cp)
    assert _bonus(cs, cp) == 0


def test_bonus_zero_when_only_isolated_unused_cells():
    # Leave exactly two EMPTY cells, diagonally apart (not orthogonally
    # adjacent): (0,0) and (1,1). Fill everything else (incl. the starting
    # rooms' column neighbors) so no orthogonal unused pair exists.
    cs, cp = _state()
    grid = cs.players[cp].farmyard.grid
    keep_empty = {(0, 0), (1, 1)}
    overrides = {
        (r, c): Cell(cell_type=CellType.FIELD)
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY and (r, c) not in keep_empty
    }
    cs = with_grid(cs, cp, overrides)
    # (0,0) and (1,1) are the only unused cells and share no edge.
    assert _bonus(cs, cp) == 0


def test_bonus_two_for_a_single_orthogonal_pair():
    # Leave exactly two orthogonally adjacent EMPTY cells: (0,0) and (0,1).
    cs, cp = _state()
    grid = cs.players[cp].farmyard.grid
    keep_empty = {(0, 0), (0, 1)}
    overrides = {
        (r, c): Cell(cell_type=CellType.FIELD)
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY and (r, c) not in keep_empty
    }
    cs = with_grid(cs, cp, overrides)
    assert _bonus(cs, cp) == 2


def test_bonus_vertical_adjacency_also_counts():
    # Two vertically adjacent EMPTY cells: (0,2) and (1,2).
    cs, cp = _state()
    grid = cs.players[cp].farmyard.grid
    keep_empty = {(0, 2), (1, 2)}
    overrides = {
        (r, c): Cell(cell_type=CellType.FIELD)
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.EMPTY and (r, c) not in keep_empty
    }
    cs = with_grid(cs, cp, overrides)
    assert _bonus(cs, cp) == 2


# ---------------------------------------------------------------------------
# Scoring integration: ownership gate + printed vps
# ---------------------------------------------------------------------------

def test_scoring_term_only_applies_to_owner():
    # Owner (kept the minor) gets the +2; opponent's identical farm does not,
    # because the term is gated on owning the card.
    cs, cp = _state()
    cs = with_minors(cs, cp, frozenset({"pottery_yard"}))
    _total_owner, bd_owner = score(cs, cp)
    _total_opp, bd_opp = score(cs, 1 - cp)
    # Owner: +2 bonus AND +1 printed vps = 3 card_points.
    assert bd_owner.card_points == 3
    # Opponent owns nothing → 0 card points despite the same fresh farm.
    assert bd_opp.card_points == 0


def test_unused_penalty_still_applies_for_owner():
    # The parenthetical: the engine's unused-space penalty is untouched. On a
    # fresh farm there are many unused spaces, so unused_spaces is negative even
    # with the card kept.
    cs, cp = _state()
    cs = with_minors(cs, cp, frozenset({"pottery_yard"}))
    _total, bd = score(cs, cp)
    assert bd.unused_spaces < 0


# ---------------------------------------------------------------------------
# On-play via a real engine play-minor flow
# ---------------------------------------------------------------------------

def test_play_pottery_yard_no_cost_and_kept():
    cs, cp = _state()
    res_before = cs.players[cp].resources
    cs = _push_minor(cs, cp)
    # Prereq met (owns Pottery) → the play is offered.
    assert legal_actions(cs) == [sole_play_minor(cs, "pottery_yard")]
    cs = step(cs, sole_play_minor(cs, "pottery_yard"))
    p = cs.players[cp]
    assert p.resources == res_before                     # no cost paid
    assert "pottery_yard" in p.minor_improvements        # non-passing → kept
    assert "pottery_yard" not in p.hand_minors           # left my hand
    assert "pottery_yard" not in cs.players[1 - cp].hand_minors  # not circulated


def test_play_blocked_without_pottery():
    cs, cp = _state(owns_pottery=False)
    cs = _push_minor(cs, cp)
    # Prereq not met → no CommitPlayMinor for pottery_yard is offered.
    from agricola.actions import CommitPlayMinor
    plays = [
        a for a in legal_actions(cs)
        if isinstance(a, CommitPlayMinor) and a.card_id == "pottery_yard"
    ]
    assert plays == []


def test_printed_vps_scored_from_spec():
    cs, cp = _state()
    cs = _push_minor(cs, cp)
    cs = step(cs, sole_play_minor(cs, "pottery_yard"))
    _total, bd = score(cs, cp)
    # Fresh farm → +2 bonus (register_scoring) + +1 printed vps = 3.
    assert bd.card_points == 3


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
