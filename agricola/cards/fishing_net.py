"""Fishing Net (minor improvement, C51; Consul Dirigens Expansion; cost
1 reed, 1 printed VP).

Card text: "Each time another player uses the "Fishing" accumulation space,
they must first pay you 1 food. Then, in the returning home phase of that
round, place 2 food on "Fishing"."
Clarifications: "Others must have 1 food before using 'Fishing'. Food from the
'Fishing' action space may not be used to pay the card owner. The 2 food is
only placed for rounds in which another player used 'Fishing'."

The first BOARD-space toll (ruling 86 item 9, user verbatim: the toll is
"before the before action space autos and triggers" — the card-space toll
model on a board space): registered in `BOARD_SPACE_TOLLS`, paid payer→owner
at the TOP of `engine.initiate_space_use` — ahead of hosting, the before
window, and the atomic sweep, whatever the arrival mode (placement, jump,
Straw Hat / Archway relocation) — which is also what makes the printed
"may not pay from the space's proceeds" automatic. Gating: a placement-forbid
predicate (liquidation-aware via `toll_payable` — a 0-food player with a
cookable animal still arrives through the raise frame, ruling 86 item 2);
`relocation_destinations` consults the same registry for the movers.

The deposit: paying the toll flags the OWNER's CardStore
("fishing_net:board_toll_paid" — machinery-set at the payment); the
`returning_home` window auto reads-and-clears it, placing 2 food on Fishing
(only for rounds in which another player used it, per the clarification —
the owner's own uses set no flag).
"""
from __future__ import annotations

from agricola.cards.card_spaces import (
    BOARD_SPACE_TOLLS, board_space_tolls_due, register_board_space_toll,
    toll_payable,
)
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register_auto
from agricola.legality import register_placement_forbid
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState, get_space, with_space

CARD_ID = "fishing_net"
_FLAG = f"{CARD_ID}:board_toll_paid"


def _forbid(state: GameState, placer_idx: int, space_id: str) -> bool:
    """Forbid a Fishing placement whose toll the placer cannot pay (ruling 86
    item 1: unpayable = illegal; liquidation-aware for the food)."""
    if space_id != "fishing":
        return False
    due = board_space_tolls_due(state, placer_idx, "fishing")
    if not due:
        return False
    total = Resources()
    for _c, _o, toll in due:
        total = total + toll.resources
    return not toll_payable(state, placer_idx, Cost(resources=total))


def _deposit_eligible(state: GameState, idx: int) -> bool:
    return bool(state.players[idx].card_state.get(_FLAG, False))


def _deposit_apply(state: GameState, idx: int) -> GameState:
    """The returning-home deposit: +2 food on Fishing, flag cleared."""
    p = state.players[idx]
    p = fast_replace(p, card_state=p.card_state.remove(_FLAG))
    state = fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(len(state.players))))
    sp = get_space(state.board, "fishing")
    return fast_replace(state, board=with_space(
        state.board, "fishing",
        fast_replace(sp, accumulated_amount=sp.accumulated_amount + 2)))


register_minor(CARD_ID, cost=Cost(resources=Resources(reed=1)), vps=1)
register_board_space_toll(CARD_ID, "fishing", Cost(resources=Resources(food=1)))
register_placement_forbid(_forbid)
register_auto("returning_home", CARD_ID, _deposit_eligible, _deposit_apply)
