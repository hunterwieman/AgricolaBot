"""Grange (minor improvement, B37; Bubulcus Expansion; players -).

Card text: "When you play this card, you immediately get 1 food."
Prerequisite: 6 Field Tiles and All Animal Types (>= 6 field tiles AND
>= 1 sheep, >= 1 wild boar, >= 1 cattle to PLAY it).
Printed VPs: 3.

Category 2 (on-play one-shot): the immediate +1 food is the whole on-play effect.
The 3 printed VPs are scored automatically from the spec's `vps` (scoring.py),
so there is no `register_scoring` term.

The prerequisite is a PLAY-time HAVE-check (never spent), distinct from the cost —
this card has no resource cost. "6 Field Tiles" counts grid cells whose
`cell_type is CellType.FIELD` (the scoring.py num_fields idiom), regardless of
whether they are sown; "All Animal Types" is the briar_hedge one-of-each-animal
predicate. Field is a real CellType, so no enclosed_cells guard is needed here.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "grange"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _prereq(state: GameState, idx: int) -> bool:
    p = state.players[idx]
    grid = p.farmyard.grid
    num_fields = sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    )
    a = p.animals
    return (
        num_fields >= 6
        and a.sheep >= 1
        and a.boar >= 1
        and a.cattle >= 1
    )


register_minor(CARD_ID, prereq=_prereq, vps=3, on_play=_on_play)
