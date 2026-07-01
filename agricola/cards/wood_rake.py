"""Wood Rake (minor improvement, D32; Dulcinaria Expansion; cost 1 wood).

Card text: "During scoring, if you had at least 7 goods in your fields before the
final harvest, you get 2 bonus points."
Printed VPs: none (the 2 points are conditional). No prerequisite.

A Category-6 harvest-field hook (II.6) feeding a Category-1 scoring term — but
with a TWIST that forces banking (mirrors Big Country). The condition — "at least
7 goods in your fields before the final harvest" — is a property of the farm at a
moment that no longer exists by scoring time: the final harvest is round 14's, and
its field phase empties the fields. So the points cannot be a derived end-game read
off the terminal state (the fields are bare then). Instead they are computed at the
qualifying moment and BANKED in the per-card CardStore, and the scoring term reads
the banked total back.

Timing — "before the final harvest". `_resolve_harvest_field` fires the
`harvest_field` automatic effects BEFORE the mechanical crop take, so at fire time
the fields are still fully sown — exactly the pre-take snapshot the card asks about.
Two gates are load-bearing:

  1. round_number == 14 only. The hook fires at EVERY harvest (rounds 4/7/9/11/13/14);
     "the final harvest" is round 14's alone. Without the round gate an earlier
     harvest's >=7 field-goods would wrongly bank the points.
  2. "goods in your fields" = grain + veg summed across FIELD cells of the owner's
     farmyard — NOT the player's total grain/veg stockpile (which lives off-field).

"Goods" here are the field crops (grain or vegetables); a field is sown with one or
the other, so the sum over FIELD cells of (grain + veg) is the field-goods count.

See CARD_IMPLEMENTATION_PLAN.md Category 6 (harvest-field hook) and Category 1 /
II.7 (banked scoring via CardStore, the Big Country pattern).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto, register_harvest_field_hook
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "wood_rake"

GOODS_THRESHOLD = 7
BONUS_POINTS = 2


def _field_goods(state: GameState, idx: int) -> int:
    """Grain + veg crops currently on the owner's FIELD cells (the pre-take
    snapshot — fields are still sown when the harvest-field hook fires)."""
    grid = state.players[idx].farmyard.grid
    return sum(
        cell.grain + cell.veg
        for r in range(3)
        for c in range(5)
        for cell in (grid[r][c],)
        if cell.cell_type == CellType.FIELD
    )


def _eligible(state: GameState, idx: int) -> bool:
    # Only the FINAL harvest (round 14), and only when the field-goods count
    # reaches the threshold. The hook fires at every harvest round, so the
    # round gate is what makes this "the final harvest" rather than any harvest.
    return state.round_number == 14 and _field_goods(state, idx) >= GOODS_THRESHOLD


def _apply(state: GameState, idx: int) -> GameState:
    # Bank the bonus points: the qualifying field state is gone by scoring time
    # (the round-14 field phase, which runs right after this hook, empties the
    # fields), so the points are stored now and read back by _score.
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, BONUS_POINTS))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _score(state: GameState, idx: int) -> int:
    # The banked points (BONUS_POINTS if the round-14 pre-harvest field-goods
    # condition was met, else 0 — nothing banked).
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("harvest_field", CARD_ID, _eligible, _apply)
register_harvest_field_hook(CARD_ID)
register_scoring(CARD_ID, _score)
