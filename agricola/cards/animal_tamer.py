"""Animal Tamer (occupation, A86; Base Revised; players 1+).

Card text: "When you play this card, you immediately get your choice of 1 wood or 1 grain.
Instead of just 1 animal total, you can keep any 1 animal in each room of your house."
Clarification: "This effect is negated by the Milking Place D012." (Milking Place is not
implemented; when it lands it must drive house-pet capacity to 0 — see capacity_mods.)

Two effects:
  1. On-play, a CHOICE of 1 wood OR 1 grain. Modeled WIDE as a play-VARIANT
     (specs.PLAY_OCCUPATION_VARIANTS, like Roof Ballaster): playing the card surfaces two
     CommitPlayOccupations — variant "wood" and variant "grain" — both at zero surcharge
     (the normal occupation play cost), and the on-play grants the chosen good.
  2. A STANDING capacity effect: the house holds one animal per room instead of a single
     pet, and each room's animal may be a DIFFERENT type. The engine's "flexible slot"
     model already captures different-type-per-slot (each flexible slot holds one animal of
     any type; `can_accommodate` sums overflow across types into a flat slot count), so the
     grant is just raising the house's flexible-slot count from 1 to num_rooms — registered
     via the house-pet-capacity registry (capacity_mods). No new accommodation structure.
"""
from __future__ import annotations

from agricola.cards.capacity_mods import register_house_capacity
from agricola.cards.specs import register_occupation, register_play_occupation_variant
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, PlayerState

CARD_ID = "animal_tamer"


def _num_rooms(p: PlayerState) -> int:
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if p.farmyard.grid[r][c].cell_type == CellType.ROOM
    )


def _variants(state: GameState, idx: int) -> list[tuple[str, Resources]]:
    """The wide wood/grain choice, each at zero surcharge (the normal play cost). Both are
    always offered, so the card is always playable; the on-play reads the chosen good."""
    return [("wood", Resources()), ("grain", Resources())]


_GAIN = {"wood": Resources(wood=1), "grain": Resources(grain=1)}


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """Grant the chosen good. The capacity effect is passive (the registered modifier), so
    nothing else happens on play."""
    gain = _GAIN.get(variant, _GAIN["wood"])
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + gain)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_occupation(CARD_ID, _on_play)
register_play_occupation_variant(CARD_ID, _variants)
register_house_capacity(CARD_ID, _num_rooms)
