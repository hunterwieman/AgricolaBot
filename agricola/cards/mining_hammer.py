"""Mining Hammer (minor improvement, B16; Base Revised; cost 1 wood).

Card text: "When you play this card, you immediately get 1 food. Each time you
renovate, you can also build a stable without paying wood." Printed 0 VP.

Category 5 (renovate hook, granted sub-action) + an on-play one-shot gain:

- **on_play** → +1 food (Category 2 shape).
- **each renovate** → an OPTIONAL trigger (register, not register_auto — a grant
  is the player's choice and pushes a primitive) on `after_renovate` whose apply_fn
  pushes the existing PendingBuildStables primitive with a FREE cost (Resources())
  and a cap of 1 build. Eligibility gates on a free stable actually being buildable
  (`_can_build_stable` with the zero cost), so it never grants a dead-end. Mirrors
  Threshing Board / Assistant Tiller (after-trigger that grants a primitive).

See CARD_IMPLEMENTATION_PLAN.md Category 5.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_build_stable
from agricola.pending import PendingBuildStables, push
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "mining_hammer"
_FREE = Resources()


def _on_play(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(
        state, players=tuple(p if i == idx else state.players[i] for i in range(2))
    )


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    return (CARD_ID not in triggers_resolved
            and _can_build_stable(state.players[idx], _FREE))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingBuildStables(
        player_idx=idx, initiated_by_id="card:mining_hammer",
        cost=_FREE, max_builds=1,
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play)
register("after_renovate", CARD_ID, _eligible, _apply)
