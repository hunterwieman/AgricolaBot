"""Sowing Master (occupation, D109; Dulcinaria Expansion; players 1+).

Card text: "When you play this card, you immediately get 1 wood. Each time
after you use an action space with the \"Sow\" action, you get 2 food."

USER RULING (2026-07-14): "yes the text is equivalent to saying, 'each time
after you use the Grain Utilization or Cultivation action spaces' (although if
an expansion card created a new action space that provides a sow, then it would
no longer be equivalent)". So the +2 food fires on ANY use of Grain Utilization
or Cultivation — whether or not the player actually took the Sow sub-action
(the space merely has to OFFER it) — and `SOW_SPACES` below must be revisited
if a future card ever creates a new sow-bearing action space.

Two distinct effects:

  - On play: a one-time +1 wood when the card enters the tableau (the
    `register_occupation` on-play hook).
  - Each time AFTER the owner uses Grain Utilization or Cultivation: +2 food.

TIMING: the text says "each time AFTER you use" (an explicit "after" exception
to the default "each time you use" = before ruling), so the recurring grant
rides `after_action_space`, NOT `before_action_space`. Both spaces are
non-atomic Proceed-hosts (and/or spaces) — already hosted, so there is NO
`register_action_space_hook` call (that is only for atomic spaces); the
eligibility just filters the host frame's `space_id`. The host flips to its
after-phase on the player's `Proceed` (the "use is done" boundary — every legal
use of these spaces passes through it, since placement requires at least one
sub-action and `Proceed` is the only exit from the before-phase), which is when
the auto fires. The grant is flat (reads nothing of what the use produced), so
the deferred after-flip (ruling 60) changes nothing for it.

The grant is choiceless income with no downside, so it is a mandatory automatic
effect (`register_auto`), not a declinable trigger. Fires once per host flip
(one flip per use), so no `triggers_resolved` guard is needed. Owner-gated
(`any_player=False` default): an opponent's use of the spaces grants nothing.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "sowing_master"

# The action spaces that carry the "Sow" action in this engine (user ruling
# 2026-07-14, quoted in the module docstring). Revisit if a future card
# creates a new sow-bearing action space.
SOW_SPACES = frozenset({"grain_utilization", "cultivation"})


def _grant_on_play(state: GameState, idx: int) -> GameState:
    """One-time +1 wood when the card is played."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int) -> bool:
    # Consulted at the after_action_space host flip; the top frame is the host,
    # so `space_id` names the space just used.
    return state.pending_stack[-1].space_id in SOW_SPACES


def _grant_food(state: GameState, idx: int) -> GameState:
    """+2 food to player `idx` (the recurring after-use grant)."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=2))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, _grant_on_play)                  # +1 wood on play
register_auto("after_action_space", CARD_ID, _eligible, _grant_food)
# No register_action_space_hook: Grain Utilization and Cultivation are
# non-atomic Proceed-hosts, already hosted for every use.
