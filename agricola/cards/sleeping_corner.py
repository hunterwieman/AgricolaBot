"""Sleeping Corner (minor improvement, A26; Base Revised; players -).

Card text: "You can use any \"Wish for Children\" action space even if it is occupied by
one other player's person."
Clarification: "But not if occupied by 2+ other player's people."
Cost: 1 Wood. Prerequisite: 2 Grain Fields. Kept (not traveling). 1 printed VP.

One mechanism — a LEGALITY RELAXATION on worker placement: the owner may place on a "Wish
for Children" space even when an opponent already holds it. This is a relaxation of the
occupancy check `_is_available`, registered via `register_occupancy_override` (consulted
only when the space is occupied, so the Family game pays nothing).

Two subtleties, both load-bearing:

- COUNT PLAYERS, NOT WORKERS. A normally-used wish space already holds TWO of one player's
  workers — the parent placed by the action plus the newborn the action generates (the
  engine models this in `_resolve_wish_for_children`). So the clarification "not if occupied
  by 2+ people" means "2+ other PLAYERS with a worker here," not "2+ workers." The override
  therefore requires exactly one OTHER player to have a worker on the space (the `== 1`
  below), tolerating that one player's parent+newborn pair. The `!= 0` self-check also stops
  the owner using a space they already occupy.

- The exact-one-other-player shape generalizes to 4-player: in the current 2-player game the
  occupied branch with `workers[ap] == 0` always means the single opponent holds it, so
  `others_with_workers == 1` is automatically true — but writing it as a player count keeps
  it correct if the 4-player variant ever lands.

Card-only state (the override registry is empty in the Family game), so the Family game is
byte-identical and the C++ differential gates are untouched. See CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.constants import CellType
from agricola.cards.specs import register_minor
from agricola.legality import register_occupancy_override
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space

CARD_ID = "sleeping_corner"
WISH_SPACES = frozenset({"basic_wish_for_children", "urgent_wish_for_children"})


def _prereq(state: GameState, idx: int) -> bool:
    """2 Grain Fields — at least two grain fields: FIELD cells that currently
    hold grain plus grain-holding card-fields. Ruling 45 (2026-07-12),
    verbatim: ""field TILES" means the plowed fields on the farmyard grid;
    "field" is the BROADER category and includes card-fields. So a card-field
    counts for field-count readers — the Fields scoring category and any "you
    need N fields" requirement — while per-TILE readers still exclude it
    (ruling 32 unchanged)." Each grain-holding card counts exactly once
    (ruling 47, 2026-07-12); a veg- or wood-holding card-field is not a grain
    field."""
    from agricola.cards.card_fields import crop_card_field_count
    p = state.players[idx]
    grid = p.farmyard.grid
    grain_fields = sum(
        1
        for row in grid
        for cell in row
        if cell.cell_type == CellType.FIELD and cell.grain > 0
    ) + crop_card_field_count(p, "grain")
    return grain_fields >= 2


def _occupancy_override(state: GameState, space_id: str) -> bool:
    """The current player may place on an occupied "Wish for Children" space iff they
    own Sleeping Corner, hold no worker there themselves, and exactly one OTHER player
    does (count players, not workers)."""
    if space_id not in WISH_SPACES:
        return False
    ap = state.current_player
    if CARD_ID not in state.players[ap].minor_improvements:
        return False
    workers = get_space(state.board, space_id).workers
    if workers[ap] != 0:
        return False
    others_with_workers = sum(1 for i, w in enumerate(workers) if i != ap and w > 0)
    return others_with_workers == 1


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    prereq=_prereq,
    vps=1,
)
register_occupancy_override(_occupancy_override)
