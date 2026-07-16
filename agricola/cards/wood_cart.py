"""Wood Cart (minor improvement, C76; Corbarius Expansion).

Card text: "Each time you use a wood accumulation space, you get 2 additional wood."
Cost: 3 Wood. Prerequisite: 3 Occupations. VPs: none. Not passing.

Category 3 (action-space hook, automatic income). "A wood accumulation space"
resolves to exactly ONE space on the 2-player board — the `forest` space (the only
entry in BUILDING_ACCUMULATION_RATES whose accumulated resource is wood,
Resources(wood=3)); it does NOT fire on clay_pit / the quarries / reed_bank.
"Each time you use [space]" fires in the BEFORE phase per the Trigger-Timing ruling
(matching Throwing Axe / Milk Jug), so the +2 wood is a `before_action_space`
automatic effect. `forest` is an ATOMIC space, so it must be hosted
(register_action_space_hook) for a frame to exist that the before-auto can fire on.

The "3 Occupations" prerequisite is a play-time HAVE-check on the owner's
occupation count, encoded via `min_occupations=3` (never spent — distinct from the
3-wood cost). The +2 wood is mandatory, choiceless, and has no downside, so it is a
register_auto effect (NOT an optional FireTrigger). `any_player` is False: "each
time YOU use" is owner-only (unlike Milk Jug's "any player").
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "wood_cart"


def _eligible(state: GameState, idx: int) -> bool:
    return state.pending_stack[-1].space_id in WOOD_ACCUMULATION_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(wood=2))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=3)), min_occupations=3, vps=0)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
