"""Threshing Board (minor improvement, A24; Base Revised; cost 1 wood,
prereq 2 occupations, 1 VP).

Card text: "Each time you use the 'Farmland' or 'Cultivation' action space, you get
an additional 'Bake Bread' action."

Category 4 (action-space hook, granted sub-action) on the **after** event — an
OPTIONAL trigger whose apply_fn pushes the existing PendingBakeBread primitive.
Eligibility gates on a bake being usable (`_can_bake_bread`), so it never grants
a dead-end. Both spaces are non-atomic (always hosted), so no host-index entry is
needed. Firing it records Threshing Board in the host frame's triggers_resolved,
from which `_after_action_space_fired` derives that the base sub-actions are now
closed (no plow/sow after the bake — the rules ordering). See
CARD_IMPLEMENTATION_PLAN.md Category 4.
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
register("after_action_space", CARD_ID, _eligible, _apply)
