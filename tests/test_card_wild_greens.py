"""Tests for Wild Greens (minor E50; Ephipparius Expansion): "Each time you sow,
you get 1 food for every different type of good that you sow." No cost, VPs 0.

Modeled as a before/after pair of mandatory, choice-free automatic effects on the
Sow sub-action host (register_auto on before_sow + after_sow), using a CardStore
snapshot of the per-good field TOTALS (grain, veg, wood, stone summed over grid
FIELD tiles + every card-field stack) to detect which good-TYPES this sow planted.
+1 food per good whose total grew; two fields of the same good is still one type.

User ruling (2026-07-15): "type of GOOD" is broader than "crop" -- sowing wood
(Wood Field) or stone (Rock Garden) onto a card-field DOES count as sowing a type
of good, alongside grain/veg on grid tiles or card-fields. So the count spans ALL
fields and ALL four sowable goods. Per-good TOTALS (not field counts) are used so
the multi-stack card-fields (Wood Field 2 stacks, Rock Garden 3 stacks) have no
detection blind spot: a sown good always raises its own total.

Covers: registration; the grant via a real Grain Utilization AND Cultivation sow;
grain-only (+1), veg-only (+1), two-grain (still +1), grain+veg-in-one (+2); a
Beanfield veg card-field sow (+1) and a Wood Field wood card-field sow (+1); the
multi-stack no-blind-spot case; the _field_good_totals helper incl. stone;
not-owned; snapshot reset; and re-firing on a fresh independent sow ("each time").
"""
from __future__ import annotations

import agricola.cards.wild_greens  # noqa: F401  (registers the card; not in __init__ yet)

from agricola.actions import ChooseSubAction, CommitSow, PlaceWorker
from agricola.cards.card_fields import card_holds, stacks_to_store
from agricola.cards.specs import MINORS
from agricola.cards.triggers import AUTO_EFFECTS
from agricola.cards.wild_greens import _field_good_totals
from agricola.constants import CellType
from agricola.engine import step
from agricola.legality import legal_actions
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import CardPool, setup_env
from agricola.state import Cell, get_space, with_space
from tests.factories import with_resources

CARD_ID = "wild_greens"

_POOL = CardPool(
    occupations=tuple(f"o{i}" for i in range(20)),
    minors=(CARD_ID,) + tuple(f"m{i}" for i in range(20)),
)


# --- Helpers ----------------------------------------------------------------

def _card_state(seed=5):
    cs, _env = setup_env(seed, card_pool=_POOL)
    return fast_replace(cs, current_player=0), 0


def _own_minor(state, idx, card_id):
    p = state.players[idx]
    return fast_replace(state, players=tuple(
        fast_replace(p, minor_improvements=p.minor_improvements | {card_id}) if i == idx
        else state.players[i] for i in range(2)))


def _reveal(state, space_id):
    sp = fast_replace(get_space(state.board, space_id), revealed=True, workers=(0, 0))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _with_empty_fields(state, idx, cells):
    """Place empty FIELD tiles at the given (row, col) cells, ready to sow into."""
    p = state.players[idx]
    grid = [[c for c in row] for row in p.farmyard.grid]
    for (r, c) in cells:
        grid[r][c] = Cell(cell_type=CellType.FIELD)
    fy = fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid))
    return fast_replace(state, players=tuple(
        fast_replace(p, farmyard=fy) if i == idx else state.players[i] for i in range(2)))


def _own_card_field(s, idx, cid):
    """Give player `idx` an (empty) card-field `cid` in play."""
    p = s.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {cid})
    return fast_replace(
        s, players=tuple(p if i == idx else s.players[i] for i in range(2)))


def _own_card_field_with(s, idx, cid, stacks):
    """Own card-field `cid` with the given per-stack (g, v, w, s) contents."""
    p = s.players[idx]
    p = fast_replace(p, minor_improvements=p.minor_improvements | {cid},
                     card_state=stacks_to_store(p.card_state, cid, stacks))
    return fast_replace(
        s, players=tuple(p if i == idx else s.players[i] for i in range(2)))


def _to_before_sow(s, cp, space="grain_utilization"):
    """Place at `space`, choose sow -> PendingSow in its before-phase."""
    s = _reveal(s, space)
    s = step(s, PlaceWorker(space=space))
    s = step(s, ChooseSubAction(name="sow"))
    return s


def _sow(s, **kw):
    """The unique legal CommitSow matching the given fields (grain/veg/card_sows)."""
    want = {"grain": 0, "veg": 0, "card_sows": (), **kw}
    return next(a for a in legal_actions(s) if isinstance(a, CommitSow)
                and a.grain == want["grain"] and a.veg == want["veg"]
                and a.card_sows == want["card_sows"])


# --- Registration -----------------------------------------------------------

def test_registration():
    assert CARD_ID in MINORS
    spec = MINORS[CARD_ID]
    assert spec.cost == Cost()          # no cost
    assert spec.vps == 0
    assert not spec.passing_left
    bsow = {e.card_id for e in AUTO_EFFECTS.get("before_sow", [])}
    asow = {e.card_id for e in AUTO_EFFECTS.get("after_sow", [])}
    assert CARD_ID in bsow
    assert CARD_ID in asow


# --- One distinct type -> 1 food (grid) -------------------------------------

def test_grain_only_sow_one_food():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, grain=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = step(s, _sow(s, grain=1))
    assert s.players[cp].resources.food == 1        # grain is one type
    assert s.players[cp].farmyard.grid[1][0].grain > 0
    assert s.players[cp].card_state.get(CARD_ID) is None   # snapshot reset


def test_veg_only_sow_one_food():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, veg=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = step(s, _sow(s, veg=1))
    assert s.players[cp].resources.food == 1        # veg is one type


def test_two_grain_fields_still_one_type():
    """Two grain fields sown in one action is still ONE type -> 1 food."""
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, grain=2, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = step(s, _sow(s, grain=2))
    assert s.players[cp].resources.food == 1


# --- Both types in one sow -> 2 food ----------------------------------------

def test_grain_and_veg_in_one_sow_two_food():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, grain=1, veg=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = step(s, _sow(s, grain=1, veg=1))            # grain in one field, veg in the other
    assert s.players[cp].resources.food == 2        # two distinct types


def test_fires_via_cultivation():
    """The grant is on the Sow primitive, so Cultivation drives it too."""
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, veg=1, food=0)
    s = _to_before_sow(s, cp, "cultivation")
    s = step(s, _sow(s, veg=1))
    assert s.players[cp].resources.food == 1


# --- Card-field sows count (user ruling 2026-07-15: "good", not "crop") ------

def test_beanfield_veg_card_field_sow_one_food():
    """A veg sow onto a Beanfield ALONE (no grid field) grants +1: veg is a type
    of good, and card-field sows count."""
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _own_card_field(s, cp, "beanfield")
    s = with_resources(s, cp, veg=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = step(s, _sow(s, card_sows=(("beanfield", "veg"),)))
    assert card_holds(s.players[cp], "beanfield", "veg") == 2   # a real card sow ran
    assert s.players[cp].resources.food == 1                    # veg counts


def test_wood_field_wood_card_field_sow_one_food():
    """Sowing WOOD onto a Wood Field grants +1: wood is a "type of good" you sow
    (the whole point of the good-not-crop ruling)."""
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _own_card_field(s, cp, "wood_field")
    s = with_resources(s, cp, wood=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = step(s, _sow(s, card_sows=(("wood_field", "wood"),)))
    assert card_holds(s.players[cp], "wood_field", "wood") == 3  # a real wood sow ran
    assert s.players[cp].resources.food == 1                     # wood counts


def test_totals_have_no_blind_spot_on_multistack_card_field():
    """Wood Field stack 0 already holds wood; sowing wood into the empty stack 1
    STILL grants +1 (wood total rose 3 -> 6). A per-card field COUNT would miss
    this (the card already 'holds wood'); the per-good TOTAL does not -- this is
    the concrete reason the ruling specifies totals."""
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _own_card_field_with(s, cp, "wood_field", [(0, 0, 3, 0), (0, 0, 0, 0)])
    s = with_resources(s, cp, wood=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = step(s, _sow(s, card_sows=(("wood_field", "wood"),)))
    assert card_holds(s.players[cp], "wood_field", "wood") == 6
    assert s.players[cp].resources.food == 1


def test_field_good_totals_helper_sums_grid_and_all_card_goods():
    """`_field_good_totals` sums grid grain/veg + every card-field stack's
    (grain, veg, wood, stone) -- incl. stone (Rock Garden) -- and its 4-component
    delta is what after_sow grants on. Direct check per the ruling's helper."""
    s, cp = _card_state()
    # grid: one grain field (grain=3).
    p = s.players[cp]
    grid = [[c for c in row] for row in p.farmyard.grid]
    grid[1][0] = Cell(cell_type=CellType.FIELD, grain=3)
    p = fast_replace(p, farmyard=fast_replace(p.farmyard, grid=tuple(tuple(r) for r in grid)))
    s = fast_replace(s, players=tuple(p if i == cp else s.players[i] for i in range(2)))
    # card-fields: a Rock Garden holding 2 stone in one stack; an empty Beanfield.
    s = _own_card_field_with(s, cp, "rock_garden", [(0, 0, 0, 2), (0, 0, 0, 0), (0, 0, 0, 0)])
    s = _own_card_field(s, cp, "beanfield")
    before = _field_good_totals(s, cp)
    assert before == (3, 0, 0, 2)          # 3 grain (grid), 2 stone (card)
    # Add stone to a second Rock Garden stack -> only the stone component grows.
    s2 = _own_card_field_with(s, cp, "rock_garden",
                              [(0, 0, 0, 2), (0, 0, 0, 2), (0, 0, 0, 0)])
    after = _field_good_totals(s2, cp)
    assert after == (3, 0, 0, 4)
    assert sum(1 for b, n in zip(before, after) if n > b) == 1   # one type (stone) grew


# --- Not owned ---------------------------------------------------------------

def test_not_owned_grants_nothing():
    s, cp = _card_state()
    s = _with_empty_fields(s, cp, [(1, 0)])
    s = with_resources(s, cp, grain=1, food=0)
    s = _to_before_sow(s, cp, "grain_utilization")
    s = step(s, _sow(s, grain=1))
    assert s.players[cp].resources.food == 0


# --- "Each time": a fresh independent sow fires again ------------------------

def test_fires_on_second_independent_sow():
    s, cp = _card_state()
    s = _own_minor(s, cp, CARD_ID)
    s = _with_empty_fields(s, cp, [(1, 0), (1, 1)])
    s = with_resources(s, cp, grain=1, veg=1, food=0)
    # First sow: grain only -> +1.
    s = _to_before_sow(s, cp, "grain_utilization")
    s = step(s, _sow(s, grain=1))
    assert s.players[cp].resources.food == 1
    # A brand-new, independent PendingSow (veg this time) -> another +1 = 2 total.
    s = fast_replace(s, current_player=cp, pending_stack=())
    s = _to_before_sow(s, cp, "cultivation")
    s = step(s, _sow(s, veg=1))
    assert s.players[cp].resources.food == 2
