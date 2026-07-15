"""Tests for Wood Slide Hammer (minor improvement, C13; Corbarius).

Card text: "On your first renovation, if you have at least 5 wood rooms, you can
renovate to stone directly and you get a discount of 2 stone on the renovation
cost." Cost 1 Wood; kept.

Two renovate modifiers on ONE gate (house still WOOD == first renovation, AND
>= 5 rooms):
  1. a renovate-TARGET extension WOOD->STONE (Conservator shape), and
  2. a -2 stone COST REDUCTION on that stone renovation (Bricklayer shape).

Coverage: registration; the target extension present exactly on the gate (>=5
wood rooms, owned, wood house) and absent otherwise (unit + through the real
`_legal_renovate_targets`); the -2 stone discount at the `effective_payments`
chokepoint, gated on the stone target and >=5 rooms and ownership; and a full
House Redevelopment renovate driven end-to-end to a STONE house at the discounted
cost.
"""
import agricola.cards.wood_slide_hammer  # noqa: F401  (registers the card)

from agricola.actions import ChooseSubAction, CommitRenovate, PlaceWorker
from agricola.cards.cost_mods import REDUCTIONS
from agricola.cards.specs import MINORS
from agricola.cards.wood_slide_hammer import _wood_to_stone
from agricola.constants import CellType, HouseMaterial
from agricola.cost import CostCtx
from agricola.engine import step
from agricola.legality import (
    RENOVATE_TARGET_EXTENSIONS,
    _legal_renovate_targets,
    effective_payments,
    legal_actions,
)
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.setup import setup
from agricola.state import Cell
import tests.factories as f

CARD_ID = "wood_slide_hammer"

_ALL_FIELDS = ("wood", "clay", "reed", "stone", "food", "grain", "veg")
# effective_payments returns only AFFORDABLE payments, so ctx-level tests hold plenty.
_GEN = Resources(stone=20, clay=20, reed=20)


def _state(*, rooms=5, material=HouseMaterial.WOOD, owns=True, resources=Resources()):
    """Player 0 with exactly `rooms` ROOM cells, house `material`, `resources`, and
    optionally owning Wood Slide Hammer (as a minor)."""
    s = setup(0)
    s = f.with_current_player(s, 0)
    s = f.with_house(s, 0, material)
    # default rooms are (1,0),(2,0); add ROOM cells across row 0 to reach `rooms`.
    overrides = {(0, c): Cell(cell_type=CellType.ROOM) for c in range(rooms - 2)}
    if overrides:
        s = f.with_grid(s, 0, overrides)
    if resources:
        s = f.with_resources(s, 0, **{fld: getattr(resources, fld)
                                      for fld in _ALL_FIELDS if getattr(resources, fld)})
    if owns:
        p = fast_replace(s.players[0], minor_improvements=frozenset({CARD_ID}))
        s = fast_replace(s, players=(p, s.players[1]))
    return s


def _fe(state, ctx):
    return set(effective_payments(state, 0, ctx))


# --- registration -----------------------------------------------------------

def test_registered():
    assert CARD_ID in MINORS
    assert MINORS[CARD_ID].cost == Cost(resources=Resources(wood=1))
    assert len(RENOVATE_TARGET_EXTENSIONS) >= 1
    assert any(cid == CARD_ID for cid, _fn in REDUCTIONS.get("renovate", []))


# --- target extension: WOOD -> STONE on the gate ----------------------------

def test_stone_is_a_legal_target_for_wood_house_with_five_rooms():
    s = _state(rooms=5, owns=True)
    targets = _legal_renovate_targets(s, s.players[0])
    assert HouseMaterial.STONE in targets   # direct-to-stone enabled


def test_stone_not_a_target_below_five_rooms():
    s = _state(rooms=4, owns=True)
    targets = _legal_renovate_targets(s, s.players[0])
    assert targets == [HouseMaterial.CLAY]   # only the normal wood->clay tier


def test_extension_fn_gating():
    # Gate met -> [STONE].
    assert _wood_to_stone(_state(rooms=5, owns=True), 0, HouseMaterial.WOOD) \
        == [HouseMaterial.STONE]
    # Fewer than 5 rooms -> [].
    assert _wood_to_stone(_state(rooms=4, owns=True), 0, HouseMaterial.WOOD) == []
    # Not owned -> [].
    assert _wood_to_stone(_state(rooms=5, owns=False), 0, HouseMaterial.WOOD) == []
    # House already clay (not the first renovation) -> [].
    assert _wood_to_stone(
        _state(rooms=5, material=HouseMaterial.CLAY, owns=True), 0, HouseMaterial.CLAY) == []


# --- discount: -2 stone on the stone renovation -----------------------------

def test_discount_two_stone_on_wood_to_stone():
    s = _state(rooms=5, owns=True, resources=_GEN)
    ctx = CostCtx("renovate", Resources(stone=5, reed=1), to_material=HouseMaterial.STONE)
    assert _fe(s, ctx) == {Resources(stone=3, reed=1)}   # 5 stone -2 = 3


def test_no_discount_below_five_rooms():
    s = _state(rooms=4, owns=True, resources=_GEN)
    ctx = CostCtx("renovate", Resources(stone=4, reed=1), to_material=HouseMaterial.STONE)
    assert _fe(s, ctx) == {Resources(stone=4, reed=1)}   # unchanged


def test_no_discount_on_clay_target():
    # The -2 stone discount is scoped to the STONE target; a wood->clay first
    # renovation is untouched (and has no stone to reduce anyway).
    s = _state(rooms=5, owns=True, resources=_GEN)
    ctx = CostCtx("renovate", Resources(clay=5, reed=1), to_material=HouseMaterial.CLAY)
    assert _fe(s, ctx) == {Resources(clay=5, reed=1)}


def test_no_discount_when_not_owned():
    s = _state(rooms=5, owns=False, resources=_GEN)
    ctx = CostCtx("renovate", Resources(stone=5, reed=1), to_material=HouseMaterial.STONE)
    assert _fe(s, ctx) == {Resources(stone=5, reed=1)}


# --- end-to-end House Redevelopment renovate --------------------------------

def test_real_flow_renovate_wood_to_stone_discounted():
    s = _state(rooms=5, owns=True, resources=Resources(stone=5, reed=1))
    s = f.with_space(s, "house_redevelopment", revealed=True)
    s = step(s, PlaceWorker(space="house_redevelopment"))
    s = step(s, ChooseSubAction(name="renovate"))

    stone_commits = [a for a in legal_actions(s)
                     if isinstance(a, CommitRenovate) and a.to_material is HouseMaterial.STONE]
    assert len(stone_commits) == 1
    assert stone_commits[0].payment == Resources(stone=3, reed=1)   # discounted

    s = step(s, stone_commits[0])
    p = s.players[0]
    assert p.house_material is HouseMaterial.STONE   # renovated directly to stone
    assert p.resources.stone == 2                    # 5 - 3
    assert p.resources.reed == 0                     # 1 - 1
