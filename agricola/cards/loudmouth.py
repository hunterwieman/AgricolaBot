"""Loudmouth (occupation, D140; Dulcinaria Expansion; players 3+).

Card text: "Each time you take at least 4 building resources or 4 animals from an
accumulation space, you also get 1 food."

A bare "each time you take" → the BEFORE phase (Trigger-Timing ruling); the
reward is flat (+1 food), so before-timing is correct. Mandatory and choiceless →
an automatic effect (register_auto), owner-gated ("you").

Reading "how many taken" at the before-phase: the amount the player will take IS
what's sitting on the space right now.
  - Building-resource accumulation spaces (Forest, Clay Pit, Reed Bank, the two
    Quarries) store a Resources ``accumulated``; the building-resource count is
    wood+clay+reed+stone. These are ATOMIC, so they are hosted via
    register_action_space_hook and their ``accumulated`` is still intact in the
    before-phase (the resolver runs at the Proceed flip).
  - Animal markets (Sheep/Pig/Cattle Market) are NON-ATOMIC hosts; their initiator
    stages the animals onto the frame's ``gained`` int and zeroes the space, so the
    animal count is read from ``top.gained`` — no hook needed (always hosted).
Food and other spaces never meet either threshold, so no other space participates.

On-play is a no-op. Card-game only (ownership-gated registries), so the Family
trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "loudmouth"

# Building-resource accumulation spaces (atomic → hooked; store a Resources bank).
_BUILDING_SPACES = frozenset(
    {"forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry"})
# Animal markets (non-atomic → always hosted; count staged on frame.gained).
_MARKET_SPACES = frozenset({"sheep_market", "pig_market", "cattle_market"})
_THRESHOLD = 4


def _eligible(state: GameState, idx: int) -> bool:
    top = state.pending_stack[-1]
    sid = top.space_id
    if sid in _BUILDING_SPACES:
        acc = get_space(state.board, sid).accumulated
        return acc.wood + acc.clay + acc.reed + acc.stone >= _THRESHOLD
    if sid in _MARKET_SPACES:
        return top.gained >= _THRESHOLD
    return False


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
# Only the atomic building spaces need hosting; the markets are always hosted.
register_action_space_hook(CARD_ID, _BUILDING_SPACES)
