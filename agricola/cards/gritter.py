"""Gritter (minor improvement, D58; Dulcinaria Expansion; cost 1 wood,
prereq play in round 5 or later).

Card text: "At the end of each action in which you sow vegetables in a field, you
get 1 food for each vegetable field you have (including the new ones)."
Cost: 1 Wood. Prerequisite: Play in Round 5 or Later. VPs: 0. Not passing.

Two pieces, the same before/after Sow-host shape as Garden Hoe — but the payout is
not a flat grant, it is *1 food per vegetable-bearing field the player currently
has*, paid only when this action planted at least one vegetable:

  - `before_sow` (fires when PendingSow is pushed, before any CommitSow): snapshot
    the current count of vegetable-bearing field cells into the per-card CardStore,
    so the after-hook can tell whether THIS sow planted any vegetables.
  - `after_sow` (fires at the CommitSow before->after phase flip, after the fields
    are filled): if the vegetable-bearing-field count grew by at least 1 this sow,
    grant `current_veg_field_count` food — the count is read AFTER the fields are
    filled, so it already includes the newly-sown vegetable fields ("including the
    new ones"). Then reset the snapshot to a canonical 0 so different commit orders
    reaching the same farmyard converge (transposition-table safety).

Why the before/after delta gate (and not a payout on every sow): the text pays
only on an action that *sows vegetables in a field*. A grain-only sow plants no
vegetable field, so the count delta is 0 and nothing is paid. The cumulative
on-grid veg-field count alone cannot tell a field this sow planted from one planted
in a prior round, so the snapshot delta isolates *this* sow's planting. The payout
amount, by contrast, is the full current count (text: "1 food for each vegetable
field you have, including the new ones"), not the delta — so even a single new
vegetable field pays out for every vegetable field on the farm.

Why register_auto (mandatory, choice-free) rather than a declinable FireTrigger:
the grant is a pure food gain with no downside, so it is never surfaced as an
optional choice. The round-5-or-later prerequisite is a play-time HAVE-check on
state.round_number (a prereq, not a cost).

"Each action in which you sow vegetables" maps to one `after_sow` per Sow
sub-action — the Sow primitive is the action boundary for both Grain Utilization
and Cultivation (and no implemented card grants two separate Sow sub-actions in one
placement). This mirrors Garden Hoe / Tumbrel, which treat the per-`after_sow`
boundary as the action boundary.

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

# Per project convention, `_card_slug("Gritter") == "gritter"`.
CARD_ID = "gritter"


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


def _prereq(state: GameState, idx: int) -> bool:
    """Prerequisite: play in round 5 or later (a play-time HAVE-check on the
    current round, not a cost)."""
    return state.round_number >= 5


def _snapshot_before(state: GameState, idx: int) -> GameState:
    """before_sow: record the pre-sow count of vegetable-bearing fields so the
    after-hook can tell whether THIS sow planted any vegetables."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, _veg_field_count(p)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _grant_after(state: GameState, idx: int) -> GameState:
    """after_sow: if this sow planted vegetables in at least 1 field, grant 1 food
    per vegetable field currently held (post-sow count, including the new fields).
    Always reset the snapshot to a canonical 0."""
    p = state.players[idx]
    before = p.card_state.get(CARD_ID, 0)
    current = _veg_field_count(p)
    planted_veg = (current - before) >= 1
    grant = Resources(food=current) if planted_veg else Resources()
    new_p = fast_replace(
        p,
        resources=p.resources + grant,
        card_state=p.card_state.set(CARD_ID, 0),   # reset to canonical value
    )
    return fast_replace(
        state,
        players=tuple(new_p if i == idx else state.players[i] for i in range(2)),
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), vps=0, prereq=_prereq)
register_auto("before_sow", CARD_ID, lambda state, idx: True, _snapshot_before)
register_auto("after_sow", CARD_ID, lambda state, idx: True, _grant_after)
