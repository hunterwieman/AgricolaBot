"""Carter (occupation, E140; Ephipparius Expansion; players 3+).

Card text: "Next round, each time you use a building resource accumulation space,
you also get 1 food for each building resource that you take from the space."

A one-round window: the bonus is live only during the round AFTER the one Carter
was played. on_play snapshots the play round into the per-card CardStore; the
automatic effect's eligibility fires only when ``round_number == played + 1``.

Within that window it is a bare "each time you use" → an automatic effect
(register_auto) on the AFTER window, owner-gated ("you"). The reward scales by
"building resources taken", read off the host frame's ``taken`` (the Resources delta
stamped across the take at Proceed): food = the count of building resources
(wood+clay+reed+stone) the acting player actually obtained from the space. Mandatory
and choiceless.

"Building resource accumulation space" = Forest, Clay Pit, Reed Bank, and the two
Quarries; all ATOMIC, hosted via register_action_space_hook. The hook is static
(the spaces are hosted for every round Carter is owned), but the round latch keeps
the food grant confined to the single "next round"; outside it the auto is inert.
Card-game only (ownership-gated registries), so the Family trace and the C++ gates
are untouched.
"""
from __future__ import annotations

from agricola.constants import BUILDING_RESOURCE_ACCUMULATION_SPACES
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "carter"


def _on_play(state: GameState, idx: int) -> GameState:
    # Snapshot the play round; the bonus is active only in round played + 1.
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.set(CARD_ID, state.round_number))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


def _eligible(state: GameState, idx: int) -> bool:
    played = state.players[idx].card_state.get(CARD_ID, 0)
    # 0 == "not recorded via on_play" (round_number is always >= 1 when stored).
    if not played or state.round_number != played + 1:
        return False
    return state.pending_stack[-1].space_id in BUILDING_RESOURCE_ACCUMULATION_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    taken = state.pending_stack[-1].taken
    food = taken.wood + taken.clay + taken.reed + taken.stone
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, _on_play)
register_auto("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, BUILDING_RESOURCE_ACCUMULATION_SPACES)
