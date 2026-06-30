"""Food Chest (minor improvement, B59; Bubulcus Expansion; cost 1 wood).

Card text: "If you play this card on the 'Major Improvement' action space, you
immediately get 4 food. Otherwise, you get only 2 food." Printed 0 VP, no
prerequisite, not a passing card.

Category 2 (on-play one-shot gain), with the amount conditioned on WHERE the
card was played:

- played via the **Major Improvement** action space → +4 food,
- played via any other entry point (House Redevelopment, Basic Wish for
  Children, Meeting Place) → +2 food.

The discriminator is a SCAN of the whole pending stack for a frame whose
`initiated_by_id == "space:major_improvement"`, NOT a read of the top frame.
`PendingPlayMinor`'s own `initiated_by_id` is the shared `"major_minor_improvement"`
composite id (also used by the House-Redevelopment improvement path), so keying
off the top frame would mis-classify. The distinguishing value lives further down
the stack: `_initiate_major_improvement` pushes a `PendingSubActionSpace` with
`initiated_by_id="space:major_improvement"` (resolution.py), and the other entry
points push frames tagged `"space:house_redevelopment"` /
`"space:basic_wish_for_children"` / `"space:meeting_place"` instead. The scan reads
the LIVE stack inside `on_play`, which is correct because `_execute_play_minor`
runs `on_play` while the host frames are still on the stack (only `PendingPlayMinor`
has been flipped to its after-phase; the parent space/composite frames remain
below it, and the trailing Stop pops them later).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "food_chest"


def _on_play(state: GameState, idx: int) -> GameState:
    # `getattr(..., None)` because not every pending frame carries `initiated_by_id`
    # (e.g. PendingReveal lacks it).
    via_major = any(
        getattr(f, "initiated_by_id", None) == "space:major_improvement"
        for f in state.pending_stack
    )
    gain = Resources(food=4 if via_major else 2)
    p = fast_replace(state.players[idx], resources=state.players[idx].resources + gain)
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(
    CARD_ID,
    cost=Cost(resources=Resources(wood=1)),
    on_play=_on_play,
)
