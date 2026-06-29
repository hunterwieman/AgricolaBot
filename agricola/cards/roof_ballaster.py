"""Roof Ballaster (occupation, B123; Base Revised; players 1+).

Card text: "When you play this card, you can immediately pay 1 food to get 1 stone
for each room you have."

Category 2 (on-play one-shot), but the effect is OPTIONAL and all-or-nothing: pay
exactly 1 food → get `num_rooms` stone, or pay nothing and get nothing. This is
modeled as a PLAY-VARIANT (specs.PLAY_OCCUPATION_VARIANTS), exactly like Cooking
Hearth's return-fireplace options in CommitBuildMajor: playing Roof Ballaster
surfaces up to two CommitPlayOccupations — variant "pay" (only when food ≥ 1) and
variant "decline" (always) — and the on_play reads the chosen variant. No trigger,
no extra frame; the choice is resolved as part of the single play action. (The
"decline" variant is always offered, so the card is always playable.) Played via
Lessons. See CARD_IMPLEMENTATION_PLAN.md Category 2.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation, register_play_occupation_variant
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, PlayerState

CARD_ID = "roof_ballaster"


def _num_rooms(p: PlayerState) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """Legal play routes, each declaring its food SURCHARGE on top of the base play cost
    (FOOD_PAYMENT_DESIGN.md §8): "decline" (no surcharge) and "pay" (1 food → 1 stone per
    room). Both are returned unconditionally — affordability of base+surcharge (with
    liquidation) is filtered by the play-occupation enumerator, which knows the base play
    cost. This removes the old pre-debit `food >= 1` check that could drive food negative on
    a 2nd-occupation play with exactly 1 food."""
    return [("decline", Resources()), ("pay", Resources(food=1))]


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Grant the stone for the "pay" variant. The 1-food surcharge is NOT debited here — it is
    folded into the play cost and debited by `_execute_play_occupation` (raising it via the
    shared food-payment path if short) before this on_play runs (FOOD_PAYMENT_DESIGN.md §8)."""
    if variant != "pay":
        return state                       # declined: no exchange
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(stone=_num_rooms(p)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
