"""Tests for Potato Digger (occupation, C161; Corbarius Expansion).

Card text: "When you play this card, if you have at least 2/4/5 unplanted field
tiles, you immediately get 1/2/3 vegetables."

An on-play step-function grant keyed to the number of UNPLANTED (empty) field tiles.
Tests drive the real Lessons -> play-occupation flow for the core case, and cover
the tier bands directly, plus that sown fields don't count as unplanted.
"""
import agricola.cards.potato_digger  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitPlayOccupation, PlaceWorker
from agricola.cards.potato_digger import CARD_ID
from agricola.cards.specs import OCCUPATIONS
from agricola.constants import CellType
from agricola.engine import step
from agricola.replace import fast_replace
from agricola.setup import CardPool, setup, setup_env
from agricola.state import Cell, GameState

from tests.factories import with_current_player, with_fields, with_grid, with_space

_POOL = CardPool(
    occupations=(CARD_ID,) + tuple(f"o{i}" for i in range(20)),
    minors=tuple(f"m{i}" for i in range(20)),
)


def _play_occupation(cs, idx, card_id):
    """Drive the real Lessons -> play-occupation flow for player `idx`."""
    cs = with_current_player(cs, idx)
    cs = with_space(cs, "lessons", revealed=True)
    cs = step(cs, PlaceWorker(space="lessons"))
    cs = step(cs, ChooseSubAction(name="play_occupation"))
    cs = step(cs, CommitPlayOccupation(card_id=card_id))
    return cs


def _give_hand_occ(state, idx, card_id):
    p = state.players[idx]
    p = fast_replace(p, hand_occupations=frozenset({card_id}))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in OCCUPATIONS


# --- On-play tier bands (direct) --------------------------------------------

def test_tier_bands_direct():
    on_play = OCCUPATIONS[CARD_ID].on_play
    cells_all = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]
    for n_fields, expected_veg in [(0, 0), (1, 0), (2, 1), (3, 1),
                                   (4, 2), (5, 3)]:
        s = with_fields(setup(0), 0, cells_all[:n_fields])
        v0 = s.players[0].resources.veg
        after = on_play(s, 0)
        assert after.players[0].resources.veg == v0 + expected_veg, n_fields


def test_sown_fields_do_not_count():
    """A field sown with grain or veg is not 'unplanted' -> excluded from the count."""
    on_play = OCCUPATIONS[CARD_ID].on_play
    # 2 empty fields (would give 1 veg) + 3 sown fields that must NOT count.
    s = with_fields(setup(0), 0, [(0, 0), (0, 1)])
    s = with_grid(s, 0, {
        (1, 0): Cell(cell_type=CellType.FIELD, grain=3),
        (1, 1): Cell(cell_type=CellType.FIELD, veg=2),
        (1, 2): Cell(cell_type=CellType.FIELD, grain=1),
    })
    v0 = s.players[0].resources.veg
    after = on_play(s, 0)
    assert after.players[0].resources.veg == v0 + 1   # only the 2 empty fields count


# --- Real engine flow -------------------------------------------------------

def test_on_play_via_engine_flow():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _give_hand_occ(cs, 0, CARD_ID)
    cs = with_fields(cs, 0, [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)])  # 5 -> 3 veg
    v0 = cs.players[0].resources.veg
    cs = _play_occupation(cs, 0, CARD_ID)
    assert cs.players[0].resources.veg == v0 + 3
    assert CARD_ID in cs.players[0].occupations


def test_no_fields_no_veg_via_engine_flow():
    cs, _env = setup_env(5, card_pool=_POOL)
    cs = _give_hand_occ(cs, 0, CARD_ID)   # no fields plowed
    v0 = cs.players[0].resources.veg
    cs = _play_occupation(cs, 0, CARD_ID)
    assert cs.players[0].resources.veg == v0
