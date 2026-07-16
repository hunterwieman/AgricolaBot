"""Porter (occupation, D146; Consul Dirigens Expansion; players 3+).

Card text: "Each time you take at least 4 of the same building resource from an
accumulation space, you get 1 additional building resource of the accumulating type and
1 food."
Clarification: "4 of the same building resource must already be on the accumulation
space."

Category 3 (action-space hook, automatic income) — the multi-space Geologist shape. A
mandatory, choice-free bonus → an automatic effect (`register_auto`) on the AFTER window:
each building-resource accumulation space accumulates exactly one type (forest→wood,
clay_pit→clay, reed_bank→reed, western_quarry/eastern_quarry→stone), so "the accumulating
type" is that space's type. The amount TAKEN of it is read off the host frame's `taken`
(the Resources delta stamped across the take at Proceed) — equal, at 2p, to the pre-take
pile the clarification points at ("4 must already be on the space"). If ≥4 was taken, grant
+1 of that same type and +1 food.

Every building-resource accumulation space is atomic, so `register_action_space_hook`
hosts them when this card is owned.

This is a [3+] occupation — not dealt in the 2-player game, but valid to implement and
unit-test now. Played via Lessons; on-play is a no-op.
"""
from __future__ import annotations

from agricola.constants import (
    BUILDING_ACCUMULATION_RATES,
    BUILDING_RESOURCE_ACCUMULATION_SPACES,
)
from agricola.cards.specs import register_occupation
from agricola.cards.triggers import register_action_space_hook, register_auto
from agricola.replace import fast_replace
from agricola.resources import Resources
from agricola.state import GameState

CARD_ID = "porter"

_THRESHOLD = 4   # "at least 4 of the same building resource"
_BUILDING_FIELDS = ("wood", "clay", "reed", "stone")


def _accumulating_field(space_id: str) -> str | None:
    """The single building resource `space_id` accumulates ("the accumulating
    type"), DERIVED from BUILDING_ACCUMULATION_RATES rather than a hard-coded
    per-space map — so it is correct for any 4p building space the category hooks
    (matches interim_storage's good-type derivation). Each building space has one
    rate resource; returns its field, or None for a non-building space."""
    rate = BUILDING_ACCUMULATION_RATES.get(space_id)
    if rate is None:
        return None
    return next((f for f in _BUILDING_FIELDS if getattr(rate, f)), None)


def _accumulating(state: GameState):
    """(field, amount) of the accumulating resource the acting player took: the field
    is the hosted space's accumulation type, the amount is read off the host frame's
    `taken` (the Resources delta stamped across the take at Proceed)."""
    top = state.pending_stack[-1]
    space_id = getattr(top, "space_id", None)
    field = _accumulating_field(space_id) if space_id else None
    if field is None:
        return None, 0
    return field, getattr(top.taken, field)


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
register_auto("after_action_space", CARD_ID, _eligible, _apply)
register_action_space_hook(CARD_ID, BUILDING_RESOURCE_ACCUMULATION_SPACES)
