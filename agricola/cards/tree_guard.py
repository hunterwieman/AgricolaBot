"""Tree Guard (occupation, C102; Corbarius Expansion; players 1+).

Card text: "Each time after you use a wood accumulation space, you can place 4
wood from your supply on that space to get 2 stone, 1 clay, 1 reed, and 1 grain."
Category Goods Provider. No cost / prereq / VPs; not passing.

An OPTIONAL `after_action_space` trigger on the wood accumulation space (Forest is
the only one on the 2-player board; Copse / Grove are 3–4-player board-extension
spaces, never present here). The text's "after you use" is the explicit
"immediately after" exception to the default "each time you use [space]" = before
ruling — confirmed by Carpenter's Axe / Wood Cutter — so it rides
`after_action_space`, firing only once the space's own pickup (Forest's +3 wood)
has already happened. That ordering matters two ways:

  1. The "have 4 wood to place" check is a HAVE-check on the POST-pickup supply
     (engine.py runs ATOMIC_HANDLERS["forest"] first, then `_enter_after_phase`
     flips to the after-phase where eligibility is evaluated), so a player who held
     1 wood and picked up 3 now reads 4 and qualifies.
  2. The 4 wood is PLACED ONTO that accumulation space — it joins Forest's
     `accumulated` pile for a later player (or this player on a later turn) to pick
     up — NOT discarded to the general supply. So `_apply` both debits the player
     -4 wood AND deposits +4 wood onto Forest via `with_space`. The space was just
     emptied by its own pickup, so the deposited pile is exactly those 4 wood.

Forest is an ATOMIC space, so it must be explicitly hosted
(`register_action_space_hook`) to push a PendingActionSpace frame whose Proceed
flips to the after-phase and surfaces this trigger — the same wiring Carpenter's
Axe / Wood Cutter use for atomic wood spaces.

OPTIONALITY: "you can place ... to get ..." → an OPTIONAL FireTrigger (`register`,
not `register_auto`). The decline path IS not firing the trigger — the host's
Proceed/Stop exits without the exchange. The whole effect (pay 4 wood, gain
2 stone / 1 clay / 1 reed / 1 grain) is choiceless once fired, so `_apply` performs
it directly (no pushed sub-decision).

"Each time" = once per use, enforced by `CARD_ID not in triggers_resolved` (NOT
used_this_round — it may fire on every Forest use), exactly as Carpenter's Axe /
Ox Goad. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register, register_action_space_hook
from agricola.constants import WOOD_ACCUMULATION_SPACES
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "tree_guard"

_WOOD_COST = 4
_GAIN = Resources(stone=2, clay=1, reed=1, grain=1)


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    if CARD_ID in triggers_resolved:                       # once per use
        return False
    if state.pending_stack[-1].space_id not in WOOD_ACCUMULATION_SPACES:
        return False
    # Need 4 wood in supply to place onto the space (post-pickup have-check).
    return state.players[idx].resources.wood >= _WOOD_COST


def _apply(state: GameState, idx: int) -> GameState:
    """Place 4 wood from the player's supply onto the just-used wood space, and
    grant 2 stone / 1 clay / 1 reed / 1 grain in return."""
    sid = state.pending_stack[-1].space_id

    # Debit 4 wood from the player, credit the exchange goods.
    p = state.players[idx]
    p = fast_replace(p, resources=p.resources - Resources(wood=_WOOD_COST) + _GAIN)
    players = tuple(p if i == idx else state.players[i] for i in range(2))

    # Deposit the 4 wood onto the space's accumulated pile (not the supply).
    space = get_space(state.board, sid)
    space = fast_replace(space, accumulated=space.accumulated + Resources(wood=_WOOD_COST))
    board = with_space(state.board, sid, space)

    return fast_replace(state, players=players, board=board)


register_occupation(CARD_ID, lambda state, idx: state)  # no on-play effect
register("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, WOOD_ACCUMULATION_SPACES)
