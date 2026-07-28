"""Archway (minor improvement, D51; Dulcinaria Expansion; cost 2 clay,
prereq No Occupations, 4 printed VPs).

Card text: "This card is an action space for all. A player who uses it
immediately gets 1 food. Immediately before the returning home phase, they can
use an unoccupied action space with the person from this card."

A FOR-ALL card action space with NO toll (ruling 86), whose action is +1 food
and a PARK: the person stays on the card until the `after_work` rung
("immediately before the returning home phase" — ruling 50's Informant rung),
where the PARKED PLAYER — the user of the space, not the card's owner (ruling
86 item 4 confirmations) — may move that person to an unoccupied action space
and take that action, or simply let it go home at the reset (declining is the
window's Proceed; a destination-less park just goes home).

The move inherits the Straw Hat readings wholesale (rulings 83/86): the
destination universe is `worker_moves.relocation_destinations` (strict
unoccupancy, the destination's own placement predicate probed as the mover,
card spaces included with their tolls gating the arrival), the ledger entry
follows the person (its number is PRESERVED — ruling 79 item 3), and the
destination resolves as a FULL use above the window host.

Steam Machine coupling (user ruling, 2026-07-27, verbatim): "after_work is
during the work phase so yes. A fired Steam Machine forecloses Archway's move
(and an Archway move onto an accumulation space re-opens Steam Machine), just
like Straw Hat." — the move branch consults `last_use_committed` (set → no
move; unset → Steam Machine's own after_action_space trigger surfaces at an
accumulation destination with no code here).

MACHINERY NOTE — `is_owned_fn`: the after_work trigger belongs to whoever is
PARKED, not the tableau owner, so the registration overrides the ownership
gate with "has a worker on this card" (the per-entry predicate the craft
majors' span triggers established).
"""
from __future__ import annotations

from agricola.cards.card_spaces import (
    card_space_worker_count, register_card_action_space,
)
from agricola.cards.specs import register_minor
from agricola.cards.triggers import register, register_play_variant_trigger
from agricola.cards.worker_moves import relocate_and_use, relocation_destinations
from agricola.replace import fast_replace
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "archway"


def _use(state: GameState, placer_idx: int, owner_idx: int, picks) -> GameState:
    """The space's action: +1 food, and the person parks (the marker stays)."""
    p = state.players[placer_idx]
    p = fast_replace(p, resources=p.resources + Resources(food=1))
    return fast_replace(state, players=tuple(
        p if i == placer_idx else state.players[i]
        for i in range(len(state.players))))


def _parked(state: GameState, idx: int) -> bool:
    return card_space_worker_count(state.players[idx], CARD_ID) >= 1


def _variants(state: GameState, idx: int) -> list:
    if state.players[idx].last_use_committed:      # the ruled foreclosure
        return []
    return relocation_destinations(state, idx)


def _eligible(state: GameState, idx: int, _resolved: frozenset) -> bool:
    """Parked (the is_owned_fn gate) + at least one legal destination — a
    destination-less or foreclosed park is simply not offered (the person
    goes home at the reset)."""
    return bool(_variants(state, idx))


def _apply(state: GameState, idx: int, variant: str, picks=None) -> GameState:
    state = fast_replace(state, current_player=idx)
    return relocate_and_use(state, idx, f"card:{CARD_ID}", variant, picks=picks)


register_minor(CARD_ID, cost=Cost(resources=Resources(clay=2)),
               max_occupations=0, vps=4)
register_card_action_space(CARD_ID, _use, for_all=True)
register("after_work", CARD_ID, _eligible, _apply, is_owned_fn=_parked)
register_play_variant_trigger(CARD_ID, _variants)
