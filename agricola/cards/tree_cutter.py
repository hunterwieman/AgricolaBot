"""Tree Cutter (occupation, D143; Dulcinaria Expansion; players 3+).

Card text: "Each time you use an accumulation space providing at least 3 goods of
the same type except wood, you get an additional 1 wood. (Food is also considered
a good.)"

A bare "each time you use" that keys on WHAT WAS PROVIDED reads it in the AFTER
phase (Refactor A): the reward is flat (+1 wood) and gates on the goods actually
taken from the space. Mandatory and choiceless → an automatic effect
(register_auto), owner-gated ("you").

The gate is "the space provides ≥3 of a single NON-WOOD good type" (food explicitly
counts), read from what was TAKEN across the take:
  - Building spaces (Clay Pit, Reed Bank, the two Quarries, and Forest) stamp the
    swept goods on the host frame's ``taken`` (a Resources delta); qualify if
    taken.clay/reed/stone ≥ 3. Forest provides only wood, so its non-wood count is
    always 0 — it can never qualify, but per a standing directive to hook EVERY
    accumulation space it is still hosted (inert).
  - Fishing's swept food lands in ``taken.food``; qualifies if ≥ 3.
  These are ATOMIC, hosted via register_action_space_hook (``taken`` is stamped at
  the Proceed take).
  - Animal markets (Sheep/Pig/Cattle Market) each hold one animal type staged on
    the frame's ``gained`` (market frames carry no ``taken``); qualify if gained ≥ 3.
    NON-ATOMIC (always hosted), so no hook is needed; ``gained`` persists into the
    after-window.

On-play is a no-op. Card-game only (ownership-gated registries), so the Family
trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.constants import (
    ANIMAL_ACCUMULATION_SPACES,
    BUILDING_RESOURCE_ACCUMULATION_SPACES,
    FOOD_ACCUMULATION_SPACES,
)
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "tree_cutter"

_THRESHOLD = 3


def _eligible(state: GameState, idx: int) -> bool:
    top = state.pending_stack[-1]
    sid = top.space_id
    # Animal markets (non-atomic → always hosted; count staged on frame.gained).
    if sid in ANIMAL_ACCUMULATION_SPACES:
        return top.gained >= _THRESHOLD
    if sid in FOOD_ACCUMULATION_SPACES:   # atomic → swept food in taken.food
        return top.taken.food >= _THRESHOLD
    # Building spaces: only NON-wood goods count ("except wood"), so a wood-only
    # space (Forest) has clay/reed/stone == 0 in `taken` and never qualifies though
    # it is hooked. Behavior-identical at 2p and correct for any 4p building space.
    if sid in BUILDING_RESOURCE_ACCUMULATION_SPACES:
        acc = top.taken
        return (acc.clay >= _THRESHOLD or acc.reed >= _THRESHOLD
                or acc.stone >= _THRESHOLD)
    return False


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_action_space", CARD_ID, _eligible, _apply)
# Standing directive: hook EVERY accumulation space, including wood (Forest). Forest
# is inert (its non-wood count is 0), so adding it is behavior-preserving at 2p.
register_action_space_hook(
    CARD_ID, BUILDING_RESOURCE_ACCUMULATION_SPACES | FOOD_ACCUMULATION_SPACES)
