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

The prerequisite is a HAVE-check (3 field tiles in the farmyard), not a cost. See
CARD_AUTHORING_GUIDE.md.
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
    """Prereq: at least 3 FIELD tiles in the farmyard (planted or not)."""
    grid = state.players[idx].farmyard.grid
    return sum(
        1 for r in range(3) for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD
    ) >= 3


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
