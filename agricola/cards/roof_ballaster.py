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


def _variants(state: GameState, idx: int) -> list[str]:
    """Legal play routes: always "decline"; "pay" only when 1 food is affordable."""
    variants = ["decline"]
    if state.players[idx].resources.food >= 1:
        variants.append("pay")
    return variants


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    if variant != "pay":
        return state                       # declined: no exchange
    p = state.players[idx]
    p = fast_replace(
        p, resources=p.resources + Resources(food=-1, stone=_num_rooms(p)),
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
