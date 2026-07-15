"""Sheep Rug (minor improvement, E21; Ephipparius Expansion; players -).

Card text: "You can use any \"Wish for Children\" action space, even if it is
occupied by another player's person."
Cost: 1 Sheep. Prerequisite: 4 Sheep. Kept (not traveling). 1 printed VP.

One mechanism — a LEGALITY RELAXATION on worker placement, identical in shape to
Sleeping Corner (A26): the owner may place on a "Wish for Children" space even
when an OTHER player already holds it. Registered via `register_occupancy_override`
(consulted only when the space is occupied, so the Family game pays nothing).

Two load-bearing points, both inherited from Sleeping Corner:

- COUNT PLAYERS, NOT WORKERS. A normally-used wish space already holds TWO of one
  player's workers — the parent placed by the action plus the newborn it generates
  (modeled in `_resolve_wish_for_children`). "Occupied by another player's person"
  therefore means "exactly one OTHER player has a worker here," not "one worker":
  the override requires exactly one other player to have a worker on the space (the
  `== 1` below), tolerating that player's parent+newborn pair. The `!= 0` self-check
  stops the owner using a space they already occupy.

- The exact-one-other-player shape generalizes to 4-player. In the current 2-player
  game a single opponent is the only "other player," so `others_with_workers == 1`
  is automatic when the owner holds no worker there; writing it as a player count
  keeps it correct if the 4-player variant lands.

Card-only state (the override registry is empty in the Family game), so the Family
game is byte-identical and the C++ differential gates are untouched.

The COST is an animal cost (1 sheep, paid at play) and the PREREQUISITE is a
have-check (hold >= 4 sheep, never spent) — distinct quantities: a player needs 4
sheep to qualify, pays 1, and keeps 3.
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.legality import register_occupancy_override
from agricola.resources import Animals, Cost
from agricola.state import GameState, get_space

CARD_ID = "sheep_rug"
WISH_SPACES = frozenset({"basic_wish_for_children", "urgent_wish_for_children"})


def _prereq(state: GameState, idx: int) -> bool:
    """4 Sheep — a HAVE-check: hold at least four sheep (not spent)."""
    return state.players[idx].animals.sheep >= 4


def _occupancy_override(state: GameState, space_id: str) -> bool:
    """The current player may place on an occupied "Wish for Children" space iff they
    own Sheep Rug, hold no worker there themselves, and exactly one OTHER player does
    (count players, not workers)."""
    if space_id not in WISH_SPACES:
        return False
    ap = state.current_player
    if CARD_ID not in state.players[ap].minor_improvements:
        return False
    workers = get_space(state.board, space_id).workers
    if workers[ap] != 0:
        return False
    others_with_workers = sum(1 for i, w in enumerate(workers) if i != ap and w > 0)
    return others_with_workers == 1


register_minor(
    CARD_ID,
    cost=Cost(animals=Animals(sheep=1)),
    prereq=_prereq,
    vps=1,
)
register_occupancy_override(_occupancy_override)
