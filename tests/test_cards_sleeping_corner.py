"""Tests for Sleeping Corner (minor improvement A26):

  - the LEGALITY RELAXATION (occupancy override): the owner may place on a "Wish for
    Children" space occupied by one opponent, exercised through `legal_placements`;
  - the boundaries: not offered without ownership, not for non-wish spaces, not when the
    owner already holds the space, and (4-player shape) not when 2+ other players hold it;
  - that "count players, not workers" tolerates an opponent's parent+newborn pair;
  - the 2-grain-fields prerequisite;
  - Family byte-identity (no card owned -> occupied wish space stays illegal).
"""
import pytest

from agricola.actions import PlaceWorker
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.sleeping_corner import CARD_ID
from agricola.constants import CellType
from agricola.legality import OCCUPANCY_OVERRIDE_EXTENSIONS, legal_placements
from agricola.setup import setup_env
from agricola.state import Cell

import tests.factories as f

# Use Urgent Wish (legal whenever people_total < 5) so the test isolates the occupancy
# override; Basic Wish additionally needs more rooms than people, which a setup state lacks.
WISH = "urgent_wish_for_children"


def _state(seed=5, *, owner=None, occupant=None, owner_grain_fields=2):
    """Card-mode state with WISH revealed, p0 to move. `owner` set -> p0 owns Sleeping
    Corner; `occupant` -> that player has `n` workers placed on WISH."""
    cs, _env = setup_env(seed, card_pool=None)
    cs = f.with_current_player(cs, 0)
    cs = f.with_space(cs, WISH, revealed=True)
    if owner is not None:
        cs = f.with_minors(cs, owner, frozenset({CARD_ID}))
    if owner_grain_fields:
        cells = {(0, c): Cell(cell_type=CellType.FIELD, grain=3)
                 for c in range(owner_grain_fields)}
        cs = f.with_grid(cs, 0, cells)
    return cs


def _set_workers(cs, w):
    return f.with_space(cs, WISH, workers=w)


def _wish_placeable(cs):
    return PlaceWorker(space=WISH) in legal_placements(cs)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert len(OCCUPANCY_OVERRIDE_EXTENSIONS) >= 1
    spec = MINORS[CARD_ID]
    assert spec.vps == 1
    assert spec.cost.resources.wood == 1


# ---------------------------------------------------------------------------
# The relaxation
# ---------------------------------------------------------------------------

def test_owner_may_use_wish_occupied_by_opponent():
    cs = _state(owner=0)
    cs = _set_workers(cs, (0, 1))   # opponent (p1) holds the wish space
    assert _wish_placeable(cs)


def test_owner_may_use_wish_with_opponent_parent_and_newborn():
    # A normally-used wish space holds the opponent's parent + newborn = 2 workers, ONE
    # player. "Count players, not workers" must still permit the owner to use it.
    cs = _state(owner=0)
    cs = _set_workers(cs, (0, 2))
    assert _wish_placeable(cs)


# ---------------------------------------------------------------------------
# Boundaries
# ---------------------------------------------------------------------------

def test_not_offered_without_ownership():
    cs = _state(owner=None)
    cs = _set_workers(cs, (0, 1))
    assert not _wish_placeable(cs)


def test_not_offered_when_owner_already_holds_the_space():
    cs = _state(owner=0)
    cs = _set_workers(cs, (1, 0))   # the owner (p0) is the sole occupant
    assert not _wish_placeable(cs)


def test_override_does_not_apply_to_non_wish_spaces():
    # The override predicate self-restricts to the wish spaces.
    cs = _state(owner=0)
    cs = f.with_space(cs, "forest", revealed=True, workers=(0, 1))
    assert PlaceWorker(space="forest") not in legal_placements(cs)


def test_two_other_players_blocks_override():
    # 4-player shape: 2+ OTHER players holding the space -> override declines (== 1 only).
    cs = _state(owner=0)
    fn = _sleeping_corner_override()
    cs = _set_workers(cs, (0, 1))
    # Forge a 3-slot worker tuple so two *other* players hold the space.
    cs3 = f.with_space(cs, WISH, workers=(0, 1, 1))
    assert fn(cs3, WISH) is False
    assert fn(cs, WISH) is True


def _sleeping_corner_override():
    from agricola.cards.sleeping_corner import _occupancy_override
    return _occupancy_override


# ---------------------------------------------------------------------------
# Unoccupied space — the override is irrelevant; normal legality applies
# ---------------------------------------------------------------------------

def test_unoccupied_wish_placeable_regardless():
    cs = _state(owner=0)
    cs = _set_workers(cs, (0, 0))
    assert _wish_placeable(cs)


# ---------------------------------------------------------------------------
# Prerequisite: 2 grain fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n,expected", [(0, False), (1, False), (2, True), (3, True)])
def test_prereq_two_grain_fields(n, expected):
    cs = _state(owner=0, owner_grain_fields=0)
    cells = {(0, c): Cell(cell_type=CellType.FIELD, grain=3) for c in range(n)}
    cs = f.with_grid(cs, 0, cells)
    assert prereq_met(MINORS[CARD_ID], cs, 0) is expected


def test_prereq_empty_field_does_not_count():
    # A plowed but unsown field is not a "grain field".
    cs = _state(owner=0, owner_grain_fields=0)
    cells = {(0, 0): Cell(cell_type=CellType.FIELD, grain=0),
             (0, 1): Cell(cell_type=CellType.FIELD, grain=0),
             (0, 2): Cell(cell_type=CellType.FIELD, grain=3)}
    cs = f.with_grid(cs, 0, cells)
    assert prereq_met(MINORS[CARD_ID], cs, 0) is False


def test_prereq_veg_field_does_not_count():
    cs = _state(owner=0, owner_grain_fields=0)
    cells = {(0, 0): Cell(cell_type=CellType.FIELD, veg=2),
             (0, 1): Cell(cell_type=CellType.FIELD, veg=2)}
    cs = f.with_grid(cs, 0, cells)
    assert prereq_met(MINORS[CARD_ID], cs, 0) is False
