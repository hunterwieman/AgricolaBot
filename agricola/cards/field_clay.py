"""Field Clay (minor improvement, D5; Dulcinaria Expansion; players -).

Card text: "You immediately get 1 clay for each planted field you have."
Prerequisite: 1 planted field. Cost: 1 Food. Printed 0 VP.

Category: on-play one-shot, PASSING (traveling minor — `passing_left='X'` in the
catalog: after the on-play effect the card moves to the opponent's hand). When
played, count the player's
PLANTED fields — FIELD cells holding at least one crop (grain or veg) — and grant
that many clay immediately. A freshly-plowed-but-unsown FIELD does NOT count (it is
not planted), so counting all FIELD cells would over-grant; the predicate matches a
field with a crop on it (grain > 0 or veg > 0), the same "planted = sown" reading
used by Ash Trees.

The prerequisite (1 planted field) guarantees the count is >= 1, so the grant is
always >= 1 clay. No CardStore, no triggers.

Card-fields count too. User ruling 45 (2026-07-12), verbatim: ""field TILES"
means the plowed fields on the farmyard grid; "field" is the BROADER category
and includes card-fields. So a card-field counts for field-count readers — the
Fields scoring category and any "you need N fields" requirement — while
per-TILE readers still exclude it (ruling 32 unchanged)." This card reads
"planted field" (not "field tile"), so `_planted_field_count` adds
`planted_card_field_count(p)` — 1 per card-field holding ANYTHING, however
many stacks (ruling 47, 2026-07-12) — serving both the prerequisite and the
payout. A wood-planted card-field counts: it IS planted (its own text says
"plant wood on this card").
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "field_clay"


def _planted_field_count(state: GameState, idx: int) -> int:
    """Planted fields: FIELD cells with a crop on them (planted = sown — grain
    or veg present), plus card-fields holding anything (ruling 45, 2026-07-12;
    1 per card per ruling 47 — a wood-planted card IS planted)."""
    from agricola.cards.card_fields import (   # local import: load-order safe
        planted_card_field_count,
    )
    p = state.players[idx]
    grid = p.farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
        and (grid[r][c].grain > 0 or grid[r][c].veg > 0)
    ) + planted_card_field_count(p)


def _prereq_one_planted_field(state: GameState, idx: int) -> bool:
    return _planted_field_count(state, idx) >= 1


def _on_play(state: GameState, idx: int) -> GameState:
    n = _planted_field_count(state, idx)            # >= 1 by the prerequisite
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(clay=n))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(food=1)),
    prereq=_prereq_one_planted_field,
    passing_left=True,
    on_play=_on_play,
)
