"""Tests for Calcium Fertilizers (minor A72, Artifex Expansion).

Card text: "Each time you use a 'Quarry' accumulation space, add 1 additional good
of the respective type to each of your planted fields growing a single type of
crop." Cost: none. Prerequisite: No Field Tiles. VPs: 0.

Effect = automatic before_action_space hook on the two atomic quarry spaces. The
hook is driven via a REAL placement on a quarry (the hosted-space lifecycle:
PlaceWorker -> Proceed -> Stop), exactly like the Stone Tongs precedent in
test_cards_action_space_hook.py.
"""
import agricola.cards.calcium_fertilizers  # noqa: F401  (registers the card)

import pytest

from agricola.actions import PlaceWorker, Proceed, Stop
from agricola.cards.specs import MINORS, prereq_met
from agricola.cards.triggers import AUTO_EFFECTS, OWN_ACTION_HOOK_CARDS
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.pending import PendingActionSpace
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space

CARD_ID = "calcium_fertilizers"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


def _own_minor(state, idx, card_id):
    p = fast_replace(
        state.players[idx],
        minor_improvements=state.players[idx].minor_improvements | {card_id},
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _with_grid(state, idx, overrides):
    """Replace specific (r, c) cells in player idx's farmyard grid."""
    grid = state.players[idx].farmyard.grid
    new_grid = tuple(
        tuple(overrides.get((r, c), grid[r][c]) for c in range(5)) for r in range(3)
    )
    fy = fast_replace(state.players[idx].farmyard, grid=new_grid)
    p = fast_replace(state.players[idx], farmyard=fy)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _ready_quarry(state, space_id, owner=0):
    """Reveal + stock `space_id` and make it `owner`'s turn (quarries are Stage 2/4)."""
    state = fast_replace(state, current_player=owner)
    sp = get_space(state.board, space_id)
    return fast_replace(
        state,
        board=with_space(
            state.board, space_id,
            fast_replace(sp, revealed=True, accumulated=Resources(stone=2)),
        ),
    )


def _play_quarry(state, space_id):
    """Drive the hosted automatic-only lifecycle: place -> Proceed -> Stop."""
    state = step(state, PlaceWorker(space=space_id))
    assert isinstance(state.pending_stack[-1], PendingActionSpace)
    assert state.pending_stack[-1].phase == "before"
    assert legal_actions(state) == [Proceed()]
    state = step(state, Proceed())
    assert legal_actions(state) == [Stop()]
    state = step(state, Stop())
    assert not state.pending_stack
    return state


def _field_crops(player):
    """List of (grain, veg) for every FIELD cell, in grid order."""
    return [
        (cell.grain, cell.veg)
        for row in player.farmyard.grid
        for cell in row
        if cell.cell_type is CellType.FIELD
    ]


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.vps == 0
    assert not spec.passing_left
    assert spec.prereq is not None
    auto_ids = {e.card_id for e in AUTO_EFFECTS.get("before_action_space", ())}
    assert CARD_ID in auto_ids
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["western_quarry"]
    assert CARD_ID in OWN_ACTION_HOOK_CARDS["eastern_quarry"]


# ---------------------------------------------------------------------------
# Prerequisite: No Field Tiles
# ---------------------------------------------------------------------------

def test_prereq_true_with_no_fields():
    s = _card_state()
    assert prereq_met(MINORS[CARD_ID], s, 0)


def test_prereq_false_with_a_field_tile():
    s = _card_state()
    s = _with_grid(s, 0, {(0, 2): Cell(cell_type=CellType.FIELD)})  # one empty field
    assert not prereq_met(MINORS[CARD_ID], s, 0)
    # Opponent still has no fields → their prereq holds (player-scoped check).
    assert prereq_met(MINORS[CARD_ID], s, 1)


# ---------------------------------------------------------------------------
# Effect via a real quarry placement
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("space_id", ["western_quarry", "eastern_quarry"])
def test_adds_to_single_crop_fields_on_each_quarry(space_id):
    s = _own_minor(_card_state(), 0, CARD_ID)
    # A grain-only field (3 grain) and a veg-only field (2 veg).
    s = _with_grid(s, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),
    })
    s = _ready_quarry(s, space_id, owner=0)
    before_stone = s.players[0].resources.stone

    out = _play_quarry(s, space_id)

    # +1 to the respective crop on each single-type field.
    assert sorted(_field_crops(out.players[0])) == sorted([(4, 0), (0, 3)])
    # Quarry's own stone is unaffected (2 accumulated, no card stone bonus).
    assert out.players[0].resources.stone == before_stone + 2


def test_skips_unplanted_and_two_crop_fields():
    s = _own_minor(_card_state(), 0, CARD_ID)
    s = _with_grid(s, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),          # single → +1
        (0, 1): Cell(cell_type=CellType.FIELD),                   # unplanted → skip
        (0, 2): Cell(cell_type=CellType.FIELD, grain=2, veg=1),   # two crops → skip
    })
    s = _ready_quarry(s, "western_quarry", owner=0)

    out = _play_quarry(s, "western_quarry")

    assert sorted(_field_crops(out.players[0])) == sorted([(4, 0), (0, 0), (2, 1)])


# ---------------------------------------------------------------------------
# Eligibility boundaries
# ---------------------------------------------------------------------------

def test_does_not_fire_on_non_quarry_space():
    """Forest is a non-quarry atomic space — the card must not fire there even
    when hosted (it is hosted only if the player owns a forest-hooking card; here
    Calcium Fertilizers does not register Forest, so Forest is not hosted at all
    and the placement is byte-identical to Family)."""
    s = _own_minor(_card_state(), 0, CARD_ID)
    s = _with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3)})
    s = fast_replace(s, current_player=0)
    sp = get_space(s.board, "forest")
    s = fast_replace(s, board=with_space(
        s.board, "forest", fast_replace(sp, revealed=True, accumulated=Resources(wood=3))))

    s = step(s, PlaceWorker(space="forest"))
    # Forest is not hosted (no Forest hook), so it resolved atomically — no frame.
    assert not s.pending_stack
    # The grain field is unchanged (no +1).
    assert _field_crops(s.players[0]) == [(3, 0)]


def test_no_fields_is_a_noop_grant():
    """Owning the card with zero planted fields: the quarry still resolves, the
    effect is a harmless no-op (no crash, no spurious goods)."""
    s = _own_minor(_card_state(), 0, CARD_ID)
    s = _ready_quarry(s, "western_quarry", owner=0)
    before_stone = s.players[0].resources.stone
    out = _play_quarry(s, "western_quarry")
    assert out.players[0].resources.stone == before_stone + 2
    assert _field_crops(out.players[0]) == []


def test_opponent_card_does_not_fire_for_actor():
    """Player 1 owns the card; player 0 uses the quarry. The card is own-action
    only (any_player=False), so player 1's fields are NOT modified."""
    s = _own_minor(_card_state(), 1, CARD_ID)
    s = _with_grid(s, 1, {(0, 0): Cell(cell_type=CellType.FIELD, grain=3)})
    # Player 0 (no card) uses the quarry — it is not hosted on their behalf.
    s = _ready_quarry(s, "western_quarry", owner=0)
    s = step(s, PlaceWorker(space="western_quarry"))
    # Player 0 owns no quarry-hook card → atomic resolution, no host frame.
    assert not s.pending_stack
    # Player 1's grain field is untouched.
    assert _field_crops(s.players[1]) == [(3, 0)]
