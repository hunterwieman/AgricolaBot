"""Bread Paddle (minor improvement, B25; Base Revised; cost 1 wood).

Card text: "When you play this card, you immediately get 1 food. For each
occupation you play, you get an additional 'Bake Bread' action." Printed 0 VP.

Category 5 (play-occupation hook, granted sub-action) + an on-play one-shot gain:

- **on_play** → +1 food (Category 2 shape).
- **each occupation played** → an OPTIONAL trigger (register) on
  `after_play_occupation` whose apply_fn pushes the existing PendingBakeBread
  primitive. Eligibility gates on a bake actually being usable (`_can_bake_bread`:
  a baking improvement + grain, or a card extension), so it never grants a
  dead-end. Mirrors Oven Firing Boy / Threshing Board (after-trigger that grants a
  primitive). The play-occupation host pivots to its after-phase after the
  occupation is played (the SUBACTION_HOOK_REFACTOR uniform host), so the trigger
  surfaces there.

See CARD_IMPLEMENTATION_PLAN.md Category 5.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_bake_bread
from agricola.pending import PendingBakeBread, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "bread_paddle"


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and _can_bake_bread(state, state.players[idx]))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingBakeBread(player_idx=idx, initiated_by_id="card:bread_paddle"))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play)
register("after_play_occupation", CARD_ID, _eligible, _apply)
