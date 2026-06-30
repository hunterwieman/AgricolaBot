"""Clay Kneader (occupation, C121; Consul Dirigens Expansion; players 1+).

Card text: "When you play this card, you immediately get 1 wood and 2 clay.
Each time after you use a 'Grain Seeds' or 'Vegetable Seeds' action space, you
get 1 clay."

Category 3 (action-space hook, automatic income) plus a separate one-time on-play
goods grant. Two distinct effects:

  - On play: a one-time +1 wood +2 clay when the card enters the tableau (the
    `register_occupation` on-play hook). Unlike the recurring grant this is a
    single fixed bundle, so it is its own function (`_grant_on_play`).
  - After a Grain Seeds OR Vegetable Seeds use: +1 clay (`_grant_clay`).

TIMING: the text says "each time AFTER you use" (an explicit "immediately after"
exception to the default "each time you use" = before ruling), so the recurring
hook is on `after_action_space`, NOT `before_action_space`. (Corn Scoop uses
`before_action_space` precisely because ITS text omits "after".) Wrong event would
grant the clay before the seed pickup instead of after.

Both Grain Seeds and Vegetable Seeds are ATOMIC accumulation spaces, so each must
be explicitly hosted (`register_action_space_hook`) to push a PendingActionSpace
frame whose Proceed flips to the after-phase and fires `after_action_space`.
Without the host they would stay on the atomic fast path and never reach the
after-phase.

The grant is choiceless income with no downside, so it is a mandatory automatic
effect (`register_auto`), not a declinable trigger.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "clay_kneader"

# The AFTER-use spaces that grant +1 clay. Both are atomic, so both need an
# explicit host (see module docstring).
CLAY_KNEADER_SPACES = frozenset({"grain_seeds", "vegetable_seeds"})


def _grant_on_play(state: GameState, idx: int) -> GameState:
    """One-time +1 wood +2 clay when the card is played."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1, clay=2))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _grant_clay(state: GameState, idx: int) -> GameState:
    """+1 clay to player `idx` (the recurring after-use grant)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(clay=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at an after_action_space host frame; read the space uniformly via
    # the host frame's `space_id`.
    return state.pending_stack[-1].space_id in CLAY_KNEADER_SPACES


register_occupation(CARD_ID, _grant_on_play)                  # +1 wood +2 clay on play
register_auto("after_action_space", CARD_ID, _eligible, _grant_clay)
register_action_space_hook(CARD_ID, {"grain_seeds", "vegetable_seeds"})  # both atomic
