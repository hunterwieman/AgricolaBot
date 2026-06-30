"""Carpenter's Axe (minor improvement, A15; Artifex Expansion).

Card text: "Each time after you use a wood accumulation space, if you then have at
least 7 wood in your supply, you can build exactly 1 stable for 1 wood."
Cost: 1 Wood. No prerequisite. No VPs. Not passing.

An OPTIONAL `after_action_space` trigger on the wood accumulation space (Forest is
the only one on the 2-player board). The text's "after you use" is the explicit
"immediately after" exception to the default "each time you use [space]" = before
ruling — confirmed by Wood Cutter / Clay Puncher — so it rides `after_action_space`,
firing only once the space's own pickup (Forest's +3 wood) has already happened.
That ordering matters: the "≥ 7 wood" test is a HAVE-check on the POST-pickup supply
(engine.py runs ATOMIC_HANDLERS["forest"] first, then `_enter_after_phase` flips to
the after-phase where eligibility is evaluated), so a player who held 4 wood and
picked up 3 now reads 7 and qualifies. The ≥ 7 is not consumed; it is purely a
threshold gate.

Forest is an ATOMIC space, so it must be explicitly hosted
(`register_action_space_hook`) to push a PendingActionSpace frame whose Proceed flips
to the after-phase and surfaces this trigger; the same wiring Wood Cutter / Clay
Puncher use for atomic wood/clay spaces.

OPTIONALITY: "you can build" → an OPTIONAL FireTrigger (`register`, not
`register_auto`). The decline path IS not firing the trigger — the host's Proceed/Stop
exits without building. Once fired, building exactly 1 stable for 1 wood is the granted
(now-mandatory) sub-action, so eligibility gates on it being possible — a stable cell +
a supply stable + 1 wood affordable (`_can_build_stable`) — to never offer a dead-end
fire. The stable's 1-wood cost is separate from and additional to the ≥ 7 have-check.

"Each time" = once per use, enforced by `CARD_ID not in triggers_resolved` (NOT
used_this_round — it may fire on every Forest use), exactly as Ox Goad. The pushed
PendingBuildStables(max_builds=1) saturates after the single commit. No on-play effect.
"""
from __future__ import annotations

from agricola.legality import _can_build_stable
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_action_space_hook
from agricola.pending import PendingBuildStables, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "carpenters_axe"
_STABLE_COST = Resources(wood=1)
_WOOD_THRESHOLD = 7

# Wood accumulation spaces this card fires on. 2-player: Forest only (Copse /
# Grove are 3–4-player board-extension spaces, never on the 2-player board).
WOOD_SPACES = frozenset({"forest"})


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if state.pending_stack[-1].space_id not in WOOD_SPACES:
        return False
    p = state.players[idx]
    # ≥ 7 wood AFTER the pickup (have-check), AND a stable for 1 wood actually
    # buildable now (cell + supply + affordability) — never a dead-end fire.
    return (
        p.resources.wood >= _WOOD_THRESHOLD
        and _can_build_stable(state, p, _STABLE_COST)
    )


def _apply(state: GameState, idx: int) -> GameState:
    """Grant exactly 1 stable for 1 wood (the granted, now-mandatory sub-action)."""
    return push(state, PendingBuildStables(
        player_idx=idx,
        initiated_by_id=f"card:{CARD_ID}",
        cost=_STABLE_COST,
        max_builds=1,
    ))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1)))
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_SPACES)
