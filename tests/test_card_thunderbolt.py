import agricola.cards.thunderbolt  # noqa: F401  (registers the card)

"""Tests for Thunderbolt (minor improvement, E4; Ephipparius Expansion).

Card text: "Immediately remove all grain from one of your fields to the general
supply. Gain 2 wood for each grain you just removed."
Cost: none. Prereq: 1 Grain Field. Passing (traveling).

User rulings (2026-07-17): mandatory removal with a which-field CHOICE surfaced
as play-VARIANTS (no skip); board fields enumerated by DISTINCT grain count
(same-count fields interchangeable, representative = lowest (row, col)); each
grain-bearing card-field is its OWN "card:<id>" variant routed through the
`remove_card_crop` chokepoint (ruling 44); ruling 45 — a grain-holding
card-field counts for the prereq too.
"""
import json
from pathlib import Path

import agricola.cards.crop_rotation_field  # noqa: F401  (a grain card-field w/ removal reactor)

from agricola.actions import CommitPlayMinor
from agricola.cards.card_fields import card_holds, stacks_to_store
from agricola.cards.specs import MINORS, PLAY_MINOR_VARIANTS, prereq_met
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions, playable_minors
from agricola.pending import PendingCardChoice, PendingPlayMinor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell
from tests.factories import with_grid, with_pending_stack, with_resources

CARD_ID = "thunderbolt"
CRF = "crop_rotation_field"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID, CRF) + tuple(f"m{i}" for i in range(20)),
)

_DATA = Path(__file__).resolve().parent.parent / "agricola" / "cards" / "data"
with open(_DATA / "revised_minor_improvements.json") as f:
    _ROW = next(r for r in json.load(f) if r["name"] == "Thunderbolt")


def _base():
    """A state parked at a bare PendingPlayMinor frame with Thunderbolt (only)
    in the current player's hand and the opponent's hand emptied."""
    state, _env = setup_env(5, card_pool=_POOL)
    cp = state.current_player
    p = fast_replace(state.players[cp], hand_minors=frozenset({CARD_ID}))
    opp = fast_replace(state.players[1 - cp], hand_minors=frozenset())
    state = fast_replace(state, players=tuple(p if i == cp else opp for i in range(2)))
    state = with_resources(state, cp, wood=0, grain=0, veg=0)
    state = with_pending_stack(
        state,
        (PendingPlayMinor(player_idx=cp, initiated_by_id="space:meeting_place_cards"),))
    return state, cp


def _grain_board(state, cp, cells: dict):
    """cells: {(r, c): grain_count} — plow each as a FIELD holding that grain."""
    return with_grid(state, cp, {
        (r, c): Cell(cell_type=CellType.FIELD, grain=g) for (r, c), g in cells.items()})


def _own_card_field(state, cp, card_id, grain):
    """Own `card_id` (a card-field) and seed its single stack with `grain`."""
    p = state.players[cp]
    p = fast_replace(
        p,
        minor_improvements=p.minor_improvements | {card_id},
        card_state=stacks_to_store(p.card_state, card_id, [(grain, 0, 0, 0)]),
    )
    return fast_replace(state, players=tuple(p if i == cp else state.players[i]
                                             for i in range(2)))


def _plays(state):
    return [a for a in legal_actions(state)
            if isinstance(a, CommitPlayMinor) and a.card_id == CARD_ID]


# ---------------------------------------------------------------------------
# Registration & static facts
# ---------------------------------------------------------------------------

def test_json_row():
    assert _ROW["prerequisites"] == "1 Grain Field"
    assert _ROW["passing_left"] == "X"       # "X" is the JSON passing marker (cf. Market Stall)
    assert _ROW["cost"] is None              # free
    assert _ROW["text"] == (
        "Immediately remove all grain from one of your fields to the general "
        "supply. Gain 2 wood for each grain you just removed.")
    import agricola.cards.thunderbolt as mod
    assert _ROW["text"] in " ".join(mod.__doc__.split())


def test_registered():
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()               # free
    assert spec.passing_left is True         # traveling
    assert spec.vps == 0
    assert CARD_ID in PLAY_MINOR_VARIANTS


# ---------------------------------------------------------------------------
# Prereq boundary
# ---------------------------------------------------------------------------

def test_prereq_no_grain_field_unplayable():
    spec = MINORS[CARD_ID]
    state, cp = _base()                       # empty farm, no grain anywhere
    assert not prereq_met(spec, state, cp)
    assert CARD_ID not in playable_minors(state, cp)
    assert _plays(state) == []


def test_prereq_empty_field_does_not_count():
    """A plowed but UNSOWN field (grain 0) is not a grain field."""
    spec = MINORS[CARD_ID]
    state, cp = _base()
    state = with_grid(state, cp, {(0, 0): Cell(cell_type=CellType.FIELD)})
    assert not prereq_met(spec, state, cp)


def test_prereq_board_grain_field_playable():
    spec = MINORS[CARD_ID]
    state, cp = _base()
    state = _grain_board(state, cp, {(0, 0): 3})
    assert prereq_met(spec, state, cp)
    assert CARD_ID in playable_minors(state, cp)


def test_prereq_grain_card_field_counts():
    """Ruling 45: a grain-holding card-field satisfies '1 Grain Field'."""
    spec = MINORS[CARD_ID]
    state, cp = _base()                       # no board grain
    state = _own_card_field(state, cp, CRF, grain=3)
    assert prereq_met(spec, state, cp)
    assert CARD_ID in playable_minors(state, cp)


# ---------------------------------------------------------------------------
# Variant enumeration — board fields by DISTINCT grain count
# ---------------------------------------------------------------------------

def test_two_board_fields_different_counts_two_variants():
    state, cp = _base()
    state = _grain_board(state, cp, {(0, 0): 1, (0, 1): 3})
    assert {a.variant for a in _plays(state)} == {"board:1", "board:3"}


def test_two_board_fields_equal_counts_one_variant():
    state, cp = _base()
    state = _grain_board(state, cp, {(0, 0): 2, (2, 4): 2})
    assert {a.variant for a in _plays(state)} == {"board:2"}


def test_mandatory_no_skip_variant():
    """Every offered variant removes grain from a field — there is no
    skip/decline variant, so playing the card forces the removal."""
    state, cp = _base()
    state = _grain_board(state, cp, {(0, 0): 3})
    variants = {a.variant for a in _plays(state)}
    assert variants == {"board:3"}
    assert not any(v in ("", "skip", "decline", "none") for v in variants)


# ---------------------------------------------------------------------------
# Firing — board path
# ---------------------------------------------------------------------------

def test_board_removes_all_grain_and_pays_wood():
    state, cp = _base()
    state = _grain_board(state, cp, {(0, 0): 3})
    (play,) = [a for a in _plays(state) if a.variant == "board:3"]
    out = step(state, play)
    p = out.players[cp]
    assert p.farmyard.grid[0][0].grain == 0        # field emptied
    assert p.farmyard.grid[0][0].cell_type == CellType.FIELD   # still a field
    assert p.resources.wood == 6                   # 2 * 3 grain


def test_equal_count_variant_empties_exactly_one_field():
    """Firing "board:2" strikes the representative (lowest (r, c)) field only;
    the equal-count sibling is untouched."""
    state, cp = _base()
    state = _grain_board(state, cp, {(0, 0): 2, (2, 4): 2})
    (play,) = [a for a in _plays(state) if a.variant == "board:2"]
    out = step(state, play)
    p = out.players[cp]
    assert p.farmyard.grid[0][0].grain == 0        # representative struck
    assert p.farmyard.grid[2][4].grain == 2        # sibling untouched
    assert p.resources.wood == 4                   # 2 * 2 grain


def test_pastures_cache_preserved_on_board_strike():
    """The crop edit changes no fence, so the cached pasture decomposition rides
    along unchanged."""
    state, cp = _base()
    state = _grain_board(state, cp, {(1, 1): 3})
    before = state.players[cp].farmyard.pastures
    (play,) = [a for a in _plays(state) if a.variant == "board:3"]
    out = step(state, play)
    assert out.players[cp].farmyard.pastures == before


# ---------------------------------------------------------------------------
# Firing — card-field path (through the remove_card_crop chokepoint)
# ---------------------------------------------------------------------------

def test_card_field_variant_distinct_from_equal_count_board():
    """A grain card-field is its OWN variant, never collapsed with a board field
    of the same count."""
    state, cp = _base()
    state = _grain_board(state, cp, {(0, 0): 2})
    state = _own_card_field(state, cp, CRF, grain=2)
    assert {a.variant for a in _plays(state)} == {"board:2", f"card:{CRF}"}


def test_card_field_removes_all_grain_and_pays_wood():
    """Firing the card variant empties the card-field's grain (no veg in
    supply -> the chokepoint's reactor makes no offer) and pays 2 wood/grain."""
    state, cp = _base()
    state = _own_card_field(state, cp, CRF, grain=2)   # veg supply is 0
    (play,) = [a for a in _plays(state) if a.variant == f"card:{CRF}"]
    out = step(state, play)
    p = out.players[cp]
    assert card_holds(p, CRF, "grain") == 0            # card grain removed
    assert p.resources.wood == 4                       # 2 * 2 grain


def test_card_field_removal_routes_through_chokepoint():
    """Emptying the card-field's last grain via the `remove_card_crop`
    chokepoint fires its registered removal reactor — Crop Rotation Field's
    sow-or-decline offer (ruling 44). With 1 veg in supply + an empty stack, the
    reactor pushes a PendingCardChoice, proving the chokepoint (not a raw edit)
    was used."""
    state, cp = _base()
    state = _own_card_field(state, cp, CRF, grain=3)
    state = with_resources(state, cp, veg=1)           # opposite crop for the re-sow
    (play,) = [a for a in _plays(state) if a.variant == f"card:{CRF}"]
    out = step(state, play)
    p = out.players[cp]
    assert card_holds(p, CRF, "grain") == 0            # grain removed
    assert p.resources.wood == 6                       # 2 * 3 grain (paid before the frame)
    top = out.pending_stack[-1]
    assert isinstance(top, PendingCardChoice)
    assert top.initiated_by_id == f"card:{CRF}"
    assert set(top.options) == {"sow_veg", "decline"}


# ---------------------------------------------------------------------------
# Passing (traveling) — the card leaves to the opponent's hand
# ---------------------------------------------------------------------------

def test_card_passes_to_opponent():
    state, cp = _base()
    state = _grain_board(state, cp, {(0, 0): 3})
    (play,) = [a for a in _plays(state) if a.variant == "board:3"]
    out = step(state, play)
    assert CARD_ID not in out.players[cp].minor_improvements   # not kept
    assert CARD_ID not in out.players[cp].hand_minors          # left our hand
    assert CARD_ID in out.players[1 - cp].hand_minors          # passed to opponent
