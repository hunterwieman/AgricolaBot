"""Wage (minor improvement, deck B #7; Bubulcus Expansion; traveling).

Card text: "You immediately get 2 food and 1 additional food for each major
improvement you have from the bottom row of the supply board." No cost, no
prerequisite, no printed VPs, and it is a TRAVELING (passing) card — after the
immediate effect it is passed to the opponent rather than kept.

Category 2 (on-play one-shot) + passing. `on_play` grants 2 food plus 1 food per
owned major improvement whose supply-board slot is in the bottom row.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "wage"

# Bottom row of the Revised major-improvement supply board (Clay Oven, Stone
# Oven, Joinery, Pottery, Basketmaker's Workshop); top row = the two Fireplaces,
# two Cooking Hearths, and the Well. Confirm layout with the user if in doubt.
BOTTOM_ROW_MAJORS = frozenset({5, 6, 7, 8, 9})


def _on_play(state: GameState, idx: int) -> GameState:
    owners = state.board.major_improvement_owners
    count = sum(1 for i in BOTTOM_ROW_MAJORS if owners[i] == idx)
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=2 + count))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    vps=0,
    passing_left=True,
    on_play=_on_play,
)
