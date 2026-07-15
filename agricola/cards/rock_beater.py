"""Rock Beater (occupation, E150; Ephipparius Expansion; players 4+).

Card text: "You can use an action space providing both stone and a different building
resource even if it is occupied by another player. Stone rooms cost you 2 stone less
each."

Only the SECOND clause is live in this 2-player engine; it is implemented as a passive
COST-REDUCTION (COST_MODIFIER_DESIGN.md §1.1), the Bricklayer shape: "Stone rooms cost 2
stone less each" is a −2 stone delta on build_room, gated on the house being STONE (a
room's material is the house's material — ROOM_COSTS — so a "stone room" is precisely a
room built in a stone house). The chokepoint floors at 0.

The FIRST clause (place on an occupied action space that provides stone + a different
building resource) is INERT in the 2-player game: no space on the 2-player board provides
both stone and a different building resource in one use (the two stone spaces —
western_quarry / eastern_quarry — provide stone only; forest/clay_pit/reed_bank each
provide a single non-stone resource). It is therefore vacuous exactly like Geologist's
"in games with 3+ players, this also applies to the Clay Pit" clause and Wood Cutter's
Copse/Grove note — a multi-player-only clause referencing spaces absent from the
2-player board — so it is deliberately not implemented (there is nothing it could ever
affect here). No on-play effect.
"""
from __future__ import annotations

from agricola.cards.cost_mods import register_reduction
from agricola.cards.specs import _noop_on_play, register_occupation
from agricola.constants import HouseMaterial
from agricola.resources import Resources

CARD_ID = "rock_beater"


def _less_2_stone_for_stone_rooms(state, idx, ctx, cost: Resources) -> Resources:
    # A "stone room" is a room in a stone house (room material == house material).
    if state.players[idx].house_material is HouseMaterial.STONE:
        return cost - Resources(stone=2)
    return cost


register_reduction("build_room", CARD_ID, _less_2_stone_for_stone_rooms)

register_occupation(CARD_ID, _noop_on_play)   # no on-play effect (passive cost card)
