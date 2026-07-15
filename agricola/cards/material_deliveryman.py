"""Material Deliveryman (occupation, C163; Corbarius Expansion; players 4+).

Card text: "Each time any player (including you) takes 5/6/7/8+ goods from an
accumulation space, you get 1 wood/clay/reed/stone from the general supply."

An any-player action hook (the Milk Jug shape): fired for the OWNER whenever ANY
player takes goods from an accumulation space. A bare "each time any player takes"
→ the BEFORE phase (Trigger-Timing ruling); the reward is a flat resource grant, so
before-timing is correct. Mandatory and choiceless → an automatic effect
(register_auto) with ``any_player=True``.

The reward is DETERMINED by the goods count (a positional mapping, not a free
choice): exactly 5 → 1 wood, exactly 6 → 1 clay, exactly 7 → 1 reed, 8 or more → 1
stone; fewer than 5 → nothing.

"Goods taken" is the total across ALL good types on the space, read at the
before-phase where it is still available:
  - Building spaces (Forest, Clay Pit, Reed Bank, the two Quarries) store a
    Resources ``accumulated`` → sum its fields. ATOMIC, so hosted via
    register_action_space_hook (their bank is intact until the Proceed flip).
  - Fishing stores a food ``accumulated_amount``. ATOMIC → hooked.
  - Animal markets stage their animal count on the frame's ``gained``. NON-ATOMIC
    (always hosted) → no hook needed.
All hooks are any_player so the host frame appears on either player's turn.

On-play is a no-op. Card-game only (ownership-gated registries), so the Family
trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "material_deliveryman"

_MARKET_SPACES = frozenset({"sheep_market", "pig_market", "cattle_market"})
# Atomic accumulation spaces (need hosting on either player's turn).
_HOOK_SPACES = frozenset(
    {"forest", "clay_pit", "reed_bank", "western_quarry", "eastern_quarry", "fishing"})
# Every accumulation space the count is defined for.
_ACC_SPACES = _HOOK_SPACES | _MARKET_SPACES


def _goods_taken(state: GameState, top) -> int:
    sid = top.space_id
    if sid in _MARKET_SPACES:
        return top.gained
    sp = get_space(state.board, sid)
    if sid == "fishing":
        return sp.accumulated_amount
    acc = sp.accumulated
    return acc.wood + acc.clay + acc.reed + acc.stone + acc.grain + acc.veg + acc.food


def _reward(n: int) -> Resources | None:
    if n >= 8:
        return Resources(stone=1)
    return {5: Resources(wood=1), 6: Resources(clay=1),
            7: Resources(reed=1)}.get(n)


def _eligible(state: GameState, owner: int) -> bool:
    top = state.pending_stack[-1]
    if top.space_id not in _ACC_SPACES:
        return False
    return _reward(_goods_taken(state, top)) is not None


def _apply(state: GameState, owner: int) -> GameState:
    top = state.pending_stack[-1]
    bonus = _reward(_goods_taken(state, top))
    p = state.players[owner]
    p = fast_replace(p, resources=p.resources + bonus)
    return fast_replace(state, players=tuple(
        p if i == owner else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply, any_player=True)
register_action_space_hook(CARD_ID, _HOOK_SPACES, any_player=True)
