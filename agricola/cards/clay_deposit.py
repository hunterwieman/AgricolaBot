"""Clay Deposit (minor improvement, C36; Corbarius Expansion; cost 2 food).

Card text: "Immediately after each time you use a clay accumulation space, you can
exchange 1 clay for 1 bonus point. If you do, place the clay on the accumulation
space."
Prerequisite: "1 Occupation" (you must have at least 1 occupation in play).
Printed 0 VP (the bonus point is earned per exchange, not a flat printed score).

A "Points Provider" card — the same shape as Basket (an OPTIONAL after-action
trigger that converts a resource and returns the spent good to the accumulation
space) fused with Baking Sheet (bank a bonus point in CardStore + register_scoring):

- **each clay accumulation space use** → an OPTIONAL trigger (`register`, not
  `register_auto` — the text says "you CAN exchange", so the player chooses) on
  the clay space host's AFTER-phase (`after_action_space`). Clay Pit is the only
  clay accumulation space in scope; it is ATOMIC, so it is explicitly hosted via
  `register_action_space_hook` (its Proceed flips to the after-phase and fires
  `after_action_space`).
- when fired it pays exactly 1 clay and BANKS 1 bonus point in the per-card
  CardStore, then RETURNS the spent clay to the accumulation space's accumulated
  goods ("place the clay on the accumulation space" — net: the player loses 1 clay
  and gains 1 VP; the clay sits back on the space for the next taker).
- **the bonus point** → BANKED in CardStore and read at scoring
  (`register_scoring`): a use-count-dependent quantity, so a flat `vps=` on the
  minor spec would wrongly award it without ever exchanging.

TIMING: the text says "Immediately AFTER each time you use" (an explicit
"immediately after" exception to the default "each time you use" = before ruling),
so the hook is on `after_action_space`, NOT `before_action_space`.

Once per clay-space action is automatic: `_apply_fire_trigger` stamps
`triggers_resolved` before applying, and `_eligible` reads it (each new clay-space
use gets a fresh host frame with an empty `triggers_resolved`, so the card
re-becomes eligible per action — "each time you use a clay accumulation space").
The point (a CardStore bank) and the returned clay (the space's accumulated bank)
are always accommodatable, so firing never dead-ends.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.scoring import register_scoring
from agricola.state import GameState, get_space, with_space

CARD_ID = "clay_deposit"

# Clay accumulation spaces whose AFTER-use offers the exchange. Clay Pit is the
# only clay accumulation space in scope; it is atomic, so it must be explicitly
# hosted (register_action_space_hook) to reach an after_action_space phase.
CLAY_SPACES = frozenset({"clay_pit"})

_CLAY_IN = 1


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    # Optional, once per clay-space action, only when 1 clay is available to
    # exchange.
    if CARD_ID in triggers_resolved:
        return False
    top = state.pending_stack[-1]
    return top.space_id in CLAY_SPACES and state.players[idx].resources.clay >= _CLAY_IN


def _apply(state: GameState, idx: int) -> GameState:
    space_id = state.pending_stack[-1].space_id
    p = state.players[idx]
    # Pay 1 clay; bank 1 bonus point in the per-card CardStore.
    p = fast_replace(
        p,
        resources=p.resources + Resources(clay=-_CLAY_IN),
        card_state=p.card_state.set(CARD_ID, p.card_state.get(CARD_ID, 0) + 1),
    )
    state = fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )
    # "place the clay on the accumulation space" — return the spent clay to the
    # space's accumulated goods.
    sp = get_space(state.board, space_id)
    sp = fast_replace(sp, accumulated=sp.accumulated + Resources(clay=_CLAY_IN))
    return fast_replace(state, board=with_space(state.board, space_id, sp))


def _score(state: GameState, idx: int) -> int:
    # The banked bonus points (1 per fired exchange).
    return state.players[idx].card_state.get(CARD_ID, 0)


register_minor(CARD_ID, cost=Cost(resources=Resources(food=2)), min_occupations=1)
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, CLAY_SPACES)
register_scoring(CARD_ID, _score)
