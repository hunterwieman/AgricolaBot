"""Porter (occupation, D146; Consul Dirigens Expansion; players 3+).

Card text: "Each time you take at least 4 of the same building resource from an
accumulation space, you get 1 additional building resource of the accumulating type and
1 food."
Clarification: "4 of the same building resource must already be on the accumulation
space."

Category 3 (action-space hook, automatic income) — the multi-space Geologist shape. A
mandatory, choice-free bonus → an automatic effect (`register_auto`) on the BEFORE window
— confirmed by the clarification (the 4 "must already be on the space", i.e. read the
pre-take amount): each building-resource accumulation space accumulates exactly one type
(forest→wood, clay_pit→clay, reed_bank→reed, western_quarry/eastern_quarry→stone), so
"the accumulating type" is that space's type. If ≥4 of it are on the space, grant +1 of
that same type and +1 food.

Every building-resource accumulation space is atomic, so `register_action_space_hook`
hosts them when this card is owned.

This is a [3+] occupation — not dealt in the 2-player game, but valid to implement and
unit-test now. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState, get_space

CARD_ID = "porter"

# space -> the single building resource it accumulates ("the accumulating type").
_SPACE_FIELD = {
    "forest": "wood",
    "clay_pit": "clay",
    "reed_bank": "reed",
    "western_quarry": "stone",
    "eastern_quarry": "stone",
}
SPACES = frozenset(_SPACE_FIELD)

_THRESHOLD = 4   # "at least 4 of the same building resource"


def _accumulating(state: GameState):
    """(field, amount) of the accumulating resource on the hosted space."""
    space_id = getattr(state.pending_stack[-1], "space_id", None)
    field = _SPACE_FIELD.get(space_id)
    if field is None:
        return None, 0
    return field, getattr(get_space(state.board, space_id).accumulated, field)


def _eligible(state: GameState, idx: int) -> bool:
    _field, amount = _accumulating(state)
    return amount >= _THRESHOLD


def _apply(state: GameState, idx: int) -> GameState:
    field, _amount = _accumulating(state)
    bonus = Resources(**{field: 1, "food": 1})
    p = fast_replace(state.players[idx],
                     resources=state.players[idx].resources + bonus)
    return fast_replace(state, players=tuple(
        p if i == idx else state.players[i] for i in range(2)))


register_occupation(CARD_ID, lambda state, idx: state)   # no on-play effect
register_auto("before_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, SPACES)
