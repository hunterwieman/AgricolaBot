"""Small Trader (occupation, A109; Artifex Expansion; players 1+).

Card text: "Each time you take a 'Major or Minor Improvement' action to play an
improvement from your hand, you also get 3 food."

Clarification: "Does not work unless you literally get that action."

Category 5 (income on a parent action). No on-play effect. A mandatory,
choice-free grant -> an automatic effect (`register_auto`) on the composite
"build a major OR play a minor" host's after-event, `after_major_minor_improvement`.

USER RULING (2026-07-15 — the "action, not action space" distinction; RULES.md
Primitive Sub-Actions, CARD_ENGINE_IMPLEMENTATION.md §6): Small Trader keys off
the **'Major or Minor Improvement' action** — the primitive sub-action (build a
major from the board OR play a minor from hand) — NOT the Major Improvement
action *space*. That primitive is offered by the Major Improvement space, by
House Redevelopment's optional step, and by card effects (Angler; a
Merchant-granted repeat — so with Merchant it can fire twice). It is a DIFFERENT
primitive from the **'Minor Improvement' action** (play a minor only), which
Meeting Place and Basic Wish for Children offer — so Small Trader never fires
there. The clarification "does not work unless you literally get that action"
means you must actually TAKE the action and play the minor (it doesn't fire on a
decline), not that only the physical space counts.

So the engine gate is simply the composite host's after-event + `minor_chosen`:

  - The event `after_major_minor_improvement` fires ONLY from
    `PendingMajorMinorImprovement` (the 'Major or Minor Improvement' action) —
    the Major Improvement space, House Redevelopment, and card grants all reach
    it; Meeting Place / Basic Wish push a BARE `PendingPlayMinor` (the 'Minor
    Improvement' action) and fire `after_play_minor` instead, which we do not
    hook. So no `initiated_by_id` space check is needed (the prior "space only"
    gate was wrong — un-ratified, corrected by this ruling).
  - `minor_chosen` (not `major_chosen`) — "play an improvement from your hand" =
    a MINOR (majors come from the common board, not your hand), so building a
    major at the space gives no food.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "small_trader"


def _eligible(state: GameState, idx: int) -> bool:
    # The after_major_minor_improvement event already scopes to the composite
    # 'Major or Minor Improvement' action (any entry point); a minor was played
    # iff `minor_chosen`. No space gate (ruling 2026-07-15).
    return getattr(state.pending_stack[-1], "minor_chosen", False)


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(food=3))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)  # no on-play effect
register_auto("after_major_minor_improvement", CARD_ID, _eligible, _apply)
