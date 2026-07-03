"""Shepherd's Crook (minor improvement, A83; Base Revised; players 1+).

Card text: "Each time you fence a new pasture covering at least 4 farmyard
spaces, you immediately get 2 sheep on this pasture."

Rulings (confirmed with the maintainer): the pasture must lie entirely on
*newly-enclosed* farmyard spaces (extending or subdividing an existing pasture
does not qualify), and "covering at least 4 farmyard spaces" means size >= 4.
Each qualifying pasture grants 2 sheep, so building two such pastures in one
action gives 4 sheep. If you fence a new 6-space area and split it into a 4 and a
2 in the SAME action, the undivided 4-space piece still grants (the 2 does not) —
which is exactly why the grant is computed ONCE at the end of the fencing action
by comparing the pasture decomposition before vs after, not incrementally per
pasture commit.

Mechanism — a before/after pair of AUTOMATIC effects on the build_fences
sub-action host (made a uniform before/after host for this card; see
SUBACTION_HOOK_REFACTOR.md). The grant is mandatory and parameter-free (the new
>= 4-space pasture has capacity >= 8 and is empty, so the 2 sheep always fit on
it — no accommodation decision), hence `register_auto`, not a FireTrigger:

  - `before_build_fences` (fires when PendingBuildFences is pushed, before any
    pasture commit): snapshot the set of currently-enclosed cells into the
    per-card CardStore.
  - `after_build_fences` (fires at the Proceed work-complete flip, after all
    commits): a pasture in the after-decomposition qualifies iff every one of its
    cells was newly enclosed during this action (`cells <= newly_enclosed`) AND it
    spans >= 4 cells. Grant 2 sheep per qualifying pasture, then reset the snapshot
    to a canonical empty value (so two commit orders reaching the same farmyard
    converge to the same state).

This fires identically whether fencing is reached via the Fencing action space or
Farm Redevelopment ("Overhaul"), since both push PendingBuildFences. Card-only
state (the CardStore snapshot) defaults empty, so the Family game is byte-identical
and the C++ gates are untouched. See CARD_AUTHORING_GUIDE.md §4 (deferred
snapshot / CardStore) and CARD_IMPLEMENTATION_PLAN.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.helpers import grant_animals
from agricola.replace import fast_replace
from agricola.resources import Animals, Cost, Resources
from agricola.state import GameState

# The card id is the slug of the printed name, per the project convention that
# `_card_slug(json_name) == card_id` (so the web UI joins this card to its
# data-file name + effect text). `_card_slug` drops apostrophes, so
# "Shepherd's Crook" -> "shepherds_crook".
CARD_ID = "shepherds_crook"

MIN_PASTURE_SIZE = 4   # "covering at least 4 farmyard spaces"
SHEEP_PER_PASTURE = 2


def _enclosed_cells(player) -> frozenset:
    """The set of cells the player has enclosed in a pasture (the union over the
    pasture decomposition). Empty before any fences are built."""
    return frozenset(
        cell for pasture in player.farmyard.pastures for cell in pasture.cells
    )


def _snapshot_before(state: GameState, idx: int) -> GameState:
    """before_build_fences: record the pre-action enclosed cells so the after-hook
    can tell which pastures are genuinely new."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, _enclosed_cells(p)))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _grant_after(state: GameState, idx: int) -> GameState:
    """after_build_fences: grant 2 sheep per new, undivided, >= 4-space pasture."""
    p = state.players[idx]
    before = p.card_state.get(CARD_ID, None)
    if before is None:
        # Defensive: no snapshot was taken (cannot happen — before_build_fences
        # always fires at the push). Grant nothing rather than risk over-granting.
        return state
    newly_enclosed = _enclosed_cells(p) - before
    qualifying = sum(
        1
        for pasture in p.farmyard.pastures
        if len(pasture.cells) >= MIN_PASTURE_SIZE
        and frozenset(pasture.cells) <= newly_enclosed
    )
    # Reset the snapshot to canonical empty (so two commit orders converge).
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, frozenset()))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2)),
    )
    # Grant the sheep via grant_animals (add + flag). The 2 sheep land on the fresh
    # >= 4-space pasture (capacity >= 8, empty), so they always fit and the accommodation
    # barrier just clears the flag — but routing every animal grant through grant_animals
    # keeps the path uniform and robust to unusual capacity interactions.
    if qualifying:
        state = grant_animals(state, idx, Animals(sheep=SHEEP_PER_PASTURE * qualifying))
    return state


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register_auto("before_build_fences", CARD_ID, lambda state, idx: True, _snapshot_before)
register_auto("after_build_fences", CARD_ID, lambda state, idx: True, _grant_after)
