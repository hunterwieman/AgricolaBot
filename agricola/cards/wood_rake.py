"""Wood Rake (minor improvement, D32; Dulcinaria Expansion; cost 1 wood).

Card text: "During scoring, if you had at least 7 goods in your fields before the
final harvest, you get 2 bonus points."
Printed VPs: none (the 2 points are conditional). No prerequisite.

A window-#1 snapshot feeding a Category-1 scoring term — with a TWIST that
forces banking (mirrors Big Country). The condition — "at least 7 goods in your
fields before the final harvest" — is a property of the farm at a moment that no
longer exists by scoring time: the final harvest is round 14's, and its field
phase empties the fields. So the points cannot be a derived end-game read off the
terminal state (the fields are bare then). Instead they are computed at the
qualifying moment and BANKED in the per-card CardStore, and the scoring term
reads the banked total back.

Timing — "before the final harvest" = the `immediately_before_harvest` window
(#1), round-14-gated (MIGRATED 2026-07-05 off the legacy pre-take
`harvest_field` seam). The distinction became LIVE the day Straw Manure landed:
Straw Manure adds vegetables to fields at window #3 (inside the harvest), so a
pre-take in-phase snapshot would wrongly count those adds toward "goods in your
fields BEFORE the final harvest" — window #1 precedes every in-harvest effect,
which is what the print asks. Two gates are load-bearing:

  1. round_number == 14 only. Window #1 opens EVERY harvest (rounds
     4/7/9/11/13/14); "the final harvest" is round 14's alone. Without the round
     gate an earlier harvest's >=7 field-goods would wrongly bank the points.
  2. "goods in your fields" = grain + veg summed across FIELD cells of the
     owner's farmyard — NOT the player's total grain/veg stockpile.

"Goods" here are the field crops (grain or vegetables); a field is sown with one
or the other, so the sum over FIELD cells of (grain + veg) is the field-goods
count.

See CARD_IMPLEMENTATION_PLAN.md Category 1 / II.7 (banked scoring via CardStore,
the Big Country pattern) and HARVEST_WINDOWS_DESIGN.md §1 (the window ladder).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.harvest_windows import register_harvest_window_hook
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState

CARD_ID = "wood_rake"

GOODS_THRESHOLD = 7
BONUS_POINTS = 2


def _field_goods(state: GameState, idx: int) -> int:
    """Grain + veg crops currently on the owner's FIELD cells — read at window
    #1, before ANY in-harvest effect (Straw Manure's #3 adds included) touches
    the fields."""
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
    # reaches the threshold. Window #1 opens at every harvest round, so the
    # round gate is what makes this "the final harvest" rather than any harvest.
    return state.round_number == 14 and _field_goods(state, idx) >= GOODS_THRESHOLD


def _apply(state: GameState, idx: int) -> GameState:
    # Bank the bonus points: the qualifying field state is gone by scoring time
    # (the round-14 field phase, later this same harvest, empties the fields),
    # so the points are stored now and read back by _score.
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
register_auto("immediately_before_harvest", CARD_ID, _eligible, _apply)
register_harvest_window_hook(CARD_ID, "immediately_before_harvest")
register_scoring(CARD_ID, _score)
