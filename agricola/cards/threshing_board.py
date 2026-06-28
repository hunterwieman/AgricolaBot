"""Threshing Board (minor improvement, A24; Base Revised; cost 1 wood,
prereq 2 occupations, 1 VP).

Card text: "Each time you use the 'Farmland' or 'Cultivation' action space, you get
an additional 'Bake Bread' action."

Category 4 (action-space hook, granted sub-action) on the **before** event — an
OPTIONAL trigger whose apply_fn pushes the existing PendingBakeBread primitive.
"Each time you use [space]" fires before the space's own effect (the Trigger-Timing
ruling), so the bake is offered together with the space's base plow/sow (and any
other "use Farmland" grant, e.g. Moldboard Plow), takeable in either order.
Eligibility gates on a bake being usable (`_can_bake_bread`), so it never grants a
dead-end. Both spaces are non-atomic (always hosted): Cultivation is a Proceed-host
(before-triggers coexist with plow/sow until Proceed) and Farmland a delegating host
(the engine holds its post-plow auto-advance while this grant is eligible, so it is
never dropped). See CARD_IMPLEMENTATION_PLAN.md Category 4.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_bake_bread
from agricola.pending import PendingBakeBread, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "threshing_board"
SPACES = frozenset({"farmland", "cultivation"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and state.pending_stack[-1].space_id in SPACES
            and _can_bake_bread(state, state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingBakeBread(player_idx=idx, initiated_by_id="card:threshing_board"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)),
               min_occupations=2, vps=1)
register("before_action_space", CARD_ID, _eligible, _apply)
