"""Tests for Imitator (occupation, E129; Ephipparius Expansion; players 3+).

Card text: "If you have a person on the "Day Laborer" action space, you can use
non-accumulating round 1-9 action spaces even if they are occupied."

A `register_occupancy_override` (Sleeping Corner / Forest School seam): the owner
may place on an occupied space iff they hold a Day Laborer worker, the space is a
non-accumulating stage card revealed in rounds 1-9, and they do not already hold it.
"""
import agricola.cards.imitator  # noqa: F401  (registers the card)

from agricola.actions import PlaceWorker
from agricola.cards.imitator import CARD_ID, _occupancy_override
from agricola.cards.specs import OCCUPATIONS
from agricola.legality import OCCUPANCY_OVERRIDE_EXTENSIONS, legal_actions
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.setup import setup
from tests.factories import with_current_player, with_space

# A non-accumulating round-1-9 space whose placement gate is availability-only.
_TARGET = "vegetable_seeds"


def _scenario(*, own=True, dl_workers=(1, 0), space=_TARGET,
              revealed_round=8, target_workers=(0, 1), accumulated_amount=0):
    """P0 is current, (optionally) owns Imitator, has `dl_workers` on Day Laborer,
    and `space` is revealed with `revealed_round` + `target_workers`."""
    s = with_current_player(setup(0), 0)
    if own:
        p = fast_replace(s.players[0], occupations=frozenset({CARD_ID}))
        s = fast_replace(s, players=tuple(p if i == 0 else s.players[i] for i in range(2)))
    s = with_space(s, "day_laborer", workers=dl_workers)
    s = with_space(s, space, revealed=True, revealed_round=revealed_round,
                   workers=target_workers, accumulated_amount=accumulated_amount)
    return s


def _placeable(s, space=_TARGET):
    return space in [a.space for a in legal_actions(s) if isinstance(a, PlaceWorker)]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registered():
    assert CARD_ID in OCCUPATIONS
    assert _occupancy_override in OCCUPANCY_OVERRIDE_EXTENSIONS


# ---------------------------------------------------------------------------
# End-to-end: the occupied round-1-9 space becomes placeable and resolves
# ---------------------------------------------------------------------------

def test_can_place_on_occupied_round_1_9_space():
    s = _scenario()
    assert _placeable(s)
    veg0 = s.players[0].resources.veg
    s = step(s, PlaceWorker(space=_TARGET))         # actually place there
    assert s.players[0].resources.veg == veg0 + 1   # Vegetable Seeds resolved


# ---------------------------------------------------------------------------
# Each condition is load-bearing (tested through the override predicate)
# ---------------------------------------------------------------------------

def test_needs_a_day_laborer_worker():
    s = _scenario(dl_workers=(0, 0))
    assert not _occupancy_override(s, _TARGET)
    assert not _placeable(s)


def test_only_non_accumulating_spaces():
    # western_quarry is a round-1-9 (stage 2) space, but it ACCUMULATES stone.
    s = _scenario(space="western_quarry", revealed_round=6, accumulated_amount=2)
    assert not _occupancy_override(s, "western_quarry")


def test_only_rounds_1_through_9():
    s = _scenario(revealed_round=10)
    assert not _occupancy_override(s, _TARGET)
    assert not _placeable(s)
    s0 = _scenario(revealed_round=9)                # the boundary is included
    assert _occupancy_override(s0, _TARGET)


def test_permanent_space_excluded():
    # A permanent space carries revealed_round 0 -> never a "round 1-9" space.
    s = _scenario(space="lessons", revealed_round=0, target_workers=(0, 1))
    assert not _occupancy_override(s, "lessons")


def test_not_a_space_the_owner_already_holds():
    s = _scenario(target_workers=(1, 1))            # P0 also has a worker here
    assert not _occupancy_override(s, _TARGET)
    assert not _placeable(s)


def test_unowned_is_inert():
    s = _scenario(own=False)
    assert not _occupancy_override(s, _TARGET)
    assert not _placeable(s)


def test_unoccupied_space_is_normal_placement():
    # With no opponent worker, the space is placeable the ordinary way (the
    # override is only consulted on the occupied branch).
    s = _scenario(target_workers=(0, 0))
    assert _placeable(s)
