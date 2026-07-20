"""Newly-Plowed Field (minor improvement, C17; Corbarius Expansion; Farm Planner).

Card text (verbatim): "When you play this card, you can immediately plow 1 field,
which needs not be adjacent to another field."
Cost: none. Prerequisite: Exactly 3 Field Tiles. VPs: none printed. Not passing.

An OPTIONAL on-play plow grant that composes the existing PendingPlow primitive,
with one twist: the plowed field "needs not be adjacent to another field", so the
normal subsequent-field adjacency narrowing is waived.

Timing/mechanism — "When you play this card, you can ..." is an OPTIONAL on-play
choice, so it surfaces WIDE per user ruling 17 (2026-07-05, the on-play optional
grant declines wide — Baker; extended to minors for Facades Carving): the choice
is part of the single play action, never an after-play trigger that could
interleave with other cards. The card registers a `variants_fn` on the
`PLAY_MINOR_VARIANTS` seam (specs.register_play_minor_variant) with two
zero-surcharge routes:
  - "plow": push the plow (offered only when an empty, non-enclosed cell exists —
    i.e. a legal target exists under the adjacency waiver); and
  - "decline": always present, a no-op — playing the card without the plow.
The "decline" route is the take-or-leave moment (user ruling 2026-07-20), so the
"plow" route's PendingPlow is MANDATORY once chosen — no per-frame skip flag,
matching the standing optionality-at-the-parent invariant. Because "plow" is
offered only when a target exists, the pushed plow never dead-ends. Neither route
carries a cost surcharge (the plow is free), so the card is playable whenever its
(empty) base cost is.

Adjacency waiver (user ruling 2026-07-20): the "plow" route pushes
`PendingPlow(..., ignore_adjacency=True)`. That flag WAIVES ONLY the
subsequent-field adjacency narrowing — every empty, non-enclosed cell becomes a
legal target, with cells adjacent to an existing field still included. The card
relaxes the constraint; it never forbids adjacency. The plow otherwise runs
through the normal CommitPlow path.

The gate for offering "plow" is therefore the adjacency-waived target existence
check, `_legal_plow_cells(p, ignore_adjacency=True)`, NOT the ordinary `_can_plow`
(which requires adjacency once a field exists) — with exactly 3 fields already on
the board, the only remaining empty cells may all be non-adjacent, which is
precisely the case this card exists to enable.

Prerequisite "Exactly 3 Field Tiles" (user ruling 2026-07-20): exactly 3
board-grid FIELD cells. The printed wording is "field TILES", and per ruling 32
(2026-07-06) a card-field is never a field tile, so card-fields do NOT count
toward this prerequisite — it is grid-only (the same doctrine as Calcium
Fertilizers' "No Field Tiles"). A play-time HAVE-check on the grid.

Family-inertness: minors exist only under GameMode.CARDS; the PLAY_MINOR_VARIANTS
registry entry and the granted plow are card-only, so the Family game is
byte-identical and the C++ gates are untouched. `PendingPlow.ignore_adjacency`
defaults to False (a canonical-skip field), so no C++ change.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor, register_play_minor_variant
from agricola.constants import CellType
from agricola.legality import _legal_plow_cells
from agricola.pending import PendingPlow, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "newly_plowed_field"


def _prereq(state: GameState, idx: int) -> bool:
    """Prerequisite "Exactly 3 Field Tiles": exactly 3 board-grid FIELD cells.

    Grid-only on purpose (user ruling 2026-07-20) — the printed wording is
    "field TILES", and per ruling 32 (2026-07-06) a card-field is never a field
    tile, so card-fields are excluded."""
    grid = state.players[idx].farmyard.grid
    return sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type is CellType.FIELD
    ) == 3


def _variants(state: GameState, idx: int) -> list:
    """The wide on-play choice (user ruling 2026-07-20). Two zero-surcharge
    routes: "plow" (offered only when a legal adjacency-waived target exists) and
    "decline" (always present, the no-op play). The plow is free, so neither
    route surcharges the (empty) base cost.

    "plow" is gated on the ADJACENCY-WAIVED target set — an empty, non-enclosed
    cell existing — not on `_can_plow`, because with exactly 3 fields on the board
    the remaining empties may all be non-adjacent, the very case this card
    enables."""
    variants = [("decline", Resources())]
    if _legal_plow_cells(state.players[idx], ignore_adjacency=True):
        variants.append(("plow", Resources()))
    return variants


def _on_play(state: GameState, idx: int, variant: str | None = None) -> GameState:
    """"plow" pushes the granted plow with adjacency waived; "decline" is a no-op.

    The "decline" route was the take-or-leave moment, so the pushed plow is
    MANDATORY (no per-frame skip). `_variants` offers "plow" only when a target
    exists, so the forced plow never dead-ends. The plow runs through the normal
    CommitPlow path."""
    if variant == "plow":
        return push(state, PendingPlow(
            player_idx=idx,
            initiated_by_id="card:newly_plowed_field",
            ignore_adjacency=True,
        ))
    return state                        # "decline": played without the plow


# Cost none; prereq exactly 3 board-grid field tiles; no printed VP; not passing.
register_minor(
    CARD_ID,
    cost=Cost(),
    prereq=_prereq,
    vps=0,
    on_play=_on_play,
)

# The wide on-play choice (user ruling 2026-07-20): "plow" (adjacency waived) vs
# "decline", each zero-surcharge.
register_play_minor_variant(CARD_ID, _variants)
