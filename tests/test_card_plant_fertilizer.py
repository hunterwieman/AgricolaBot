"""Tests for Plant Fertilizer (minor C8, Corbarius Expansion; traveling).

Card text: "In each field with exactly 1 good, you can immediately place 1
additional good of the same type." Cost: none. Prerequisite: none. VPs: 0.
TRAVELING (passing) card.

Effect = automatic on-play one-shot. THE THRESHOLD is "exactly 1 good": a FIELD
holding grain == 1 (xor) veg == 1 → that crop goes to 2; everything else (empty,
>1 token, freshly sown 3-grain / 2-veg, two-crop) is skipped. It is passing
(passing_left=True), so after the effect it circulates to the opponent.
"""
import agricola.cards.plant_fertilizer  # noqa: F401  (registers the card)

from agricola.cards.specs import MINORS
from agricola.constants import CellType
from agricola.engine import step
from agricola.pending import PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import with_pending_stack
from tests.test_utils import sole_play_minor

CARD_ID = "plant_fertilizer"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


def _card_state(seed=5):
    s, _env = setup_env(seed, card_pool=_POOL)
    return s


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
    assert spec.cost == Cost()              # no cost
    assert spec.vps == 0                    # no printed VPs
    assert spec.prereq is None              # no prerequisite
    assert spec.passing_left is True        # traveling card
    assert spec.on_play is not None


# ---------------------------------------------------------------------------
# Effect: the "exactly 1 good" threshold (direct on_play)
# ---------------------------------------------------------------------------

def test_single_token_fields_each_get_one_more():
    """A 1-grain field → 2 grain; a 1-veg field → 2 veg."""
    s = _card_state()
    s = _with_grid(s, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=1),
        (0, 1): Cell(cell_type=CellType.FIELD, veg=1),
    })
    out = MINORS[CARD_ID].on_play(s, 0)
    assert sorted(_field_crops(out.players[0])) == sorted([(2, 0), (0, 2)])


def test_skips_fields_with_more_than_one_token():
    """Freshly-sown fields (3 grain / 2 veg) hold >1 good → NOT eligible."""
    s = _card_state()
    s = _with_grid(s, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=3),  # sown grain → skip
        (0, 1): Cell(cell_type=CellType.FIELD, veg=2),    # sown veg → skip
        (0, 2): Cell(cell_type=CellType.FIELD, grain=2),  # 2 grain → skip
    })
    out = MINORS[CARD_ID].on_play(s, 0)
    # Nothing changed: identity returned (no-op grant).
    assert out is s
    assert sorted(_field_crops(out.players[0])) == sorted([(3, 0), (0, 2), (2, 0)])


def test_skips_empty_and_two_crop_fields():
    s = _card_state()
    s = _with_grid(s, 0, {
        (0, 0): Cell(cell_type=CellType.FIELD, grain=1),          # single → +1
        (0, 1): Cell(cell_type=CellType.FIELD),                   # empty → skip
        (0, 2): Cell(cell_type=CellType.FIELD, grain=1, veg=1),   # two crops → skip
    })
    out = MINORS[CARD_ID].on_play(s, 0)
    assert sorted(_field_crops(out.players[0])) == sorted([(2, 0), (0, 0), (1, 1)])


def test_no_fields_is_a_noop_grant():
    """Playing it with zero planted fields is a harmless identity no-op."""
    s = _card_state()
    out = MINORS[CARD_ID].on_play(s, 0)
    assert out is s
    assert _field_crops(out.players[0]) == []


def test_only_fields_are_touched():
    """A non-FIELD cell that happens to be empty is never given crops, and the
    crop edit does not bleed into player.resources."""
    s = _card_state()
    s = _with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    res_before = s.players[0].resources
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _field_crops(out.players[0]) == [(2, 0)]
    # No FIELD-cell crop leaked into player resources (grain/veg unchanged there).
    assert out.players[0].resources.grain == res_before.grain
    assert out.players[0].resources.veg == res_before.veg


# ---------------------------------------------------------------------------
# Scoping: only the playing player's fields
# ---------------------------------------------------------------------------

def test_only_acting_player_fields_change():
    s = _card_state()
    s = _with_grid(s, 0, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    s = _with_grid(s, 1, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    out = MINORS[CARD_ID].on_play(s, 0)
    assert _field_crops(out.players[0]) == [(2, 0)]   # player 0 fertilized
    assert _field_crops(out.players[1]) == [(1, 0)]   # opponent untouched


# ---------------------------------------------------------------------------
# Real play flow: through CommitPlayMinor, and the passing circulation
# ---------------------------------------------------------------------------

def test_real_play_flow_applies_effect_and_passes_to_opponent():
    """Play the card via the minor-play machinery: the effect fires, and being a
    traveling card it leaves the player's tableau and lands in the opponent's hand.
    """
    s = _card_state()
    cp = s.current_player
    # Give the active player the card in hand and a single-token grain field.
    p = fast_replace(s.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(s.players[1 - cp], hand_minors=frozenset())
    s = fast_replace(s, players=tuple(p if i == cp else opp for i in range(2)))
    s = _with_grid(s, cp, {(0, 0): Cell(cell_type=CellType.FIELD, grain=1)})
    # Drive PendingPlayMinor directly (the established factory pattern for the
    # minor-play machinery — test_cards_minors.py).
    s = with_pending_stack(
        s,
        (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),),
    )

    out = step(s, sole_play_minor(s, CARD_ID))

    # Effect applied to the active player's field.
    assert (2, 0) in _field_crops(out.players[cp])
    # Passing card: it is NOT kept in the player's tableau...
    assert CARD_ID not in out.players[cp].minor_improvements
    # ...and circulates to the opponent's hand.
    assert CARD_ID in out.players[1 - cp].hand_minors
