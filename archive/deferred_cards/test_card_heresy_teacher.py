"""Heresy Teacher (occupation, A113): each time you use a Lessons action space,
you get 1 vegetable in each field with at least 3 grain and no vegetable.

Card text: "Each time you use a 'Lessons' action space, you get 1 vegetable in
each of your fields with at least 3 grain and no vegetable. Place the vegetable
below the grain."

The effect fires in the Lessons host's BEFORE-phase (the "each time you use"
ruling → before_action_space), at the PlaceWorker("lessons") push. The card is an
occupation, so it must already be in the player's tableau for the auto to fire.

Card-fields (ruling 45, 2026-07-12): "field" is the broader category and
includes card-fields, so a card-field holding 3+ grain and no vegetable gains
the below-the-grain vegetable too — on its grain-bearing stack, which the
field-phase take then harvests grain-first exactly like a grid cell.
"""
import agricola.cards.crop_rotation_field  # noqa: F401  (registers a grain-capable card-field)
import agricola.cards.heresy_teacher  # noqa: F401  (registers the card)
import agricola.cards.stable_architect  # noqa: F401  (a registered no-op-on-play occupation, played to drive Lessons)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker, Stop
from agricola.cards.card_fields import card_field_stacks, stacks_to_store
from agricola.cards.specs import OCCUPATIONS
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.constants import CellType
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.resolution import field_take
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space

_POOL = CardPool(
    occupations=("heresy_teacher", "stable_architect") + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5, *, occupations=frozenset({"heresy_teacher"}),
                hand=frozenset({"stable_architect"})):
    """A card-mode round-1 WORK state with the current player owning
    heresy_teacher and holding a no-op occupation to play via Lessons."""
    cs, _env = setup_env(seed, card_pool=_POOL)
    cp = cs.current_player
    p = fast_replace(cs.players[cp], hand_occupations=hand, occupations=occupations)
    cs = fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)),
                      current_player=cp)
    return cs, cp


def _set_grid(cs, cp, overrides):
    """Replace cells in cp's farmyard grid (overrides: {(r, c): Cell})."""
    grid = cs.players[cp].farmyard.grid
    new_grid = tuple(
        tuple(overrides.get((r, c), grid[r][c]) for c in range(5))
        for r in range(3)
    )
    fy = fast_replace(cs.players[cp].farmyard, grid=new_grid)
    p = fast_replace(cs.players[cp], farmyard=fy)
    return fast_replace(cs, players=tuple(p if i == cp else cs.players[i] for i in range(2)))


def _veg_at(cs, cp, r, c):
    return cs.players[cp].farmyard.grid[r][c].veg


def _grain_at(cs, cp, r, c):
    return cs.players[cp].farmyard.grid[r][c].grain


def _use_lessons(cs):
    """Drive one full Lessons use (play the no-op stable_architect occupation)."""
    cs = step(cs, PlaceWorker(space="lessons"))   # before_action_space fires HERE
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id="stable_architect"))
    cs = step(cs, Stop())   # pop the occupation child → host flips to after
    cs = step(cs, Stop())   # pop the Lessons host frame
    return cs


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_heresy_teacher_registered():
    assert "heresy_teacher" in OCCUPATIONS
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert "heresy_teacher" in auto_ids
    # Lessons self-hosts → it is NOT in the atomic-space hook index.
    assert "heresy_teacher" not in OWN_ACTION_HOOK_CARDS.get("lessons", set())


# ---------------------------------------------------------------------------
# Effect: a qualifying field (grain >= 3, veg == 0) gets +1 veg
# ---------------------------------------------------------------------------

def test_qualifying_field_gets_one_veg():
    cs, cp = _card_state()
    cs = _set_grid(cs, cp, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3, veg=0)})
    assert _veg_at(cs, cp, 0, 0) == 0

    cs = step(cs, PlaceWorker(space="lessons"))   # before_action_space fires
    # The vegetable is placed "below the grain": veg becomes 1, grain untouched.
    assert _veg_at(cs, cp, 0, 0) == 1
    assert _grain_at(cs, cp, 0, 0) == 3


def test_fires_for_every_qualifying_field_at_once():
    cs, cp = _card_state()
    cs = _set_grid(cs, cp, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3, veg=0),
        (0, 1): Cell(cell_type=CellType.FIELD, grain=5, veg=0),
        (1, 2): Cell(cell_type=CellType.FIELD, grain=3, veg=0),
    })
    cs = step(cs, PlaceWorker(space="lessons"))
    assert _veg_at(cs, cp, 0, 0) == 1
    assert _veg_at(cs, cp, 0, 1) == 1
    assert _veg_at(cs, cp, 1, 2) == 1


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_field_with_too_little_grain_does_not_qualify():
    cs, cp = _card_state()
    cs = _set_grid(cs, cp, {(0, 0): Cell(cell_type=CellType.FIELD, grain=2, veg=0)})
    cs = step(cs, PlaceWorker(space="lessons"))
    assert _veg_at(cs, cp, 0, 0) == 0   # grain < 3 → no veg
    assert _grain_at(cs, cp, 0, 0) == 2


def test_field_already_holding_veg_does_not_qualify():
    # A mixed grain+veg field (the clarification case) is excluded by veg == 0.
    cs, cp = _card_state()
    cs = _set_grid(cs, cp, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3, veg=1)})
    cs = step(cs, PlaceWorker(space="lessons"))
    assert _veg_at(cs, cp, 0, 0) == 1   # unchanged (not bumped to 2)


def test_empty_field_and_non_field_cells_unaffected():
    cs, cp = _card_state()
    cs = _set_grid(cs, cp, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=0, veg=0),   # empty field
        (0, 1): Cell(cell_type=CellType.ROOM),                    # not a field
    })
    cs = step(cs, PlaceWorker(space="lessons"))
    assert _veg_at(cs, cp, 0, 0) == 0
    assert cs.players[cp].farmyard.grid[0][1].cell_type == CellType.ROOM


def test_does_not_fire_for_unowned_card():
    # Player does NOT own heresy_teacher → the auto is owner-gated off.
    cs, cp = _card_state(occupations=frozenset())
    cs = _set_grid(cs, cp, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3, veg=0)})
    cs = step(cs, PlaceWorker(space="lessons"))
    assert _veg_at(cs, cp, 0, 0) == 0


def test_does_not_fire_on_unrelated_space():
    # Owns heresy_teacher; uses Forest (not Lessons) → no field change.
    cs, cp = _card_state()
    cs = _set_grid(cs, cp, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3, veg=0)})
    cs = step(cs, PlaceWorker(space="forest"))
    assert _veg_at(cs, cp, 0, 0) == 0


# ---------------------------------------------------------------------------
# "Each time you use" — fires again on a SECOND Lessons use
# ---------------------------------------------------------------------------

def test_fires_each_time_lessons_is_used():
    cs, cp = _card_state()
    cs = _set_grid(cs, cp, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3, veg=0)})

    # First Lessons use: the field gains 1 veg.
    cs = _use_lessons(cs)
    assert _veg_at(cs, cp, 0, 0) == 1
    assert _grain_at(cs, cp, 0, 0) == 3

    # A full Lessons use places cp's worker on Lessons and advances the turn.
    # Reset the space to unoccupied and hand the turn back to cp, re-arm the
    # field to a fresh qualifying state, then use Lessons AGAIN — it must fire a
    # second time (no once-per-game latch).
    open_lessons = fast_replace(get_space(cs.board, "lessons"), workers=(0, 0))
    cs = fast_replace(cs, board=with_space(cs.board, "lessons", open_lessons),
                      current_player=cp)
    cs = _set_grid(cs, cp, {(0, 0): Cell(cell_type=CellType.FIELD, grain=4, veg=0)})
    cs = step(cs, PlaceWorker(space="lessons"))
    assert _veg_at(cs, cp, 0, 0) == 1
    assert _grain_at(cs, cp, 0, 0) == 4


# ---------------------------------------------------------------------------
# Card-fields (ruling 45, 2026-07-12): a card-field with 3+ grain and no
# vegetable is "a field with at least 3 grain and no vegetable" too.
# ---------------------------------------------------------------------------

def _own_card_field(cs, cp, cid):
    p = fast_replace(cs.players[cp],
                     minor_improvements=cs.players[cp].minor_improvements | {cid})
    return fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))


def _set_stacks(cs, cp, cid, stacks):
    p = cs.players[cp]
    p = fast_replace(p, card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(cs, players=tuple(
        p if i == cp else cs.players[i] for i in range(2)))


def test_card_field_with_three_grain_gains_below_the_grain_veg():
    cs, cp = _card_state()
    cs = _own_card_field(cs, cp, "crop_rotation_field")
    cs = _set_stacks(cs, cp, "crop_rotation_field", [(3, 0, 0, 0)])
    cs = step(cs, PlaceWorker(space="lessons"))   # before_action_space fires
    # The veg joins the grain-bearing stack; the grain count is untouched.
    assert card_field_stacks(cs.players[cp], "crop_rotation_field") == (
        (3, 1, 0, 0),)


def test_card_field_with_too_little_grain_does_not_qualify():
    cs, cp = _card_state()
    cs = _own_card_field(cs, cp, "crop_rotation_field")
    cs = _set_stacks(cs, cp, "crop_rotation_field", [(2, 0, 0, 0)])
    cs = step(cs, PlaceWorker(space="lessons"))
    assert card_field_stacks(cs.players[cp], "crop_rotation_field") == (
        (2, 0, 0, 0),)


def test_card_field_already_holding_veg_does_not_qualify():
    # The clarification case on a card: a mixed grain+veg card-field is
    # excluded by the veg == 0 test (never bumped to 2).
    cs, cp = _card_state()
    cs = _own_card_field(cs, cp, "crop_rotation_field")
    cs = _set_stacks(cs, cp, "crop_rotation_field", [(3, 1, 0, 0)])
    cs = step(cs, PlaceWorker(space="lessons"))
    assert card_field_stacks(cs.players[cp], "crop_rotation_field") == (
        (3, 1, 0, 0),)


def test_mixed_card_field_then_harvests_grain_first():
    # The (3, 1, 0, 0) stack the effect creates behaves like a grid cell at
    # the field-phase take: 1 grain is harvested (grain before veg — the
    # take-precedence elif), the below-the-grain veg stays put.
    cs, cp = _card_state()
    cs = _own_card_field(cs, cp, "crop_rotation_field")
    cs = _set_stacks(cs, cp, "crop_rotation_field", [(3, 0, 0, 0)])
    cs = _use_lessons(cs)   # full use, so no frame is left on the stack
    assert card_field_stacks(cs.players[cp], "crop_rotation_field") == (
        (3, 1, 0, 0),)
    g0 = cs.players[cp].resources.grain
    nxt, occasion = field_take(cs, cp)
    e = [e for e in occasion.entries
         if e.source == "card:crop_rotation_field"][0]
    assert (e.crop, e.amount, e.emptied) == ("grain", 1, False)
    assert nxt.players[cp].resources.grain - g0 == 1
    assert card_field_stacks(nxt.players[cp], "crop_rotation_field") == (
        (2, 1, 0, 0),)
