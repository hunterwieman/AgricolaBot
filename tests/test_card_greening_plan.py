"""Greening Plan (minor, C #33): cost 3 food; during scoring, with at least
2/4/5/6 unplanted fields you get 1/2/3/5 bonus points.

Covers: registration (cost, no prereq/on-play/vps), the scoring ladder at every
band + boundaries, the "unplanted = FIELD with grain==0 AND veg==0" rule
(plowed-but-unsown counts; a sown field does not), ownership-scoping (only the
owner scores it), and the real play-flow that pays 3 food and keeps the card.
"""
import agricola.cards.greening_plan  # noqa: F401

from agricola.actions import ChooseSubAction, PlaceWorker
from agricola.cards.greening_plan import (
    _bonus_for,
    count_unplanted_fields,
)
from agricola.cards.specs import MINORS
from agricola.constants import CellType
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup, setup_env
from agricola.scoring import score
from agricola.state import Cell, get_space, with_space
from tests.factories import with_grid, with_resources
from tests.test_utils import sole_play_minor

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=("greening_plan",) + tuple(f"m{i}" for i in range(20)),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _own_minor(state, idx, card_id):
    p = fast_replace(
        state.players[idx],
        minor_improvements=state.players[idx].minor_improvements | {card_id},
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _unplanted_field(r, c):
    return (r, c), Cell(cell_type=CellType.FIELD)


def _planted_field(r, c, *, grain=0, veg=0):
    return (r, c), Cell(cell_type=CellType.FIELD, grain=grain, veg=veg)


def _set_fields(state, idx, cells):
    """cells: list of ((r,c), Cell) overrides."""
    return with_grid(state, idx, dict(cells))


def _reveal_improvement_space(state):
    sp = fast_replace(
        get_space(state.board, "major_improvement"), revealed=True, workers=(0, 0)
    )
    return fast_replace(state, board=with_space(state.board, "major_improvement", sp))


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration_cost_and_no_flat_terms():
    spec = MINORS["greening_plan"]
    assert spec.cost == Cost(resources=Resources(food=3))
    assert spec.prereq is None
    assert spec.vps == 0                       # bonus is variable, not a flat vps
    assert spec.passing_left is False


def test_registered_in_scoring_terms():
    from agricola.scoring import SCORING_TERMS
    assert any(cid == "greening_plan" for cid, _ in SCORING_TERMS)


# ---------------------------------------------------------------------------
# The bonus ladder (pure mapping)
# ---------------------------------------------------------------------------

def test_bonus_ladder_every_band():
    # >= 2/4/5/6 unplanted fields -> 1/2/3/5 points.
    assert _bonus_for(0) == 0
    assert _bonus_for(1) == 0              # below the first threshold
    assert _bonus_for(2) == 1
    assert _bonus_for(3) == 1              # GAP: 3 fields still only 1 point
    assert _bonus_for(4) == 2
    assert _bonus_for(5) == 3
    assert _bonus_for(6) == 5              # JUMP: 5 -> 6 fields is +2 points


# ---------------------------------------------------------------------------
# count_unplanted_fields — what counts as "unplanted"
# ---------------------------------------------------------------------------

def test_count_unplanted_plowed_but_unsown_counts():
    s = setup(0)
    s = _set_fields(s, 0, [_unplanted_field(0, 0), _unplanted_field(0, 1)])
    assert count_unplanted_fields(s.players[0].farmyard) == 2


def test_count_unplanted_sown_field_does_not_count():
    s = setup(0)
    s = _set_fields(
        s,
        0,
        [
            _unplanted_field(0, 0),
            _planted_field(0, 1, grain=2),     # sown grain -> not unplanted
            _planted_field(0, 2, veg=1),       # sown veg   -> not unplanted
        ],
    )
    # Only the single empty field counts.
    assert count_unplanted_fields(s.players[0].farmyard) == 1


def test_count_unplanted_ignores_non_field_cells():
    s = setup(0)
    # The starting farmyard has 2 rooms + empty cells; none are FIELD.
    assert count_unplanted_fields(s.players[0].farmyard) == 0


# ---------------------------------------------------------------------------
# Scoring through score() with ownership scoping
# ---------------------------------------------------------------------------

def test_score_awards_band_for_owner():
    s = setup(0)
    # 4 unplanted fields -> band 2 points.
    s = _set_fields(
        s, 0,
        [_unplanted_field(0, 0), _unplanted_field(0, 1),
         _unplanted_field(0, 2), _unplanted_field(0, 3)],
    )
    base, _ = score(s, 0)
    s_own = _own_minor(s, 0, "greening_plan")
    total, bd = score(s_own, 0)
    assert bd.card_points == 2
    assert total == base + 2


def test_score_six_fields_top_band():
    s = setup(0)
    s = _set_fields(
        s, 0,
        [_unplanted_field(0, 0), _unplanted_field(0, 1), _unplanted_field(0, 2),
         _unplanted_field(0, 3), _unplanted_field(0, 4), _unplanted_field(1, 0)],
    )
    s = _own_minor(s, 0, "greening_plan")
    _t, bd = score(s, 0)
    assert bd.card_points == 5


def test_score_below_threshold_zero():
    s = setup(0)
    s = _set_fields(s, 0, [_unplanted_field(0, 0)])     # 1 field, < 2
    s = _own_minor(s, 0, "greening_plan")
    _t, bd = score(s, 0)
    assert bd.card_points == 0


def test_score_scoped_to_owner_only():
    s = setup(0)
    # Give player 1 the fields but the card to player 0 -> player 1 scores nothing.
    s = _set_fields(
        s, 1,
        [_unplanted_field(0, 0), _unplanted_field(0, 1),
         _unplanted_field(0, 2), _unplanted_field(0, 3)],
    )
    s = _own_minor(s, 0, "greening_plan")        # owner is player 0
    _t0, bd0 = score(s, 0)
    _t1, bd1 = score(s, 1)
    assert bd0.card_points == 0                  # owner has no unplanted fields
    assert bd1.card_points == 0                  # non-owner does not score the card


def test_sown_fields_suppress_bonus():
    s = setup(0)
    # Six FIELD cells, but all sown -> zero unplanted -> no bonus.
    s = _set_fields(
        s, 0,
        [_planted_field(0, c, grain=1) for c in range(5)]
        + [_planted_field(1, 0, veg=1)],
    )
    s = _own_minor(s, 0, "greening_plan")
    _t, bd = score(s, 0)
    assert bd.card_points == 0


# ---------------------------------------------------------------------------
# Real play flow: pay 3 food, keep the card (not passing)
# ---------------------------------------------------------------------------

def test_play_flow_pays_food_and_keeps_card():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, food=4)
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"greening_plan"}))
    cs = fast_replace(
        cs, players=tuple(p if i == cp else cs.players[i] for i in range(2))
    )

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    cs = step(cs, sole_play_minor(cs, "greening_plan"))

    assert cs.players[cp].resources.food == 1                  # 4 - 3 cost
    assert "greening_plan" in cs.players[cp].minor_improvements  # kept, not passed
    assert "greening_plan" not in cs.players[1 - cp].hand_minors


def test_play_flow_unaffordable_not_in_legal():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _reveal_improvement_space(cs)
    cp = cs.current_player
    cs = with_resources(cs, cp, food=2)                        # only 2 food, need 3
    p = fast_replace(cs.players[cp], hand_minors=frozenset({"greening_plan"}))
    cs = fast_replace(
        cs, players=tuple(p if i == cp else cs.players[i] for i in range(2))
    )

    cs = step(cs, PlaceWorker(space="major_improvement"))
    cs = step(cs, ChooseSubAction(name="improvement"))
    cs = step(cs, ChooseSubAction(name="play_minor"))
    from agricola.legality import legal_actions
    from agricola.actions import CommitPlayMinor
    played = [
        a for a in legal_actions(cs)
        if isinstance(a, CommitPlayMinor) and a.card_id == "greening_plan"
    ]
    assert played == []                                       # cannot afford it
