"""Second Spouse (occupation, C129; Corbarius Expansion; players 3+).

Card text: "You can use the \"Urgent Wish for Children\" action space (from round 12-13)
even if it is occupied by the first person another player placed."
Clarification: "But not if any second, third, etc. people occupy it."

One mechanism — a LEGALITY RELAXATION on worker placement, identical in shape to Sleeping
Corner but scoped to a SINGLE space: the owner may place on the "Urgent Wish for Children"
space even when an opponent already holds it. Registered via `register_occupancy_override`,
which `_is_available` consults ONLY on the occupied branch — so the unoccupied path and the
entire Family game pay nothing.

Three load-bearing points:

- SCOPED TO THE URGENT SPACE ONLY. The card text names only "Urgent Wish for Children"
  (unlike Sleeping Corner, which covers BOTH wish spaces), so the override returns False for
  every other space, including `basic_wish_for_children`.

- COUNT PLAYERS, NOT WORKERS. A normally-used urgent-wish space already holds TWO of one
  player's workers — the parent placed by the action plus the newborn the action generates
  (`_resolve_wish_for_children`). So the clarification "not if any second, third, etc. people
  occupy it" means "exactly one OTHER PLAYER has a worker here," not "exactly one worker." The
  override requires `others_with_workers == 1`, tolerating that one player's parent+newborn
  pair. The `workers[ap] != 0` self-check also stops the owner re-using a space they hold.

- The "from round 12-13" phrasing is purely descriptive of the space's stage-5 reveal timing
  — `_is_available` short-circuits on `not sp.revealed`, so the override is only ever consulted
  once the urgent-wish space exists. It is NOT a separate round-gate to enforce.

A pure occupancy relaxer played via Lessons: no cost / prereq / VPs, and its on-play effect is
a no-op. The override registry is empty in the Family game, so the Family game is byte-identical
and the C++ differential gates are untouched. See CARD_AUTHORING_GUIDE.md.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.legality import register_occupancy_override
from agricola.state import GameState, get_space

CARD_ID = "second_spouse"
TARGET_SPACE = "urgent_wish_for_children"


def _occupancy_override(state: GameState, space_id: str) -> bool:
    """The current player may place on the occupied "Urgent Wish for Children" space iff they
    own Second Spouse, hold no worker there themselves, and exactly one OTHER player does
    (count players, not workers)."""
    if space_id != TARGET_SPACE:
        return False
    ap = state.current_player
    if CARD_ID not in state.players[ap].occupations:
        return False
    workers = get_space(state.board, space_id).workers
    if workers[ap] != 0:
        return False
    others_with_workers = sum(1 for i, w in enumerate(workers) if i != ap and w > 0)
    return others_with_workers == 1


# Pure occupancy-relaxer occupation: played via Lessons, but its on-play effect is a no-op.
register_occupation(CARD_ID, lambda state, idx: state)
register_occupancy_override(_occupancy_override)
