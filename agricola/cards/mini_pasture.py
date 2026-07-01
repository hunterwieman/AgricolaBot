"""Mini Pasture (minor improvement, B2; Base Revised; players -).

Card text: "Immediately fence a farmyard space, without paying wood for the fences. (If you
already have pastures, the new one must be adjacent to an existing one.)"
Cost: 2 Food. This is a TRAVELING (passing) minor (`passing_left="X"` in the card data): after
its immediate effect it is passed to the opponent's hand, never kept in the owner's tableau.
Owner ruling (2026-06-29): a NEW 1×1 enclosure, adjacent to an existing pasture (if any),
NEVER a subdivision; and the grant is MANDATORY — the card is UNPLAYABLE unless a valid free
1×1 can actually be built (enough fence pieces in supply AND a legal location: a first pasture,
or an empty space adjacent to an existing pasture).

A restricted, free, MANDATORY grant (COST_MODIFIER_DESIGN.md §9.8):
- on_play pushes a `PendingBuildFences` directly (after the play host flips to its after-phase,
  the Shifting-Cultivation nesting), carrying `FenceRestrictions(exact_size=1,
  forbid_subdivision=True, max_pastures=1)` so the enumerator offers only NEW 1×1 enclosures and
  exactly one — the player must commit it (no decline; "Immediately fence"). "Adjacent to an
  existing one" needs no flag: `_check_entry_legal`'s adjacency rule already forces a
  non-subdivision new pasture to touch an existing one when any exist.
- "Without paying wood" → `free_fence_budget=4` (a 1×1 is at most 4 new edges, so the per-action
  free budget covers the whole grant). The fence PIECES still come from supply ("you still use
  your fence pieces" — the general rule), so the build needs `buildable_fences >= the edges`.
- `build_fences_action=False` — a card effect, not the literal action, so action-scoped frees
  (Hedge Keeper, Hunting Trophy) do NOT fire on it (per Hedge Keeper's clarification).
- The MANDATORY-playability gate is the card's `prereq`: a free 1×1 new-enclosure must be
  legal (the same `_any_legal_pasture_commit` check the grant will satisfy), so the card is
  never offered when it couldn't be resolved.

Cost 2 food (play-minor path). Cards-only (restrictions are an unrestricted-default skip-field);
Family byte-identical, C++ gates untouched. See COST_MODIFIER_DESIGN.md §9.8.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.pending import FenceRestrictions, PendingBuildFences, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "mini_pasture"
FRAME_ID = "card:mini_pasture"
_RESTRICTIONS = FenceRestrictions(exact_size=1, forbid_subdivision=True, max_pastures=1)
_FREE = 4   # a 1×1 is <= 4 new edges, so this per-action budget covers the whole (free) grant


def _can_fence_new_1x1(state: GameState, idx: int) -> bool:
    """Playability: a free 1×1 NEW enclosure is buildable (enough fence pieces + a legal
    location). Anticipates the grant exactly (same restrictions / free budget / provenance)."""
    from agricola.legality import _any_legal_pasture_commit
    return _any_legal_pasture_commit(
        state, state.players[idx],
        restrictions=_RESTRICTIONS, free_budget=_FREE,
        space_id=FRAME_ID, initiated_by_id=FRAME_ID, build_fences_action=False)


def _on_play(state: GameState, idx: int) -> GameState:
    return push(state, PendingBuildFences(
        player_idx=idx, initiated_by_id=FRAME_ID,
        free_fence_budget=_FREE, build_fences_action=False,
        restrictions=_RESTRICTIONS))


register_minor(CARD_ID, cost=Cost(resources=Resources(food=2)),
               passing_left=True, prereq=_can_fence_new_1x1, on_play=_on_play)
