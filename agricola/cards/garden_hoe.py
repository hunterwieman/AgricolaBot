"""Garden Hoe (minor improvement, A79; Artifex Expansion; cost 1 wood).

Card text: "Each time you take an unconditional 'Sow' action planting vegetables
in at least 1 field, you get 1 clay and 1 stone."

The grant is FLAT — +1 clay +1 stone *once* per qualifying Sow action, regardless
of how many vegetable fields were planted. It fires only when that Sow planted
vegetables in at least one field.

Mechanism — a before/after pair of AUTOMATIC effects on the Sow sub-action host
(the same before/after CardStore-snapshot shape as Shepherd's Crook on the
build-fences host). The grant is mandatory and parameter-free (+1 clay +1 stone
is a pure building-resource gain with no downside), so it is modeled with
`register_auto`, not a declinable FireTrigger:

  - `before_sow` (fires when PendingSow is pushed, before any CommitSow): snapshot
    the current count of vegetable-bearing field cells into the per-card CardStore.
  - `after_sow` (fires at the CommitSow before->after phase flip, after the fields
    are filled): if the vegetable-bearing-field count grew by at least 1 this sow,
    grant 1 clay + 1 stone (once, flat). Then reset the snapshot to a canonical 0 so
    different commit orders reaching the same farmyard converge (transposition-table
    safety).

Why the before/after delta rather than reading the commit: `register_auto`'s
apply_fn receives only (state, idx) — the CommitSow's veg count is invisible — and
the cumulative on-grid veg count alone cannot distinguish a field this sow planted
from one planted in a prior round. The count delta isolates *this* sow's planting.
`after_sow` fires post-fill, so the after-snapshot already reflects the new veg.

"Unconditional Sow" distinguishes the standard Sow sub-action (Grain Utilization /
Cultivation) from a card-granted *conditional* sow. No conditional-sow card exists
in the implemented set, so every `before_sow`/`after_sow` event is an unconditional
sow — this fires on all of them. (If a conditional-sow card is ever added, this
must additionally inspect the PendingSow's provenance to exclude it; mirrors
seed_pellets.py / drill_harrow.py.)

Card-only state (the CardStore snapshot) defaults to its canonical 0, so the Family
game is byte-identical and the C++ gates are untouched. See CARD_AUTHORING_GUIDE.md
§4 (deferred snapshot / CardStore).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

# `_card_slug("Garden Hoe") == "garden_hoe"` (the project's card-id convention,
# joining this card to its data-file name + effect text in the web UI).
CARD_ID = "garden_hoe"


def _veg_field_count(player) -> int:
    """Number of field cells currently bearing vegetables (veg > 0).

    A sown field holds grain XOR veg (never both — _execute_sow fills grain=3 OR
    veg=2 per cell), so this counts exactly the vegetable-planted fields."""
    grid = player.farmyard.grid
    return sum(
        1
        for r in range(3)
        for c in range(5)
        if grid[r][c].cell_type == CellType.FIELD and grid[r][c].veg > 0
    )


def _snapshot_before(state: GameState, idx: int) -> GameState:
    """before_sow: record the pre-sow count of vegetable-bearing fields so the
    after-hook can tell whether THIS sow planted any vegetables."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, _veg_field_count(p)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _grant_after(state: GameState, idx: int) -> GameState:
    """after_sow: if this sow planted vegetables in at least 1 field, grant 1 clay
    + 1 stone (flat, once). Always reset the snapshot to a canonical 0."""
    p = state.players[idx]
    before = p.card_state.get(CARD_ID, 0)
    planted_veg = (_veg_field_count(p) - before) >= 1
    grant = Resources(clay=1, stone=1) if planted_veg else Resources()
    new_p = fast_replace(
        p,
        resources=p.resources + grant,
        card_state=p.card_state.set(CARD_ID, 0),   # reset to canonical value
    )
    return fast_replace(
        state,
        players=tuple(new_p if i == idx else state.players[i] for i in range(2)),
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("before_sow", CARD_ID, lambda state, idx: True, _snapshot_before)
register_auto("after_sow", CARD_ID, lambda state, idx: True, _grant_after)
