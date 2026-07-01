"""Mining Hammer (minor improvement, B16; Base Revised; cost 1 wood).

Card text: "When you play this card, you immediately get 1 food. Each time you
renovate, you can also build a stable without paying wood." Printed 0 VP.

Category 5 (renovate hook, granted sub-action) + an on-play one-shot gain:

- **on_play** → +1 food (Category 2 shape).
- **each renovate** → an OPTIONAL trigger (register, not register_auto — a grant
  is the player's choice and pushes a primitive) on `before_renovate` whose apply_fn
  pushes the existing PendingBuildStables primitive with a FREE cost (Resources())
  and a cap of 1 build. Eligibility gates on a free stable actually being buildable
  (`_can_build_stable` with the zero cost), so it never grants a dead-end.

Why `before_renovate` (not after): the text is a bare "each time you renovate" with
a FLAT grant — a free stable whose legality depends only on an empty farmyard cell
and a stable in supply, neither of which the renovate produces or changes. It reads
nothing about the renovate's chosen target or outcome. Per the ruling in
CARD_AUTHORING_GUIDE.md ("Each time you [do X]" fires BEFORE X unless the text says
"after"/"immediately after"), a flat "each time you [do X]" fires in the BEFORE
window of X. There is no "after" here, so it hooks the before-phase of
PendingRenovate — the free-stable trigger is offered alongside the CommitRenovate
options, before the renovate commits.

No stranding is possible, so no stranding guard is needed. The granted free stable
consumes a farmyard cell + a stable from supply (see `_can_build_stable`); the
mandatory renovate consumes only building resources (to CLAY: clay + reed; to STONE:
stone + reed — see `_execute_renovate` / the renovate cost path in legality.py).
These resource sets are disjoint, so firing the stable grant in the before-window
can never deprive the renovate of a resource it needs; the renovate is still forced
after (the before-phase offers FireTrigger + CommitRenovate, no Stop).

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
            and _can_build_stable(state, state.players[idx], _FREE))


def _apply(state: GameState, idx: int) -> GameState:
    return push(state, PendingBuildStables(
        player_idx=idx, initiated_by_id="card:mining_hammer",
        cost=_FREE, max_builds=1,
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)), on_play=_on_play)
register("before_renovate", CARD_ID, _eligible, _apply)
