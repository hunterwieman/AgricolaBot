"""Moldboard Plow (minor improvement, B19; Base Revised; cost 2 wood, prereq
1 occupation).

Card text: "Place 2 field tiles on this card. Twice this game, when you use the
'Farmland' action space, you can also plow 1 field from this card."

Category 4 (action-space hook, granted sub-action), but bounded to TWICE PER GAME
rather than once-per-use. The "2 field tiles on this card" is modeled as a
uses-left counter (starting at 2) stored in the per-card CardStore (II.7); each
granted plow decrements it, and the grant is no longer offered once it hits 0.

Mechanically an OPTIONAL trigger (register, not register_auto) on Farmland's
BEFORE-phase whose apply_fn pushes the existing PendingPlow primitive — mirrors
Assistant Tiller / Threshing Board. "When you use [space]" fires before the space's
own effect (the Trigger-Timing ruling), so the card plow is offered together with
the base Farmland plow, takeable in either order. Farmland is always hosted
(non-atomic, pushes PendingSubActionSpace, a delegating host); the engine holds that
host's post-plow auto-advance while this grant is eligible, so it is never dropped.
No register_action_space_hook is needed. Eligibility gates on uses-left > 0, the
card not already fired THIS frame (triggers_resolved), and a plow actually being
possible (_can_plow) — so it never grants a dead-end and never exceeds twice per
game. The uses-left decrement happens in apply_fn, so each fire across two separate
Farmland turns consumes one use. See CARD_IMPLEMENTATION_PLAN.md Category 4 / II.7.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_plow_twice
from agricola.pending import PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "moldboard_plow"
SPACES = frozenset({"farmland"})
_INITIAL_USES = 2


def _uses_left(state: GameState, idx: int) -> int:
    return state.players[idx].card_state.get(CARD_ID, _INITIAL_USES)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Enforce-first before-trigger on Farmland: require TWO sequential plows so firing
    # this grant cannot strand the mandatory base plow (CARD_AUTHORING_GUIDE.md) — e.g.
    # with only one empty space left, the grant is not offered.
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in SPACES
            and _uses_left(state, idx) > 0
            and _can_plow_twice(state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    # Spend one of the two lifetime uses, then push the plow primitive on top of
    # the Farmland host. The PendingPlow resolves via the normal CommitPlow path.
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, _uses_left(state, idx) - 1))
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    return push(state, PendingPlow(player_idx=idx, initiated_by_id="card:moldboard_plow"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), min_occupations=1)
register("before_action_space", CARD_ID, _eligible, _apply)
