"""Shared helpers for Category-8 deferred-goods cards (CARD_IMPLEMENTATION_PLAN.md
§II.5 / Category 8).

These cards place goods / effects on FUTURE round spaces — "place 1 food on each of
the next 3 round spaces", "place 1 wood on each remaining even-numbered round
space", etc. The promise lands in a player's per-round schedule and is collected at
the START of each scheduled round (in `engine._complete_preparation`):

- **Goods / food** ride on `PlayerState.future_resources` (a `tuple[Resources, ...]`,
  the Family-reachable structure the Well already uses). `schedule_resources`
  adds to those slots additively.
- **Effect-card round-start hooks** ride on `PlayerState.future_rewards` (the
  card-only `tuple[FutureReward, ...]`). `schedule_effect` unions a card id into
  the named round slots; that scheduled id is what an OPTIONAL `start_of_round`
  trigger checks for eligibility (Handplow's deferred plow), surfaced at the
  preparation ladder's start_of_round window with a decline (hosting is
  eligibility-driven — the window's choice frame is pushed exactly when the
  schedule makes the trigger eligible). A granted sub-action is
  the player's to take or decline, so it is NOT auto-fired at round start.

Index convention (matching the engine's Well code): slot `r` (0-indexed) holds the
goods promised for round `r+1`, collected when round `r+1` is entered. So a card
placing on "round N" (1-indexed, as printed on the board) writes slot `N-1`. Slots
are clamped to the 14-round game; a round already past (or > 14) is silently
dropped, matching "place on each REMAINING round space".
"""
from __future__ import annotations

from typing import Iterable

from agricola.replace import fast_replace
from agricola.resources import Animals, Resources
from agricola.state import FutureReward, GameState


def _update_player(state: GameState, idx: int, new_player) -> GameState:
    return fast_replace(
        state, players=tuple(new_player if i == idx else state.players[i]
                             for i in range(len(state.players))))


def schedule_resources(
    state: GameState, idx: int, rounds: Iterable[int], goods: Resources,
) -> GameState:
    """Add `goods` to player `idx`'s future_resources for each 1-indexed round in
    `rounds` that is still in the future (or current — entered next). Additive:
    repeated placers stack on the same slot. Rounds outside 1..14 are dropped."""
    p = state.players[idx]
    slots = list(p.future_resources)
    for rnd in rounds:
        slot = rnd - 1
        if 0 <= slot < len(slots):
            slots[slot] = slots[slot] + goods
    return _update_player(state, idx, fast_replace(p, future_resources=tuple(slots)))


def schedule_effect(
    state: GameState, idx: int, rounds: Iterable[int], card_id: str,
) -> GameState:
    """Union `card_id` into player `idx`'s future_rewards effect-hook set for each
    1-indexed round in `rounds`. The scheduled id gates the card's OPTIONAL
    start_of_round trigger (surfaced at that window's choice host) when that round
    is entered. Additive."""
    p = state.players[idx]
    slots = list(p.future_rewards)
    for rnd in rounds:
        slot = rnd - 1
        if 0 <= slot < len(slots):
            slots[slot] = slots[slot] + FutureReward(effect_card_ids=frozenset({card_id}))
    return _update_player(state, idx, fast_replace(p, future_rewards=tuple(slots)))


def schedule_animals(
    state: GameState, idx: int, rounds: Iterable[int], animals: Animals,
) -> GameState:
    """Add `animals` to player `idx`'s future_rewards for each 1-indexed round in
    `rounds` that is still in the game (slot r-1). Additive (repeated placers stack on
    the same slot); rounds outside 1..14 are dropped. The animals are collected at the
    start of each scheduled round by `engine._collect_future_rewards` (granted via
    `helpers.grant_animals`); if they overflow the farm, the accommodation barrier lets
    the player choose which to keep. The animal sibling of `schedule_resources` (Acorns
    Basket; the boar half of Hauberg)."""
    p = state.players[idx]
    slots = list(p.future_rewards)
    for rnd in rounds:
        slot = rnd - 1
        if 0 <= slot < len(slots):
            slots[slot] = slots[slot] + FutureReward(animals=animals)
    return _update_player(state, idx, fast_replace(p, future_rewards=tuple(slots)))
