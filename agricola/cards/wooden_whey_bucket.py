"""Wooden Whey Bucket (minor improvement, D16; Dulcinaria Expansion; cost 1 wood + 1 food).

Card text: "Each time before you use the "Sheep Market"/"Cattle Market" accumulation
space, you can build exactly 1 stable for 1 wood/at no cost." Printed 0 VP.

The paired-slash text is a per-space CORRESPONDENCE (not a player-count variant):
the FIRST slash in the SPACE list pairs with the FIRST slash in the COST clause, so
- Sheep Market  -> build a stable for 1 WOOD,
- Cattle Market -> build a stable at NO COST.
This mirrors Forest Lake Hut's verified crossed mapping (Fishing -> wood / Forest ->
food). The asymmetric cost is unusual but is what the paired text says.

Category: an action-space hook (granted sub-action) on the two NON-ATOMIC animal-market
spaces. "Each time before you use [space]" fires in the BEFORE phase (the explicit
"before", and "each time you use" maps to before_action_space anyway). Building a stable
consumes a farmyard cell and may be unwanted, so the grant is the player's CHOICE -> an
OPTIONAL trigger (register, not register_auto): surfaced as a FireTrigger that the player
may decline by going straight to the market's own accommodation. Once-per-use is gated on
CARD_ID not in the host frame's `triggers_resolved`.

Eligibility computes the grant's cost from the SAME space_id it will build with (1 wood at
sheep_market, free at cattle_market) and gates on `_can_build_stable` at that cost, so it
never offers an unaffordable grant nor blocks an affordable free one. Timing is BEFORE the
market animals are taken, which is correct: the stable raises capacity ahead of acquiring
the animals (the card's whole purpose).

Sheep Market and Cattle Market are non-atomic — `_initiate_sheep_market` /
`_initiate_cattle_market` always push a PendingSheepMarket / PendingCattleMarket host frame
and fire before_action_space from there — so no `register_action_space_hook` is needed (that
index only gates the conditional hosting of ATOMIC spaces). The granted stable build reuses
the PendingBuildStables primitive (cap 1, the per-space cost).
"""
from __future__ import annotations

from agricola.cards.specs import register_minor
from agricola.cards.triggers import register
from agricola.legality import _can_build_stable
from agricola.pending import PendingBuildStables, push
from agricola.resources import Cost, Resources
from agricola.state import GameState

CARD_ID = "wooden_whey_bucket"
SPACES = frozenset({"sheep_market", "cattle_market"})


def _stable_cost(space_id: str) -> Resources:
    """Per-space stable cost: 1 wood at Sheep Market, free at Cattle Market."""
    return Resources(wood=1) if space_id == "sheep_market" else Resources()


def _eligible(state: GameState, idx: int, triggers_resolved) -> bool:
    top = state.pending_stack[-1]
    if CARD_ID in triggers_resolved or top.space_id not in SPACES:
        return False
    return _can_build_stable(state, state.players[idx], _stable_cost(top.space_id))


def _apply(state: GameState, idx: int) -> GameState:
    space_id = state.pending_stack[-1].space_id
    return push(state, PendingBuildStables(
        player_idx=idx, initiated_by_id=f"card:{CARD_ID}",
        cost=_stable_cost(space_id), max_builds=1))


register_minor(CARD_ID, cost=Cost(resources=Resources(wood=1, food=1)))
register("before_action_space", CARD_ID, _eligible, _apply)
