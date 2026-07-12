"""Schnapps Distillery (minor improvement, C59; Consul Dirigens Expansion; Food Provider).

Card text: "In each feeding phase, you can use this card to turn exactly 1
vegetable into 5 food. During scoring, you get 1 bonus point each for your 5th
and 6th vegetable."
Cost: 2 Stone, 1 Vegetable. VPs: 2. Not passing.

Two independent effects, both off existing machinery:

1. A recurring, optional, once-per-harvest goods-to-food conversion offered
   during HARVEST_FEED — the exact shape HarvestConversionSpec exists for
   (mirrors the three built-in crafts joinery/pottery/basketmaker and Beer Keg).
   "Exactly 1 vegetable -> 5 food" is a single registry entry with
   input_cost = Resources(veg=1), food_out = 5. The HARVEST_FEED enumerator
   surfaces one CommitHarvestConversion per owned-and-not-yet-fired-this-harvest
   entry, and firing it adds the conversion_id to harvest_conversions_used; that
   set is reset to empty at the start of every harvest's FEED phase. So a single
   entry automatically gives the card exactly one use per feeding phase — no
   extra cross-variant guard is needed (unlike Beer Keg, which has three grain
   amounts). "Turn exactly 1 vegetable into 5 food" has no choice of amount, so
   there is exactly one variant.

2. A scoring term: +1 point each for the player's 5th and 6th vegetable. The
   relevant count is the SAME total scoring.py uses for the printed-veg track —
   supply veg PLUS veg sitting on unharvested FIELD cells PLUS veg planted on
   the player's card-fields — not just supply veg, which would undercount a
   player holding vegetables on fields. The card-field term follows ruling 45
   (2026-07-12), verbatim: ""field TILES" means the plowed fields on the
   farmyard grid; "field" is the BROADER category and includes card-fields. So
   a card-field counts for field-count readers — the Fields scoring category
   and any "you need N fields" requirement — while per-TILE readers still
   exclude it (ruling 32 unchanged)." Veg planted on a card-field is a
   vegetable the player has, exactly as scoring.py's veg total now counts it
   (`planted_card_crops`); stone planted on Rock Garden is not a vegetable and
   never counts. The term returns (1 if total_veg >= 5 else 0) + (1 if
   total_veg >= 6 else 0). The card's printed 2 VP is awarded separately by the
   engine via MINORS[card_id].vps, so this term must NOT re-add it (no double
   count).

Card-only state (the single harvest_conversions_used entry) is empty in the
Family game, so it stays byte-identical and the C++ gates are untouched.
See CARD_AUTHORING_GUIDE.md, harvest_conversions.py, and beer_keg.py.
"""
from __future__ import annotations

from agricola.cards.harvest_conversions import (
    HarvestConversionSpec,
    register_harvest_conversion,
)
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "schnapps_distillery"


def _is_owned(state: GameState, idx: int) -> bool:
    """The conversion is offered iff the player owns Schnapps Distillery.

    The engine's once-per-harvest accounting (harvest_conversions_used, reset at
    the start of every FEED phase; the enumerator skips already-used ids) handles
    the "exactly once per feeding phase" rule on top of this, so no further guard
    is needed.
    """
    return CARD_ID in state.players[idx].minor_improvements


def _total_veg(state: GameState, idx: int) -> int:
    """Vegetables counted exactly as scoring.py's veg total: supply veg plus
    all veg sitting on unharvested FIELD cells plus veg planted on card-fields
    (`planted_card_crops` — ruling 45, 2026-07-12; verbatim quote in the module
    docstring). Non-veg card-field goods contribute nothing."""
    from agricola.cards.card_fields import planted_card_crops  # load-order safe
    p = state.players[idx]
    grid = p.farmyard.grid
    on_fields = sum(
        grid[r][c].veg
        for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    )
    _card_grain, card_veg = planted_card_crops(p)
    return p.resources.veg + on_fields + card_veg


def _score(state: GameState, idx: int) -> int:
    """+1 point each for the 5th and 6th vegetable (the printed 2 VP is awarded
    separately by the engine, so it is NOT included here)."""
    total = _total_veg(state, idx)
    return (1 if total >= 5 else 0) + (1 if total >= 6 else 0)


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(stone=2, veg=1)),
    vps=2,
)

register_harvest_conversion(HarvestConversionSpec(
    conversion_id=CARD_ID,
    input_cost=Resources(veg=1),
    food_out=5,
    is_owned_fn=_is_owned,
))

register_scoring(CARD_ID, _score)
