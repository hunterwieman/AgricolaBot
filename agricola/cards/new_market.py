"""New Market (minor improvement, D55; Dulcinaria Expansion; cost 1 wood, 1 clay).

Card text: "Each time you use an action space card on round spaces 8 to 11, you get
1 additional food."
Cost: 1 Wood, 1 Clay. Prerequisite: none. VPs: 1. Not passing.

Category 3 (action-space hook, automatic effect). "Round spaces 8 to 11" are the
action-space cards revealed for game rounds 8–11. Those rounds map onto stages 3
and 4 (rounds 8–9 = stage 3, rounds 10–11 = stage 4; see constants.STAGE_OF_ROUND),
so the set of cards that can ever occupy those slots is exactly the union of stage 3
and stage 4: vegetable_seeds + pig_market (stage 3) and cattle_market + eastern_quarry
(stage 4). The within-stage reveal order is hidden per game, but the UNION is fixed and
public — so this card needs no hidden-information dependence: it fires on any of those
four spaces whenever the owner uses it, regardless of which round each happened to be
revealed in.

"Each time you use [a space]" = the before_action_space host phase (the project's
ruling that this timing resolves BEFORE the space's own action). any_player=False —
the card says "you", not "any player" (contrast Milk Jug). The food grant is
timing-neutral here (it only touches the owner's food), but before_action_space is the
host phase that also hosts the two ATOMIC members of the set.

register_action_space_hook is REQUIRED: vegetable_seeds and eastern_quarry are atomic
accumulation spaces (no host frame by default), so without the hook the
before_action_space auto would never fire on them. pig_market and cattle_market are
non-atomic and already host a frame — the hook is harmless (idempotent index entry)
for them.

Implemented as an automatic effect (register_auto, never a FireTrigger): a
guaranteed-beneficial +1 food with no choice or downside.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "new_market"

# Round slots 8–11 = stage 3 (rounds 8–9) + stage 4 (rounds 10–11). The four
# action-space cards that fill those slots, regardless of the hidden per-game order.
NEW_MARKET_SPACES = frozenset(
    {"vegetable_seeds", "pig_market", "cattle_market", "eastern_quarry"}
)


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in NEW_MARKET_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    """Grant the owner +1 food."""
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, clay=1)), vps=1)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, NEW_MARKET_SPACES)
