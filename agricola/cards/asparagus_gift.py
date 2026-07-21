"""Asparagus Gift (minor improvement, A68; Artifex Expansion; Crop Provider).

Card text: "Each time you build a number of fences equal to or greater than the
current round, you immediately get 1 vegetable."
Cost: free. Prerequisite: 1 Unplanted Field. VPs: 0. Not passing.

The threshold is on the count of fence PIECES (edges) placed in ONE build-fences
action, NOT pastures or area — "build X is one action", so the count is the
before/after delta of `helpers.fences_built` across the whole action, never per
pasture commit. A qualifying action grants a FIXED 1 vegetable (not 1 per fence
over the threshold). The threshold is the round currently in progress
(`state.round_number`), compared `delta >= round_number` (the text's
"equal to or greater than").

Mechanism — a before/after pair of AUTOMATIC effects on the build_fences
sub-action host (the uniform before/after host introduced for Shepherd's Crook;
see SUBACTION_HOOK_REFACTOR.md). A vegetable always fits (it is a non-animal
good with no accommodation), so the grant is mandatory and parameter-free, hence
`register_auto`, not a declinable FireTrigger:

  - `before_build_fences` (fires when PendingBuildFences is pushed, before any
    pasture commit): snapshot the current fence-piece count (a scalar int) into
    the per-card CardStore.
  - `after_build_fences` (fires at the Proceed work-complete flip, after all
    commits): compute `delta = fences_built(now) - snapshot`; if
    `delta >= state.round_number`, grant 1 vegetable. Then reset the snapshot to
    a canonical 0 (so two commit orders reaching the same farmyard converge to
    the same state).

This fires identically whether fencing is reached via the Fencing action space or
Farm Redevelopment ("Overhaul"), since both push PendingBuildFences. Card-only
state (the CardStore int) defaults to 0, so the Family game is byte-identical and
the C++ gates are untouched. See CARD_AUTHORING_GUIDE.md §4 (deferred snapshot /
CardStore) and CARD_IMPLEMENTATION_PLAN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.constants import CellType
from agricola.helpers import fences_built
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

# Per project convention, `_card_slug(json_name) == card_id`; "Asparagus Gift"
# slugifies to "asparagus_gift".
CARD_ID = "asparagus_gift"

VEG_PER_QUALIFYING_ACTION = 1


def _one_unplanted_field(state: GameState, idx: int) -> bool:
    """Prerequisite: at least one unplanted field — a FIELD cell with nothing
    sown on it (a field is FIELD-typed whether or not it is sown), OR an owned
    card-field currently holding nothing (an owned, empty card-field is an
    unplanted field). Ruling 45 (2026-07-12), verbatim: ""field TILES" means
    the plowed fields on the farmyard grid; "field" is the BROADER category
    and includes card-fields. So a card-field counts for field-count readers —
    the Fields scoring category and any "you need N fields" requirement —
    while per-TILE readers still exclude it (ruling 32 unchanged)."."""
    from agricola.cards.card_fields import unplanted_card_field_count
    p = state.players[idx]
    grid = p.farmyard.grid
    # Stone-holding fields (Stone Clearing) are NOT unplanted — "considered
    # planted until the stone is gone" (its errata; user ruling 2026-07-20).
    return unplanted_card_field_count(p) >= 1 or any(
        grid[r][c].field_empty
        for r in range(3)
        for c in range(5)
    )


def _snapshot_before(state: GameState, idx: int) -> GameState:
    """before_build_fences: record the pre-action fence-piece count so the
    after-hook can measure how many were placed in THIS action."""
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, fences_built(p.farmyard))
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _grant_after(state: GameState, idx: int) -> GameState:
    """after_build_fences: grant 1 vegetable iff the number of fence pieces placed
    in this action is >= the current round number."""
    p = state.players[idx]
    before = p.card_state.get(CARD_ID, 0)
    delta = fences_built(p.farmyard) - before
    grant = Resources(veg=VEG_PER_QUALIFYING_ACTION) if delta >= state.round_number else Resources()
    new_p = fast_replace(
        p,
        resources=p.resources + grant,
        card_state=p.card_state.set(CARD_ID, 0),   # reset to canonical empty
    )
    return fast_replace(
        state,
        players=tuple(new_p if i == idx else state.players[i] for i in range(2)),
    )


register_minor(CARD_ID, cost=Cost(), vps=0, prereq=_one_unplanted_field)
register_auto("before_build_fences", CARD_ID, lambda state, idx: True, _snapshot_before)
register_auto("after_build_fences", CARD_ID, lambda state, idx: True, _grant_after)
