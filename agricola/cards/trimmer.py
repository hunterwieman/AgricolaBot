"""Trimmer (occupation, B124; Bubulcus Expansion; Building Resource Provider;
players 1+).

Card text: "In each work phase, after you enclose at least one farmyard space, you
get 2 stone. (Subdividing an existing pasture does not count.)"

Printed VPs: none. Cost: none. Prerequisite: none. Not a passing card. Played via
Lessons (occupation), so on-play is a no-op.

Mechanism — a before/after pair of AUTOMATIC effects on the build_fences sub-action
host (the same uniform before/after host Shepherd's Crook uses):

  - `before_build_fences` (fires when PendingBuildFences is pushed, before any
    pasture commit): snapshot the set of currently-enclosed cells into the per-card
    CardStore.
  - `after_build_fences` (fires at the work-complete flip, after all commits): if
    any cell became *newly* enclosed during this action (`enclosed_after −
    enclosed_before` is non-empty) AND Trimmer has not already fired this work
    phase, grant 2 stone and latch `used_this_round`. Then always reset the snapshot
    to a canonical empty value so two commit orders reaching the same farmyard
    converge to the same state.

Two subtleties, both handled by the snapshot-diff computed once at the after-flip:

  - "Subdividing an existing pasture does not count": a pure subdivision encloses no
    NEW cell (the cells were already inside a pasture), so `newly_enclosed` is empty
    and the grant is naturally skipped — no special-case code.
  - "In each work phase ... you get 2 stone" is once per WORK PHASE, not once per
    action. The `used_this_round` latch (reset at round start by
    `_complete_preparation`) means two enclosing actions in one round — e.g. the
    Fencing space plus a Farm-Redevelopment Overhaul — grant +2 stone total, not +4.

This fires identically whether fencing is reached via the Fencing action space or
Farm Redevelopment ("Overhaul"), since both push PendingBuildFences. Card-only state
(the CardStore snapshot + the `used_this_round` latch) defaults canonically, so the
Family game is byte-identical and the C++ gates are untouched. See shepherds_crook.py
(the before/after build-fences snapshot pattern) and cob.py (the once-per-work-phase
`used_this_round` latch).
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.helpers import enclosed_cells
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "trimmer"

STONE_GRANT = 2


def _snapshot_before(state: GameState, idx: int) -> GameState:
    """before_build_fences: record the pre-action enclosed cells so the after-hook
    can tell whether any farmyard space became newly enclosed."""
    p = state.players[idx]
    p = fast_replace(
        p, card_state=p.card_state.set(CARD_ID, enclosed_cells(p.farmyard))
    )
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _grant_after(state: GameState, idx: int) -> GameState:
    """after_build_fences: if at least one farmyard space was newly enclosed this
    action AND Trimmer hasn't already fired this work phase, grant 2 stone and latch
    `used_this_round`. Always reset the snapshot to canonical empty."""
    p = state.players[idx]
    before = p.card_state.get(CARD_ID, None)
    if before is None:
        # Defensive: no snapshot was taken (cannot happen — before_build_fences
        # always fires at the push). Grant nothing rather than risk over-granting.
        return state
    newly_enclosed = enclosed_cells(p.farmyard) - before
    granted = bool(newly_enclosed) and CARD_ID not in p.used_this_round
    new_p = fast_replace(
        p,
        resources=p.resources + Resources(stone=STONE_GRANT) if granted else p.resources,
        used_this_round=p.used_this_round | {CARD_ID} if granted else p.used_this_round,
        card_state=p.card_state.set(CARD_ID, frozenset()),  # reset to canonical empty
    )
    return fast_replace(
        state,
        players=tuple(new_p if i == idx else state.players[i] for i in range(2)),
    )


# Occupation: no on-play effect (played via Lessons).
register_occupation(CARD_ID, lambda state, idx: state)
register_auto("before_build_fences", CARD_ID, lambda state, idx: True, _snapshot_before)
register_auto("after_build_fences", CARD_ID, lambda state, idx: True, _grant_after)
