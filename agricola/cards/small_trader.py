"""Small Trader (occupation, A109; Artifex Expansion; players 1+).

Card text: "Each time you take a 'Major or Minor Improvement' action to play an
improvement from your hand, you also get 3 food."

Clarification: "Does not work unless you literally get that action."

Category 5 (income on a parent action). No on-play effect. A mandatory,
choice-free grant -> an automatic effect (`register_auto`) on the composite
"build a major OR play a minor" host's after-event, `after_major_minor_improvement`.

The clarification is load-bearing: the +3 food only applies when you LITERALLY
take the Major or Minor Improvement *action space* and play a minor (an
"improvement from your hand"), never via a card-granted route to playing a minor
(House Redevelopment's improvement step, Basic Wish for Children, Meeting Place).
Two gates on the still-top parent frame (`PendingMajorMinorImprovement`, now in
its "after" phase) express that exactly:

  1. `initiated_by_id == "space:major_improvement"` — the host was reached via the
     Major Improvement action space, NOT House Redevelopment ("house_redevelopment").
     This is the only signal that distinguishes the two entry points
     (`PendingPlayMinor.initiated_by_id` is "major_minor_improvement" for both), and
     it is why we fire on the PARENT's after-event rather than `after_play_minor`
     (which fires on EVERY minor play, including House Redev / Basic Wish / Meeting
     Place).
  2. `minor_chosen` (not `major_chosen`) — "play an improvement from your hand" = a
     MINOR (majors come from the common board, not your hand), so building a major
     at that space gives no food.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "small_trader"


def _eligible(state: GameState, idx: int) -> bool:
    top = state.pending_stack[-1]
    return (
        getattr(top, "initiated_by_id", "") == "space:major_improvement"
        and getattr(top, "minor_chosen", False)
    )


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=3))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)  # no on-play effect
register_auto("after_major_minor_improvement", CARD_ID, _eligible, _apply)
