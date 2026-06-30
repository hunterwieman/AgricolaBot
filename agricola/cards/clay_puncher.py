"""Clay Puncher (occupation, A121; Artifex Expansion; players 1+).

Card text: "When you play this card and each time after you use a 'Lessons'
action space or the 'Clay Pit' accumulation space, you get 1 clay."
Clarification: "Gives 1+1=2 clay when played on Lessons."

Category 3 (action-space hook, automatic income) with an additional on-play
grant. Three +1-clay grants, all the SAME effect (`_grant_clay`):

  - On play: the `register_occupation` on-play hook (+1 clay when the card
    enters the tableau).
  - After a Lessons use: Lessons pushes a PendingSubActionSpace host (to play
    an occupation), which shares PENDING_ID "action_space" and reaches
    `_enter_after_phase`, firing `after_action_space`. No hook registration is
    needed — Lessons is already a host frame.
  - After a Clay Pit use: Clay Pit is an ATOMIC space, so it must be explicitly
    hosted (`register_action_space_hook`) to push a PendingActionSpace frame
    whose Proceed flips to the after-phase and fires `after_action_space`.

The clarification "1+1=2 clay when played on Lessons" emerges for free: playing
the card via Lessons runs the on-play grant (+1, card now owned) during the
occupation play, THEN the Lessons host flips to its after-phase and fires
`after_action_space`, whose eligible auto grants +1 more = 2 total. No special
case.

TIMING: the text says "each time AFTER you use" (an explicit "immediately after"
exception to the default "each time you use" = before ruling), so the hook is on
`after_action_space`, NOT `before_action_space`.

Only Clay Pit is hooked (it is atomic); Lessons is NOT hooked because it is
already a PendingSubActionSpace host — hooking it would be redundant and the
hook index governs atomic spaces only.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "clay_puncher"

# Spaces whose AFTER-use grants +1 clay. Clay Pit is the only one needing an
# explicit atomic host; Lessons hosts itself (see module docstring).
CLAY_PUNCHER_SPACES = frozenset({"lessons", "clay_pit"})


def _grant_clay(state: GameState, idx: int) -> GameState:
    """+1 clay to player `idx` (serves both the on-play and after-use grants)."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(clay=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at an after_action_space host frame; read the space uniformly via
    # the host frame's `space_id` (works for the atomic Clay Pit host and the
    # delegating Lessons host alike).
    return state.pending_stack[-1].space_id in CLAY_PUNCHER_SPACES


register_occupation(CARD_ID, _grant_clay)                       # +1 clay on play
register_auto("after_action_space", CARD_ID, _eligible, _grant_clay)
register_action_space_hook(CARD_ID, {"clay_pit"})              # atomic; Lessons self-hosts
