"""Seed Pellets (minor improvement, A65; Artifex Expansion; players -).

Card text: "Each time before you take an unconditional 'Sow' action, you get 1 grain."
Prerequisite: 3 Fields.

A free, no-downside grant in the exact shape of Drill Harrow (the `before_sow`
SUB-ACTION hook), but mandatory and choice-free instead of an optional paid trigger:
because +1 grain has no cost and no downside, a rational agent always takes it, so it is
modeled as an automatic effect (`register_auto`) that applies directly at the hook rather
than surfacing as a declinable `FireTrigger`. It fires once per `PendingSow` push — i.e.
once per Sow action — covering both Grain Utilization and Cultivation automatically, and
runs in the before-phase ("before you take"), so the +1 grain is on hand for the sow that
follows.

"Unconditional Sow" distinguishes the standard Sow sub-action (Grain Utilization /
Cultivation) from a card-granted *conditional* sow. No conditional-sow card exists in the
implemented set, so every `before_sow` event is an unconditional sow — this fires on all
of them. (If a conditional-sow card is ever added, this eligibility must additionally
inspect the PendingSow's provenance to exclude it; mirrors the note in drill_harrow.py.)

The prerequisite is a HAVE-check (3 fields), not a cost: FIELD cells on the farmyard
grid plus owned card-fields, planted or not. Ruling 45 (2026-07-12), verbatim:
'"field TILES" means the plowed fields on the farmyard grid; "field" is the BROADER
category and includes card-fields. So a card-field counts for field-count readers —
the Fields scoring category and any "you need N fields" requirement — while per-TILE
readers still exclude it (ruling 32 unchanged).' See CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "seed_pellets"


def _three_fields(state: GameState, idx: int) -> bool:
    """Prereq: at least 3 fields, planted or not — grid FIELD cells plus owned
    card-fields (ruling 45, 2026-07-12: "field" includes card-fields, so a
    "you need N fields" requirement counts them; ruling 47: each card counts
    exactly once)."""
    from agricola.cards.card_fields import card_field_count  # local: load-order safe
    p = state.players[idx]
    grid = p.farmyard.grid
    return sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    ) + card_field_count(p) >= 3


def _eligible(state: GameState, idx: int) -> bool:
    # Every implemented sow is unconditional, so the grant always applies; there is
    # nothing to gate (the +1 grain has no cost and no downside).
    return True


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, prereq=_three_fields)
register_auto("before_sow", CARD_ID, _eligible, _apply)
