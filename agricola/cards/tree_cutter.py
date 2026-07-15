"""Tree Cutter (occupation, D143; Dulcinaria Expansion; players 3+).

Card text: "Each time you use an accumulation space providing at least 3 goods of
the same type except wood, you get an additional 1 wood. (Food is also considered
a good.)"

A bare "each time you use" → the BEFORE phase (Trigger-Timing ruling); the reward
is flat (+1 wood), so before-timing is correct. Mandatory and choiceless → an
automatic effect (register_auto), owner-gated ("you").

The gate is "the space provides ≥3 of a single NON-WOOD good type" (food explicitly
counts). Read at the before-phase, where the amounts are still on the space:
  - Non-wood building spaces (Clay Pit, Reed Bank, the two Quarries) store a
    Resources ``accumulated``; qualify if clay/reed/stone ≥ 3. (Forest provides
    only wood, so it can never qualify and is not hooked.)
  - Fishing stores a food ``accumulated_amount``; qualifies if ≥ 3.
  These are ATOMIC, hosted via register_action_space_hook (their bank is intact in
  the before-phase — the resolver runs at the Proceed flip).
  - Animal markets (Sheep/Pig/Cattle Market) each hold one animal type staged on
    the frame's ``gained``; qualify if gained ≥ 3. NON-ATOMIC (always hosted), so
    no hook is needed.

On-play is a no-op. Card-game only (ownership-gated registries), so the Family
trace and the C++ gates are untouched.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "tree_cutter"

# Non-wood building spaces (atomic → hooked; store a Resources bank). Forest is
# excluded: it provides only wood, which the "except wood" clause rules out.
_NONWOOD_BUILDING = frozenset(
    {"clay_pit", "reed_bank", "western_quarry", "eastern_quarry"})
# Animal markets (non-atomic → always hosted; count staged on frame.gained).
_MARKET_SPACES = frozenset({"sheep_market", "pig_market", "cattle_market"})
# Atomic spaces that can provide a non-wood good: the non-wood building spaces +
# Fishing (food). These need hosting.
_HOOK_SPACES = _NONWOOD_BUILDING | {"fishing"}
_THRESHOLD = 3


def _eligible(state: GameState, idx: int) -> bool:
    top = state.pending_stack[-1]
    sid = top.space_id
    if sid in _MARKET_SPACES:
        return top.gained >= _THRESHOLD
    if sid == "fishing":
        return get_space(state.board, "fishing").accumulated_amount >= _THRESHOLD
    if sid in _NONWOOD_BUILDING:
        acc = get_space(state.board, sid).accumulated
        return (acc.clay >= _THRESHOLD or acc.reed >= _THRESHOLD
                or acc.stone >= _THRESHOLD)
    return False


def _apply(state: GameState, idx: int) -> GameState:
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources + Resources(wood=1))
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, _HOOK_SPACES)
