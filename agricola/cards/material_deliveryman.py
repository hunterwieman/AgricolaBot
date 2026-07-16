"""Material Deliveryman (occupation, C163; Corbarius Expansion; players 4+).

Card text: "Each time any player (including you) takes 5/6/7/8+ goods from an
accumulation space, you get 1 wood/clay/reed/stone from the general supply."

An any-player action hook (the Milk Jug shape): fired for the OWNER whenever ANY
player takes goods from an accumulation space. A bare "each time any player takes"
that keys on WHAT WAS TAKEN reads it in the AFTER phase (Refactor A). Mandatory and
choiceless → an automatic effect (register_auto) with ``any_player=True``.

The reward is DETERMINED by the goods count (a positional mapping, not a free
choice): exactly 5 → 1 wood, exactly 6 → 1 clay, exactly 7 → 1 reed, 8 or more → 1
stone; fewer than 5 → nothing.

"Goods taken" is the total across ALL good types the player obtained from the space,
read from what was actually taken across the take:
  - Building spaces (Forest, Clay Pit, Reed Bank, the two Quarries) stamp the swept
    goods on the host frame's ``taken`` (a Resources delta) → sum its fields. ATOMIC,
    hosted via register_action_space_hook (``taken`` stamped at the Proceed take).
  - Fishing's swept food lands in ``taken.food``. ATOMIC → hooked.
  - Animal markets stage their animal count on the frame's ``gained`` (market frames
    carry no ``taken``). NON-ATOMIC (always hosted) → no hook needed; ``gained``
    persists into the after-window.
All hooks are any_player so the host frame appears on either player's turn.

On-play is a no-op. Card-game only (ownership-gated registries), so the Family
trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.constants import (
    ACCUMULATION_SPACES,
    ANIMAL_ACCUMULATION_SPACES,
    BUILDING_RESOURCE_ACCUMULATION_SPACES,
    FOOD_ACCUMULATION_SPACES,
)
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "material_deliveryman"


def _goods_taken(top) -> int:
    sid = top.space_id
    if sid in ANIMAL_ACCUMULATION_SPACES:
        return top.gained
    if sid in FOOD_ACCUMULATION_SPACES:   # atomic → swept food in taken.food
        return top.taken.food
    acc = top.taken                        # atomic building space: goods swept in taken
    return acc.wood + acc.clay + acc.reed + acc.stone + acc.grain + acc.veg + acc.food


def _reward(n: int) -> Resources | None:
    if n >= 8:
        return Resources(stone=1)
    return {5: Resources(wood=1), 6: Resources(clay=1),
            7: Resources(reed=1)}.get(n)


def _eligible(state: GameState, owner: int) -> bool:
    top = state.pending_stack[-1]
    if top.space_id not in ACCUMULATION_SPACES:
        return False
    return _reward(_goods_taken(top)) is not None


def _apply(state: GameState, owner: int) -> GameState:
    top = state.pending_stack[-1]
    bonus = _reward(_goods_taken(top))
    p = state.players[owner]
    p = fast_replace(p, resources=p.resources + bonus)
    return fast_replace(state, players=tuple(
        p if i == owner else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_action_space", CARD_ID, _eligible, _apply, any_player=True)
# Atomic accumulation spaces (need hosting on either player's turn); markets are
# non-atomic and always hosted, so they are not passed here.
register_action_space_hook(
    CARD_ID, BUILDING_RESOURCE_ACCUMULATION_SPACES | FOOD_ACCUMULATION_SPACES,
    any_player=True)
