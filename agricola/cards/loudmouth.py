"""Loudmouth (occupation, D140; Dulcinaria Expansion; players 3+).

Card text: "Each time you take at least 4 building resources or 4 animals from an
accumulation space, you also get 1 food."

A bare "each time you take" reads WHAT WAS TAKEN, so it fires in the AFTER phase
(Refactor A): the reward is flat (+1 food) and keys on the goods the player actually
obtained from the space. Mandatory and choiceless → an automatic effect
(register_auto), owner-gated ("you").

Reading "how many taken" at the after-phase (measured across the take):
  - Building-resource accumulation spaces (Forest, Clay Pit, Reed Bank, the two
    Quarries) are ATOMIC, hosted via register_action_space_hook; the goods swept
    into the player are stamped on the host frame's ``taken`` (a Resources delta)
    at the Proceed take, so the building-resource count is
    taken.wood+clay+reed+stone.
  - Animal markets (Sheep/Pig/Cattle Market) are NON-ATOMIC hosts (always hosted,
    no hook); their initiator stages the animals onto the frame's ``gained`` int
    (market frames carry no ``taken``), so the animal count is read from
    ``top.gained`` — unchanged by the after-timing shift, since ``gained`` persists
    into the after-window.
Food and other spaces never meet either threshold, so no other space participates.

On-play is a no-op. Card-game only (ownership-gated registries), so the Family
trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.constants import (
    ANIMAL_ACCUMULATION_SPACES,
    BUILDING_RESOURCE_ACCUMULATION_SPACES,
)
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "loudmouth"

_THRESHOLD = 4


def _eligible(state: GameState, idx: int) -> bool:
    top = state.pending_stack[-1]
    sid = top.space_id
    # Building-resource accumulation spaces (atomic → hooked; goods stamped on
    # the host's `taken` across the take).
    if sid in BUILDING_RESOURCE_ACCUMULATION_SPACES:
        t = top.taken
        return t.wood + t.clay + t.reed + t.stone >= _THRESHOLD
    # Animal markets (non-atomic → always hosted; count staged on frame.gained).
    if sid in ANIMAL_ACCUMULATION_SPACES:
        return top.gained >= _THRESHOLD
    return False


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("after_action_space", CARD_ID, _eligible, _apply)
# Only the atomic building spaces need hosting; the markets are always hosted.
register_action_space_hook(CARD_ID, BUILDING_RESOURCE_ACCUMULATION_SPACES)
