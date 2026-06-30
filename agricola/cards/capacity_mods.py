"""House-pet-capacity modifier registry (animal accommodation; CARD_AUTHORING_GUIDE §4).

The number of "flexible" animal slots a player's HOUSE provides — capacity-1 slots that
each hold one animal of ANY type (the same abstraction as a standalone stable), read by
`extract_slots` in `helpers.py`. The Family-game default is exactly 1 (the single house
pet). A capacity card raises it by adding one row here at import time; no engine edits.
`extract_slots` reads the fold accessor `house_pet_capacity`.

Empty registry (the Family game owns no cards) -> `house_pet_capacity` returns 1, so
`extract_slots`'s `num_flexible` is byte-identical to the pre-card `standalone_stables + 1`.

Only capacity-RAISING modifiers exist today (Animal Tamer: one slot per room — and the
heterogeneous-type freedom it grants is already captured by the flexible-slot model, since
`can_accommodate` sums overflow across types into a flat slot count). A future NEGATION
card — Milking Place D012, "you can no longer hold animals in your house (not even via
another card)" — must drive the result to 0, which the `max`-fold below cannot express.
Milking Place explicitly negates Animal Tamer, so the two are co-designed: wire the
negation as a separate check when Milking Place is implemented. (Out of scope now; flagged
so the `max` fold isn't mistaken for the whole story.)
"""
from __future__ import annotations

from typing import Callable

# (card_id, fn(player_state) -> int): each owned modifier proposes a house-pet-slot count;
# the fold takes the max (starting from the default 1). Capacity-raising only — see the
# module docstring on the future negation case.
HOUSE_CAPACITY_MODS: list[tuple[str, Callable]] = []


def register_house_capacity(card_id: str, capacity_fn: Callable) -> None:
    """Register a capacity card's house-pet-slot count. `capacity_fn(player_state) -> int`
    returns how many flexible house slots the card grants this player (Animal Tamer: the
    room count). Called at card-module import; ownership-gated in the fold below."""
    HOUSE_CAPACITY_MODS.append((card_id, capacity_fn))


def _owns(player_state, card_id: str) -> bool:
    return card_id in player_state.occupations or card_id in player_state.minor_improvements


def house_pet_capacity(player_state) -> int:
    """Flexible animal slots provided by the house: 1 (the default pet) unless an owned
    capacity card raises it. Empty registry / no owned modifier -> 1 (Family byte-identity)."""
    cap = 1
    for card_id, capacity_fn in HOUSE_CAPACITY_MODS:
        if _owns(player_state, card_id):
            cap = max(cap, capacity_fn(player_state))
    return cap
