"""Pioneering Spirit (minor improvement, D23; Dulcinaria Expansion; no cost,
no prerequisite, no printed VPs).

Card text: "This card is an action space for you only. In rounds 3-5, it
provides a "renovation" action. In rounds 6-8, it provides your choice of
1 vegetable, wild boar, or cattle."

An OWNER-ONLY card action space (the Collector shape — the opponent never sees
the placement) whose action is ROUND-WINDOWED, read at the use:

- rounds 3-5: a "renovation" action — the standard renovate primitive at its
  normal cost (a bare `PendingRenovate` with card provenance, the Master
  Renovator grant shape); carryability = `_can_renovate`, so the space is
  unplaceable when no renovation is possible (stone house / unaffordable).
- rounds 6-8: your choice of 1 vegetable, wild boar, or cattle — three WIDE
  placement variants (`picks = ("veg"|"boar"|"cattle",)`, the Collector
  idiom); animals route through `grant_animals` so the accommodation barrier
  surfaces the keep-which choice on overflow.
- rounds 1-2 and 9-14: no provision — `placeable_fn` empty, the space is dead.
"""
from __future__ import annotations

from agricola.cards.card_spaces import register_card_action_space
from agricola.cards.specs import register_minor
from agricola.helpers import grant_animals
from agricola.legality import _can_renovate
from agricola.pending import PendingRenovate, push
from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import GameState

CARD_ID = "pioneering_spirit"
_GOODS = ("veg", "boar", "cattle")


def _placeable(state: GameState, placer_idx: int, owner_idx: int) -> list:
    r = state.round_number
    if 3 <= r <= 5:
        p = state.players[placer_idx]
        return [None] if _can_renovate(state, p) else []
    if 6 <= r <= 8:
        return [(g,) for g in _GOODS]
    return []


def _use(state: GameState, placer_idx: int, owner_idx: int, picks) -> GameState:
    if picks is None:                              # rounds 3-5: the renovation
        return push(state, PendingRenovate(
            player_idx=placer_idx, initiated_by_id=f"card:{CARD_ID}"))
    good = picks[0]
    if good == "veg":
        p = state.players[placer_idx]
        p = fast_replace(p, resources=p.resources + Resources(veg=1))
        return fast_replace(state, players=tuple(
            p if i == placer_idx else state.players[i]
            for i in range(len(state.players))))
    return grant_animals(state, placer_idx,
                         Animals(**{good: 1}))


register_minor(CARD_ID)
register_card_action_space(CARD_ID, _use, placeable_fn=_placeable)
