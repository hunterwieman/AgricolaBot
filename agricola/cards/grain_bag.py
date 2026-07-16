"""Grain Bag (minor improvement, E67; Ephipparius Expansion; cost 1 reed, 1 VP).

Card text: "Each time you use the 'Grain Seeds' action space, you get 1 additional
grain for each baking improvement you have."

Corn Scoop's shape (an automatic before-window income on the atomic Grain Seeds
space), but the grain scales with the number of baking improvements owned via
`legality.count_baking_improvements`: the baking majors (Fireplace / Cooking Hearth
/ Clay Oven / Stone Oven) plus owned baking MINOR improvements (Simple Oven, Iron
Oven, Baking Course, and future ones — `BAKING_SPEC_EXTENSION_CARD_IDS`). Counted by
OWNERSHIP, so a Baking Course counts even though it only bakes at round-end (user
ruling 2026-07-15: baking minors count, not just the majors). Played via an
improvement space; the effect is the hook, so on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.legality import count_baking_improvements
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "grain_bag"
SPACES = frozenset({"grain_seeds"})


def _eligible(state: GameState, idx: int) -> bool:
    return (state.pending_stack[-1].space_id in SPACES
            and count_baking_improvements(state, idx) > 0)


def _apply(state: GameState, idx: int) -> GameState:
    n = count_baking_improvements(state, idx)
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + Resources(grain=n))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(reed=1)), vps=1)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
