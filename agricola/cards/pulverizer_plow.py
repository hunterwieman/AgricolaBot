"""Pulverizer Plow (minor improvement, D19; Dulcinaria Expansion; cost 2 wood;
prereq 1 occupation).

Card text: "Immediately after each time you use a clay accumulation space, you can
pay 1 clay to plow 1 field. If you do, place that 1 clay on the accumulation space."

Structurally the Field Watchman / Mole Plow template (an OPTIONAL trigger granting a
free PendingPlow), with two twists:

  - TIMING. "Immediately after each time you use" → `after_action_space`, NOT before
    (the explicit "immediately after" exception to the default "each time you use" =
    before ruling; see Clay Puncher). The hook fires once per use, enforced by the
    host's `triggers_resolved`.

  - COST. The plow is not free: it costs 1 clay, and that 1 clay is then PLACED BACK
    on the accumulation space ("place that 1 clay on the accumulation space"). So the
    net effect on the clay_pit's accumulated clay is zero (the player collected it on
    the space's own resolution during Proceed, then immediately hands one clay back),
    while the player is down 1 clay. `_apply` does BOTH the player debit and the
    `with_space` accumulated bump before pushing the plow. (1 clay is a plain supply
    resource — no food-payment machinery is involved.)

The card says "a clay accumulation space" generically; in the 2-player game the only
clay accumulation space is Clay Pit (the quarries accumulate stone, the reed bank
reed). Clay Pit is ATOMIC, so it must be explicitly hosted via
`register_action_space_hook` to push a PendingActionSpace whose after-phase fires
`after_action_space` (Field Watchman / Clay Puncher do the same for atomic spaces).

Optionality is the FireTrigger itself: declining = not firing it (the host's Proceed).
Once fired, the pay-and-plow is mandatory, so eligibility gates on BOTH being possible
— ≥1 clay on hand AND a plowable cell exists (`_can_plow`) — to never offer a dead-end
(CARD_AUTHORING_GUIDE.md §2).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.legality import _can_plow
from agricola.pending import PendingPlow, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "pulverizer_plow"
_SPACE = "clay_pit"


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                        # once per use
        return False
    if state.pending_stack[-1].space_id != _SPACE:
        return False
    p = state.players[idx]
    # Never a dead-end: 1 clay on hand AND a plowable cell must both exist, since once
    # fired the pay-and-plow is mandatory.
    return p.resources.clay >= 1 and _can_plow(p)


def _apply(state: GameState, idx: int) -> GameState:
    """Pay 1 clay (debit the player), place that 1 clay back on the Clay Pit
    accumulation space, then grant the plow."""
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources - Resources(clay=1))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))
    sp = get_space(state.board, _SPACE)
    sp = fast_replace(sp, accumulated=sp.accumulated + Resources(clay=1))
    state = fast_replace(state, board=with_space(state.board, _SPACE, sp))
    return push(state, PendingPlow(player_idx=idx, initiated_by_id=f"card:{CARD_ID}"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=2)), min_occupations=1)
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, {_SPACE})            # clay_pit is atomic; host it
