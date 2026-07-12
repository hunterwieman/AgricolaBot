"""Garden Claw (minor improvement, C47; Corbarius Expansion; players -).

Card text: "Place 1 food on each remaining round space, up to three times the
number of planted fields you have. At the start of these rounds, you get the food."
Cost: 1 Wood. No prerequisite. VPs: 0. Not passing.

Category 8 (deferred goods). The whole effect runs at play (on_play). Let P be the
number of PLANTED fields the player has at play-time — a FIELD cell holding at least
one crop (grain or veg). Schedule 1 food onto each of the next `3 * P` round spaces:
rounds R+1..R+3*P where R is the current round. `schedule_resources` clamps slots
outside 1..14, so the "each REMAINING round space" cap on rounds left is handled for
free (no separate min against the rounds remaining — Trellises relies on exactly the
same clamp). The "up to three times the number of planted fields" cap is therefore
`min(remaining round spaces, 3 * P)`, and the lower of the two binds automatically.
P == 0 (no planted fields) schedules nothing — a legal +0.

Distinct from Trellises (A47), which counts FENCE pieces built; Garden Claw counts
3x PLANTED fields, measured at play-time.

Card-fields count too. User ruling 45 (2026-07-12), verbatim: ""field TILES"
means the plowed fields on the farmyard grid; "field" is the BROADER category
and includes card-fields. So a card-field counts for field-count readers — the
Fields scoring category and any "you need N fields" requirement — while
per-TILE readers still exclude it (ruling 32 unchanged)." This card reads
"planted fields" (not "field tiles"), so `_planted_fields` adds
`planted_card_field_count(p)` — 1 per card-field holding ANYTHING, however
many stacks (ruling 47, 2026-07-12). A wood-planted card-field counts: it IS
planted (its own text says "plant wood on this card").
"""
from __future__ import annotations

from agricola.cards.schedules import schedule_resources
from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "garden_claw"


def _planted_fields(state: GameState, idx: int) -> int:
    """Planted fields: FIELD cells holding at least one crop (grain or veg —
    'planted' = sown), plus card-fields holding anything (ruling 45,
    2026-07-12; 1 per card per ruling 47 — a wood-planted card IS planted)."""
    from agricola.cards.card_fields import (   # local import: load-order safe
        planted_card_field_count,
    )
    p = state.players[idx]
    grid = p.farmyard.grid
    return sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
        and (grid[r][c].grain > 0 or grid[r][c].veg > 0)
    ) + planted_card_field_count(p)


def _on_play(state: GameState, idx: int) -> GameState:
    R = state.round_number
    n = 3 * _planted_fields(state, idx)
    return schedule_resources(state, idx, range(R + 1, R + 1 + n), Resources(food=1))


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    on_play=_on_play,
)
