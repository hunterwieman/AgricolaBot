"""Storage Barn (minor improvement, A6; Artifex Expansion; players any).

Card text: "If you have the Well, Joinery, Pottery, and/or Basketmaker's
Workshop, you immediately get 1 stone, 1 wood, 1 clay, and/or 1 reed,
respectively."

Clarifications: "You may only get 1 of each resource, even in a 6-player game
with multiple copies of the same improvement. Applies to the 10 (or 18 in 6p)
major improvements."

The four majors map to a building resource, respectively:
  Well (idx 4)                  -> 1 stone
  Joinery (idx 7)               -> 1 wood
  Pottery (idx 8)               -> 1 clay
  Basketmaker's Workshop (idx 9)-> 1 reed
Ownership is read from the BOARD (state.board.major_improvement_owners), not a
PlayerState field. In the 2-player game each major exists in exactly one copy
and is owned 0 or 1 times, so the "1 of each" clarification needs no dedup.

Category 2 (on-play one-shot). No cost, no prerequisite, no printed VPs, kept
(not passing). No stored state.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "storage_barn"

# (major_improvement index, resource granted if owned by the player).
_GRANTS: tuple[tuple[int, Resources], ...] = (
    (4, Resources(stone=1)),   # Well
    (7, Resources(wood=1)),    # Joinery
    (8, Resources(clay=1)),    # Pottery
    (9, Resources(reed=1)),    # Basketmaker's Workshop
)


def _on_play(state: GameState, idx: int) -> GameState:
    owners = state.board.major_improvement_owners
    gain = Resources()
    for major_idx, res in _GRANTS:
        if owners[major_idx] == idx:
            gain = gain + res
    if not gain:
        return state
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + gain)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, on_play=_on_play)
