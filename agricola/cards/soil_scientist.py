"""Soil Scientist (occupation, C114; Corbarius Expansion; players 1+).

Card text: "Each time after you use a clay/stone accumulation space, you can place
1 stone/2 clay from your supply on the space to get 2 grain/1 vegetable,
respectively."

The "clay/stone … 1 stone/2 clay … 2 grain/1 vegetable, respectively" is a single
slash-paired sentence whose branch is fixed by WHICH space was used (not a choice
the player makes). Resolving the pairs positionally:

  - a CLAY accumulation space (Clay Pit) → pay 1 STONE → get 2 grain
  - a STONE accumulation space (Western Quarry / Eastern Quarry) → pay 2 CLAY →
    get 1 vegetable

Note the cost good is always the OPPOSITE mineral of the space used, and the two
quarries share the identical stone-space branch. The two branches are asymmetric
(1↔2 in the cost, grain↔veg in the reward) — they are NOT an OR-cost the player
picks between, so this is a single deterministic effect, not a play-variant.

OPTIONALITY: "you can place" → an OPTIONAL `after_action_space` FireTrigger
(`register`, NOT `register_auto`). Declining is simply not firing — the host's
Proceed/Stop exits without the swap. Eligibility gates on the player actually
having the cost mineral, so a fire is never a dead-end.

TIMING: the text says "each time AFTER you use" — the explicit "immediately after"
exception to the default "each time you use [space]" = before ruling (cf. Clay
Puncher / Carpenter's Axe) — so the hook is on `after_action_space`, firing only
once the space's own pickup has already happened.

"Each time" = once per use, enforced by `CARD_ID not in triggers_resolved` (NOT
used_this_round — it may fire on every separate Clay Pit / quarry use), exactly as
Carpenter's Axe / Ox Goad. The swap is a pure goods exchange with no pushed frame
(like Potter Ceramics): `_apply` returns the state with the resources adjusted and
leaves the host frame on top, where `triggers_resolved` is stamped.

All three accumulation spaces are ATOMIC, so each must be explicitly hosted
(`register_action_space_hook`) to push a PendingActionSpace frame whose Proceed
flips to the after-phase that surfaces this trigger — the same wiring Mineralogist
uses for the same three mineral spaces.

"place … on the space" is flavor: the goods leave the player's supply, so no
per-card goods stack is needed. No on-play effect, no cost, no prereq, no VPs.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "soil_scientist"

# Clay Pit is the only clay accumulation space; the two quarries are the only
# stone accumulation spaces on the 2-player board.
CLAY_SPACE = "clay_pit"
STONE_SPACES = frozenset({"western_quarry", "eastern_quarry"})
SOIL_SCIENTIST_SPACES = frozenset({CLAY_SPACE}) | STONE_SPACES

# Each branch's signed goods delta (cost mineral leaves supply, reward added).
# Clay space: -1 stone, +2 grain.  Stone spaces: -2 clay, +1 vegetable.
_CLAY_SPACE_DELTA = Resources(stone=-1, grain=2)
_STONE_SPACE_DELTA = Resources(clay=-2, veg=1)


def _delta_for(space_id: str) -> Resources:
    return _CLAY_SPACE_DELTA if space_id == CLAY_SPACE else _STONE_SPACE_DELTA


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    space_id = state.pending_stack[-1].space_id
    if space_id not in SOIL_SCIENTIST_SPACES:
        return False
    res = state.players[idx].resources
    # Must actually hold the cost mineral, else the swap is a dead-end fire.
    if space_id == CLAY_SPACE:
        return res.stone >= 1
    return res.clay >= 2


def _apply(state: GameState, idx: int) -> GameState:
    """Pure goods swap fixed by the space used; no pushed frame (cf. Potter)."""
    delta = _delta_for(state.pending_stack[-1].space_id)
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + delta)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)     # no on-play effect
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SOIL_SCIENTIST_SPACES)
