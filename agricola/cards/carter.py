"""Carter (occupation, E140; Ephipparius Expansion; players 3+).

Card text: "Next round, each time you use a building resource accumulation space,
you also get 1 food for each building resource that you take from the space."

A one-round window: the bonus is live only during the round AFTER the one Carter
was played. on_play snapshots the play round into the per-card CardStore; the
automatic effect's eligibility fires only when ``round_number == played + 1``.

Within that window it is a bare "each time you use" → the BEFORE phase
(Trigger-Timing ruling). The reward scales by "building resources taken", which at
the before-phase equals what is sitting on the space (a building space stores a
Resources ``accumulated``; the resolver runs at the Proceed flip, so it is still
intact) — a flat computation, so before-timing is correct. Mandatory and choiceless
→ an automatic effect (register_auto), owner-gated ("you").

"Building resource accumulation space" = Forest, Clay Pit, Reed Bank, and the two
Quarries; all ATOMIC, hosted via register_action_space_hook. The hook is static
(the spaces are hosted for every round Carter is owned), but the round latch keeps
the food grant confined to the single "next round"; outside it the auto is inert.
Card-game only (ownership-gated registries), so the Family trace and the C++ gates
are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "carter"

# Building-resource accumulation spaces (store a Resources bank).
_BUILDING_SPACES = frozenset(
    {"forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry"})


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
    return state.pending_stack[-1].space_id in _BUILDING_SPACES


def _apply(state: GameState, idx: int) -> GameState:
    sid = state.pending_stack[-1].space_id
    acc = get_space(state.board, sid).accumulated
    food = acc.wood + acc.clay + acc.reed + acc.stone
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(food=food))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, _on_play)
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, _BUILDING_SPACES)
